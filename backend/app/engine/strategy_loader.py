"""策略加载与路由匹配。

维护 enabled 策略的内存缓存；根据原始数据外层特征匹配策略。
策略变更时调用 :meth:`StrategyLoader.refresh` 刷新缓存。

引擎只消费 ``dict`` 形式的策略配置，因此可以脱离数据库独立测试
（直接用 :class:`StrategyLoader` 的 ``strategies`` 构造参数注入策略列表）。
"""
import logging
import re
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


def _get_path(obj: Any, path: str, default: Any = None) -> Any:
    """按点分路径从嵌套 dict 中取值。

    Args:
        obj: 根对象（一般为 dict）。
        path: 点分路径，如 ``data.uuId``；空路径直接返回 obj。
        default: 路径不存在时的返回值。

    Returns:
        路径对应的值，不存在返回 default。
    """
    if not path:
        return obj
    cur = obj
    for key in path.split("."):
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return default
    return cur


def _version_key(version: str) -> tuple:
    """把版本字符串转为可比较的数字元组，如 ``1.30`` → ``(1, 30)``。"""
    try:
        return tuple(int(p) for p in str(version or "0").split(".") if p != "")
    except ValueError:
        return (0,)


class StrategyLoader:
    """策略缓存与路由匹配器。

    Args:
        fetch_strategies: 策略加载函数，返回 ``[{"id": int, "config": dict, ...}]`` 列表。
            生产环境传入数据库查询函数；测试时可直接用 ``strategies`` 参数注入。
        strategies: 直接注入的策略列表（优先于 fetch_strategies，供测试使用）。
    """

    def __init__(
        self,
        fetch_strategies: Optional[Callable[[], list[dict]]] = None,
        strategies: Optional[list[dict]] = None,
    ) -> None:
        self._fetch = fetch_strategies
        self._strategies: list[dict] = []
        if strategies:
            # 测试模式：直接使用注入的策略，不触发数据库加载
            self._strategies = self._normalize(strategies)
        else:
            self.refresh()

    # ------------------------------------------------------------------
    # 策略加载
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """从数据源重新加载 enabled 策略到内存缓存。"""
        if not self._fetch:
            return
        try:
            raw = self._fetch()
            self._strategies = self._normalize(raw)
            logger.debug("策略缓存已刷新，共 %d 个 enabled 策略", len(self._strategies))
        except Exception:
            logger.exception("策略缓存刷新失败，保留旧缓存（%d 个策略）", len(self._strategies))

    @staticmethod
    def _normalize(raw_list: list[dict]) -> list[dict]:
        """把策略记录规整为引擎所需结构，仅保留 enabled 策略。"""
        result = []
        for item in raw_list or []:
            status = str(item.get("status") or "enabled").lower()
            if status != "enabled":
                continue
            config = item.get("config") or {}
            if isinstance(config, str):
                import json

                try:
                    config = json.loads(config)
                except (TypeError, ValueError):
                    logger.warning("策略 %s 的 config 不是合法 JSON，跳过", item.get("id"))
                    continue
            result.append(
                {
                    "id": item.get("id"),
                    "strategy_name": config.get("strategy_name") or item.get("strategy_name", ""),
                    "device_type": config.get("device_type") or item.get("device_type", ""),
                    "version": str(config.get("version") or item.get("version") or "0"),
                    "config": config,
                }
            )
        return result

    @property
    def strategies(self) -> list[dict]:
        """当前缓存的 enabled 策略列表。"""
        return self._strategies

    # ------------------------------------------------------------------
    # 路由匹配
    # ------------------------------------------------------------------
    def match(self, raw: dict) -> Optional[dict]:
        """按 route_rules 匹配原始数据，返回命中的策略（dict），无命中返回 None。

        匹配规则：
        - exact：外层字段值完全相等；
        - regex：外层字段值满足正则；
        - 命中多个策略时取 version 最新的。

        Args:
            raw: 原始告警 JSON（dict）。

        Returns:
            命中的策略 ``{"id", "strategy_name", "device_type", "version", "config"}`` 或 None。
        """
        candidates: list[dict] = []
        for strat in self._strategies:
            rules = strat.get("config", {}).get("route_rules") or {}
            match_type = str(rules.get("match_type") or "exact").lower()
            match_field = rules.get("match_field") or ""
            match_value = rules.get("match_value")
            if not match_field:
                continue
            actual = _get_path(raw, match_field)
            hit = False
            if match_type == "regex":
                try:
                    hit = re.fullmatch(str(match_value), str(actual)) is not None
                except re.error:
                    logger.warning("策略 %s 的路由正则非法: %s", strat.get("id"), match_value)
                    hit = False
            else:  # exact
                hit = actual == match_value
            if hit:
                candidates.append(strat)
                logger.debug(
                    "策略路由命中: strategy=%s(%s) field=%s value=%r",
                    strat.get("id"), strat.get("strategy_name"), match_field, actual,
                )

        if not candidates:
            logger.debug("策略路由未命中任何策略")
            return None
        # 多个命中取 version 最新
        best = max(candidates, key=lambda s: _version_key(s.get("version", "0")))
        return best


# 模块级共享的路径取值工具（引擎其他模块复用）
get_path = _get_path
