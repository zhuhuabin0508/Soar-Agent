"""⑤ AlertRule 阶段：告警规则匹配（严格模式：未命中不产生告警）。

位于 Translator 与 Normalizer 之间，对解析成功的条目做告警判定：
- 匹配类规则（rule_type=match）：按 (priority ASC, id ASC) 依次匹配
  （作用域：全局或按设备类型），首条命中即停，按规则动作处理：
  - alert：保留该条目产生告警；写入 alert_rule_id / alert_rule_name，
    应用字段配置 field_mapping（静态值/字段映射/保留，XDR 双控件；
    旧规则回退 override 的名称模板/等级覆盖）+ 附加标签；
  - adjust_level：保留该条目产生告警，按 level_map 调整风险等级；
  - suppress：移除该条目（不产生告警，且不计入统计窗口）；
- 统计类规则（rule_type=stats）：条件为输入筛选，事件计入滑动窗口
  （基于 occur_timestamp；count 计数 / count_distinct 去重计数，
  按 group_by 分组键独立计数），窗口内计数 ≥ 阈值时对当前触发事件
  产生告警；匹配类规则已产生告警的事件仅计数不重复告警；
- 全部未命中且无统计窗口可计入：移除该条目（严格模式，不产生告警）。

可观测性：
- 每次命中写 alert_rule_hits（含抑制/调整/统计触发），仅保留近 7 天
  （小时级节流清理）；
- 命中 alert/adjust_level/stats 触发且最终风险等级为高危及以上（<=1）
  时推送通知中心（同一规则 5 分钟节流）。

被移除的条目解析本身已成功，仍记录终态接收明细（status=success/partial，
parse_error 携带不产生告警的原因说明，含统计窗口当前计数）与解析指标。
匹配前把 ``parse_status``（result.status）注入范式化字段，条件可直接引用。

条件结构（兼容两代）：
- 旧版扁平：conditions=[{field,op,value}] + match 列（all/any）；
- 新版嵌套：conditions={"logic":"all","items":[叶 | {"type":"group",
  "logic":"any","items":[...]}]}，组最多两层嵌套（API 校验）。
操作符语义复用 Filter 阶段的 _match_op。

规则缓存：模块级短 TTL（15s）+ API 写入时主动失效（写后立即生效）；
草稿（draft=1）不参与线上匹配。
"""
import json
import logging
import threading
import time
from collections import deque
from datetime import datetime, timedelta

from ..registry import stage_registry
from .base_stage import BaseStage, PipelineData
from .filter_stage import _match_op

logger = logging.getLogger(__name__)

# 风险等级标准词表（与 Translator 阶段一致；覆盖 risk_level 时同步补 name）
RISK_LEVEL_NAMES = {0: "严重", 1: "高危", 2: "中危", 3: "低危", 4: "信息"}

# 动作全集（alert/suppress/adjust_level；未知动作按 alert 兜底处理）
ACTIONS = ("alert", "suppress", "adjust_level")

# 高危及以上通知节流：同一规则 N 秒内不重复推送
_NOTIFY_THROTTLE_SECONDS = 300
_notify_last: dict[int, float] = {}
_notify_lock = threading.Lock()

# 命中记录清理节流：每小时最多清理一次（删除 7 天前记录）
_HITS_RETENTION_DAYS = 7
_hits_cleanup_ts: float = 0.0

# ===== 统计滑动窗口（内存实现；单容器部署，多接收线程共享）=====
# rule_id → {group_key: deque[(事件时间, 去重字段值|None)]}
_stats_windows: dict[int, dict[str, deque]] = {}
_stats_lock = threading.Lock()
# 单规则单分组窗口最大缓存事件数（防内存膨胀；超出丢弃最旧）
_STATS_WINDOW_MAX_EVENTS = 10000

# 窗口单位 → 秒
_WINDOW_UNIT_SECONDS = {"minute": 60, "hour": 3600, "day": 86400}


def _stats_window_seconds(window: dict) -> int:
    """统计/聚合窗口配置 {value, unit} → 秒数（非法配置回退 1 分钟）。"""
    if not isinstance(window, dict):
        return 60
    unit = _WINDOW_UNIT_SECONDS.get(str(window.get("unit") or "minute"), 60)
    try:
        value = max(1, int(window.get("value") or 1))
    except (TypeError, ValueError):
        value = 1
    return value * unit


def _event_time(norm) -> datetime:
    """事件时间：优先 occur_timestamp（datetime 或 ISO 字符串），缺失用当前北京时间。"""
    from app.core.timezone import beijing_now

    ts = norm.get_field("occur_timestamp")
    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, str) and ts.strip():
        try:
            return datetime.fromisoformat(ts.strip().replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            pass
    return beijing_now()


def _stats_feed(buckets: dict, rule: dict, norm) -> dict:
    """把事件计入给定滑动窗口桶并判定阈值（调用方负责隔离/加锁）。

    buckets: {group_key: deque[(事件时间, 去重值|None)]}，由调用方持有
    （线上计数用模块级 _stats_windows，测试模拟用局部 dict）。
    返回 {group_key, count, threshold, triggered}。
    """
    cfg = rule.get("stats_config") or {}
    try:
        threshold = max(1, int(cfg.get("threshold") or 1))
    except (TypeError, ValueError):
        threshold = 1
    method = str(cfg.get("method") or "count")
    distinct_field = str(cfg.get("distinct_field") or "")
    window = timedelta(seconds=_stats_window_seconds(cfg.get("window") or {}))
    now = _event_time(norm)
    cutoff = now - window
    group_by = cfg.get("group_by") if isinstance(cfg.get("group_by"), list) else []
    group_key = "|".join(str(norm.get_field(f) or "") for f in group_by)[:255]
    value = None
    if method == "count_distinct" and distinct_field:
        value = str(norm.get_field(distinct_field) or "")
    dq = buckets.setdefault(group_key, deque())
    dq.append((now, value))
    while dq and dq[0][0] < cutoff:  # 滑出窗口的旧事件剪枝
        dq.popleft()
    while len(dq) > _STATS_WINDOW_MAX_EVENTS:  # 内存上限保护
        dq.popleft()
    if method == "count_distinct" and distinct_field:
        count = len({v for _, v in dq})
    else:
        count = len(dq)
    return {"group_key": group_key, "count": count, "threshold": threshold, "triggered": count >= threshold}


def record_stats_event(rule: dict, norm) -> dict:
    """线上统计计数：事件计入模块级滑动窗口（加锁），返回窗口判定。"""
    rid = rule.get("id") or 0
    with _stats_lock:
        buckets = _stats_windows.setdefault(rid, {})
        return _stats_feed(buckets, rule, norm)


def reset_stats_windows(rule_id: int | None = None) -> None:
    """清空统计窗口计数（规则删除/修改/导入后由缓存失效一并调用）。"""
    with _stats_lock:
        if rule_id is None:
            _stats_windows.clear()
        else:
            _stats_windows.pop(rule_id, None)


def simulate_stats(rule: dict, sample_norms: list) -> list[dict]:
    """测试模拟（只读）：样例依次计入临时滑动窗口，不污染线上计数。

    输入筛选（作用域 + 条件）不匹配的样例不计入窗口。
    返回每条样例 {matched, reason?, group_key, count, threshold, triggered}。
    """
    buckets: dict = {}
    out = []
    for norm in sample_norms:
        device_type = norm.get_field("device_type") or ""
        if rule.get("scope") == "device_type" and rule.get("device_type") != device_type:
            out.append({"matched": False, "reason": "作用域不匹配", "triggered": False})
            continue
        cond_ok, _ = _eval_rule_conditions(norm, rule)
        if not cond_ok:
            out.append({"matched": False, "reason": "输入条件不匹配", "triggered": False})
            continue
        rec = _stats_feed(buckets, rule, norm)
        rec["matched"] = True
        out.append(rec)
    return out


# ===== 规则缓存（模块级，多 worker 线程共享）=====
_RULE_CACHE_TTL = 15.0
_rules_cache: list[dict] = []
_rules_cache_ts: float = 0.0
_rules_cache_lock = threading.Lock()


def invalidate_alert_rules_cache() -> None:
    """API 写入告警规则后调用：立即失效缓存（下一事件重新加载）+ 清空统计窗口。"""
    global _rules_cache, _rules_cache_ts
    with _rules_cache_lock:
        _rules_cache = []
        _rules_cache_ts = 0.0
    # 规则变更后旧窗口计数语义失效（配置可能已改），统一清零重计
    reset_stats_windows()


def load_enabled_rules() -> list[dict]:
    """加载线上生效的告警规则（启用 + 非草稿；缓存 15s；按 priority ASC, id ASC）。

    返回纯 dict 列表（脱离 ORM 会话），字段：
    id/name/scope/device_type/match/conditions/rule_type/action/override/
    stats_config/field_mapping/alert_aggregation/group。
    """
    global _rules_cache, _rules_cache_ts
    with _rules_cache_lock:
        if _rules_cache and time.monotonic() - _rules_cache_ts < _RULE_CACHE_TTL:
            return _rules_cache
    from app.database import SessionLocal
    from app.models.alert_rule import AlertRule

    rules: list[dict] = []
    db = SessionLocal()
    try:
        rows = (
            db.query(AlertRule)
            .filter(AlertRule.enabled == 1, AlertRule.draft == 0)
            .order_by(AlertRule.priority.asc(), AlertRule.id.asc())
            .all()
        )
        for r in rows:
            rules.append(_rule_to_engine_dict(r))
    finally:
        db.close()
    with _rules_cache_lock:
        _rules_cache = rules
        _rules_cache_ts = time.monotonic()
    return rules


def _parse_json(raw, default):
    """规则 JSON 列安全反序列化。"""
    try:
        parsed = json.loads(raw) if raw else default
    except (ValueError, TypeError):
        return default
    return parsed


def _rule_to_engine_dict(r) -> dict:
    """规则 ORM → 引擎匹配用 dict（缓存项同构，脱离会话）。"""
    conditions = _parse_json(r.conditions, [])
    override = _parse_json(r.override, {})
    stats_config = _parse_json(r.stats_config, None)
    field_mapping = _parse_json(r.field_mapping, {})
    alert_aggregation = _parse_json(r.alert_aggregation, None)
    return {
        "id": r.id,
        "name": r.name or "",
        "priority": r.priority if r.priority is not None else 100,
        "scope": (r.scope or "global").lower(),
        "device_type": r.device_type or "",
        "match": (r.match or "all").lower(),
        "conditions": conditions if isinstance(conditions, (list, dict)) else [],
        "rule_type": (r.rule_type or "match").lower(),
        "action": (r.action or "alert").lower(),
        "override": override if isinstance(override, dict) else {},
        "stats_config": stats_config if isinstance(stats_config, dict) else None,
        "field_mapping": field_mapping if isinstance(field_mapping, dict) else {},
        "alert_aggregation": alert_aggregation if isinstance(alert_aggregation, dict) else None,
        "group": r.rule_group or "其他",
    }


def get_alert_aggregation_config(rule_id) -> dict | None:
    """查询规则的告警聚合配置（复用规则缓存；未配置返回 None）。

    供 Normalizer 阶段在告警落库前做同键同窗合并。
    """
    if not rule_id:
        return None
    for rule in load_enabled_rules():
        if rule.get("id") == rule_id:
            cfg = rule.get("alert_aggregation")
            if isinstance(cfg, dict) and cfg.get("keys"):
                return cfg
            return None
    return None


# ===== 条件评估（兼容旧版扁平 + 新版嵌套结构）=====
def _eval_leaf(norm, cond: dict) -> tuple[bool, dict]:
    """单条件（叶节点）判定。"""
    field = cond.get("field") or ""
    op = (cond.get("op") or "eq").lower()
    expected = cond.get("value")
    passed = False
    if field:
        passed = _match_op(norm.get_field(field), op, expected)
    return passed, {"field": field, "op": op, "value": expected, "passed": passed}


def _eval_cond_tree(norm, node) -> tuple[bool, dict | None]:
    """递归评估条件树节点。

    - 叶节点 {field, op, value} → 单条件判定，明细 {field,op,value,passed}；
    - 组节点 {type:'group', logic:'all'|'any', items:[...]} → 递归聚合，
      明细 {type:'group', logic, passed, items:[子明细...]}（供测试面板渲染）。
    """
    if not isinstance(node, dict):
        return False, None
    if node.get("type") == "group":
        logic = node.get("logic") or "all"
        items = node.get("items") or []
        child_results, child_details = [], []
        for it in items:
            ok, detail = _eval_cond_tree(norm, it)
            child_results.append(ok)
            child_details.append(detail)
        passed = bool(child_results) and (
            all(child_results) if logic != "any" else any(child_results)
        )
        return passed, {"type": "group", "logic": logic, "passed": passed, "items": child_details}
    return _eval_leaf(norm, node)


def _eval_rule_conditions(norm, rule: dict) -> tuple[bool, list]:
    """评估规则条件（自动兼容旧版扁平 / 新版嵌套结构）。

    返回 (是否命中, 明细列表)。明细：叶 → {field,op,value,passed}；
    组 → {type:'group',logic,passed,items:[...]}。空条件视为不匹配
    （安全默认，避免空条件规则放行全部日志）。
    """
    raw = rule.get("conditions")
    if isinstance(raw, dict) and isinstance(raw.get("items"), list):
        logic = raw.get("logic") or rule.get("match") or "all"
        results, details = [], []
        for it in raw["items"]:
            ok, detail = _eval_cond_tree(norm, it)
            results.append(ok)
            details.append(detail)
        if not results:
            return False, []
        return (all(results) if logic != "any" else any(results)), details
    # 旧版扁平：[{field,op,value}] + match 列
    details = []
    for cond in raw if isinstance(raw, list) else []:
        if not isinstance(cond, dict):
            continue
        _, detail = _eval_leaf(norm, cond)
        details.append(detail)
    if not details:
        return False, details
    results = [d["passed"] for d in details]
    match = rule.get("match") or "all"
    return (all(results) if match != "any" else any(results)), details


def _conditions_match(norm, rule: dict) -> bool:
    """规则条件是否命中（明细丢弃版，流水线快路径）。"""
    matched, _ = _eval_rule_conditions(norm, rule)
    return matched


# 兼容旧调用方（API 测试端点旧签名）：(norm, match, conditions)
def _eval_conditions(norm, match: str, conditions) -> tuple[bool, list]:
    return _eval_rule_conditions(norm, {"match": match, "conditions": conditions})


def match_alert_rules(norm, rules: list[dict] | None = None) -> dict | None:
    """对单条范式化事件匹配匹配类规则，返回首条命中的规则 dict（未命中返回 None）。

    作用域过滤：scope=global 对所有日志生效；scope=device_type 仅对
    device_type 相同的日志生效。匹配顺序即 rules 列表顺序（priority ASC）。
    调用方应传入匹配类（rule_type=match）规则；统计类规则走独立窗口计数。
    供流水线阶段与 API 规则测试端点共用。
    """
    if rules is None:
        rules = [r for r in load_enabled_rules() if r.get("rule_type") != "stats"]
    device_type = norm.get_field("device_type") or ""
    for rule in rules:
        if rule.get("scope") == "device_type" and rule.get("device_type") != device_type:
            continue
        if _conditions_match(norm, rule):
            return rule
    return None


def render_name_template(template: str, fields: dict) -> str:
    """渲染告警名称模板：``{field}`` 用解析后字段值插值，缺失字段留空。

    fields 为 AlertEvent 列名 → 值 的 dict（norm.to_alert_fields()）。
    模板不含 ``{`` 时原样返回（零开销快路径）。
    """
    if not template or "{" not in template:
        return template

    class _SafeDict(dict):
        def __missing__(self, key):  # 缺失变量留空，避免 KeyError
            return ""

    return str(template).format_map(_SafeDict({k: ("" if v is None else str(v)) for k, v in (fields or {}).items()}))


def _merge_tags(norm, new_tags: list) -> None:
    """附加标签：追加到 risk_tag（JSON 安全：读取→合并去重→写回 JSON 字符串）。"""
    if not new_tags:
        return
    raw = norm.get_field("risk_tag")
    existing: list = []
    if isinstance(raw, list):
        existing = [str(t) for t in raw]
    elif isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                existing = [str(t) for t in parsed]
        except (ValueError, TypeError):
            existing = []
    merged = existing + [str(t) for t in new_tags if str(t) not in existing]
    norm.set_field("risk_tag", json.dumps(merged, ensure_ascii=False))


def _apply_adjust_level(norm, level_map) -> None:
    """调整等级：按映射 {原等级: 新等级} 调整，未映射等级保留原值。"""
    if not isinstance(level_map, dict) or not level_map:
        return
    current = norm.get_field("risk_level")
    if current is None:
        return
    try:
        key = str(int(current))
    except (TypeError, ValueError):
        return
    if key not in level_map:
        return
    try:
        level = int(level_map[key])
    except (TypeError, ValueError):
        return
    norm.set_field("risk_level", level)
    norm.set_field("risk_level_name", RISK_LEVEL_NAMES.get(level, ""))


def _apply_field_mapping(norm, mapping: dict) -> None:
    """应用字段配置（XDR 双控件）：static 静态值 / map 字段映射 / keep 保留。

    - alert_name static：值作为名称模板，支持 ``{field}`` 变量插值；
    - risk_level static：整型等级，同步 risk_level_name；
    - map：目标字段 ← 解析字段（值为 AlertEvent 列名）；
    - keep：保留解析结果（不处理）。
    """
    if not isinstance(mapping, dict) or not mapping:
        return
    fields = norm.to_alert_fields()
    for target, cfg in mapping.items():
        if not isinstance(cfg, dict):
            continue
        mode = cfg.get("mode")
        value = cfg.get("value")
        if mode == "keep":
            continue
        if mode == "map":
            if isinstance(value, str) and value:
                norm.set_field(target, fields.get(value))
        elif mode == "static":
            if target == "alert_name":
                norm.set_field("alert_name", render_name_template(str(value or ""), fields))
            elif target == "risk_level":
                try:
                    level = int(value)
                except (TypeError, ValueError):
                    continue
                norm.set_field("risk_level", level)
                norm.set_field("risk_level_name", RISK_LEVEL_NAMES.get(level, ""))
            else:
                norm.set_field(target, value)


def apply_rule_action(norm, rule: dict) -> dict:
    """应用命中规则的动作（alert / adjust_level / stats 触发）到范式化事件。

    写入规则标识 + 应用字段配置与覆盖项，返回最终告警字段 dict。
    字段配置优先；未配置的目标回退 override（旧规则兼容）。
    供流水线阶段与 API 测试预览共用。
    """
    norm.set_field("alert_rule_id", rule["id"])
    norm.set_field("alert_rule_name", rule["name"])
    override = rule.get("override") or {}
    mapping = rule.get("field_mapping") if isinstance(rule.get("field_mapping"), dict) else {}
    if rule["action"] == "adjust_level":
        _apply_adjust_level(norm, override.get("level_map"))
    else:
        _apply_field_mapping(norm, mapping)
        if "alert_name" not in mapping and override.get("alert_name"):
            norm.set_field(
                "alert_name", render_name_template(str(override["alert_name"]), norm.to_alert_fields())
            )
        if "risk_level" not in mapping and override.get("risk_level") is not None:
            try:
                level = int(override["risk_level"])
                norm.set_field("risk_level", level)
                norm.set_field("risk_level_name", RISK_LEVEL_NAMES.get(level, ""))
            except (TypeError, ValueError):
                pass
        _merge_tags(norm, override.get("tags") or [])
    return norm.to_alert_fields()


def verify_rule_passes_samples(rule: dict, sample_norms: list) -> tuple[bool, str]:
    """发布门禁校验：规则对样例集是否"测试通过"。

    - 匹配类：任一样例命中（作用域 + 条件）即通过；
    - 统计类：样例依次计入同一临时窗口，任一计数点达到阈值即通过。
    """
    if rule.get("rule_type") == "stats":
        sims = simulate_stats(rule, sample_norms)
        ok = any(s.get("triggered") for s in sims)
        return ok, ("统计模拟达到阈值，测试通过" if ok else "统计模拟未达阈值：请提供足够多条同窗口样例（如按源IP 5分钟 ≥10 需 ≥10 条同 IP 样例）")
    for norm in sample_norms:
        device_type = norm.get_field("device_type") or ""
        if rule.get("scope") == "device_type" and rule.get("device_type") != device_type:
            continue
        matched, _ = _eval_rule_conditions(norm, rule)
        if matched:
            return True, "样例命中规则，测试通过"
    return False, "所有样例均未命中该规则（请检查作用域与匹配条件）"


def _bump_hit_counts(hits: dict[int, int]) -> None:
    """累计规则命中数（独立短会话，仿 ReceiverSink._bump_counts 模式）。"""
    from sqlalchemy import text as sa_text

    from app.database import SessionLocal

    db = SessionLocal()
    try:
        for rid, cnt in hits.items():
            db.execute(
                sa_text("UPDATE alert_rules SET hit_count = hit_count + :c WHERE id = :id"),
                {"c": cnt, "id": rid},
            )
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("告警规则 hit_count 累计失败（不影响流水线）")
    finally:
        db.close()


def _record_hits(rows: list[dict]) -> None:
    """写命中记录（独立短会话）+ 小时级节流清理 7 天前数据。"""
    global _hits_cleanup_ts
    from app.core.timezone import beijing_now
    from app.database import SessionLocal
    from app.models.alert_rule_hit import AlertRuleHit

    db = SessionLocal()
    try:
        db.add_all([AlertRuleHit(**r) for r in rows])
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("告警规则命中记录写入失败（不影响流水线）")
    finally:
        db.close()

    now = time.monotonic()
    if now - _hits_cleanup_ts < 3600:
        return
    _hits_cleanup_ts = now
    db = SessionLocal()
    try:
        from sqlalchemy import delete as sa_delete

        cutoff = beijing_now() - timedelta(days=_HITS_RETENTION_DAYS)
        db.execute(sa_delete(AlertRuleHit).where(AlertRuleHit.matched_at < cutoff))
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("告警规则命中记录清理失败")
    finally:
        db.close()


def _notify_high_risk(rule: dict, norm, fields: dict) -> None:
    """高危及以上（risk_level<=1）命中推送通知中心（同一规则 5 分钟节流）。"""
    global _notify_last
    # 等级门槛前置：仅高危及以上推送（调用方已过滤，此处兜底防误用）
    level = fields.get("risk_level")
    level = level if isinstance(level, int) else -1
    if level > 1:
        return
    rid = rule.get("id") or 0
    now = time.monotonic()
    with _notify_lock:
        if now - _notify_last.get(rid, 0) < _NOTIFY_THROTTLE_SECONDS:
            return
        _notify_last[rid] = now
    try:
        from app.core.notification_dispatch import dispatch_notification
        from app.core.timezone import beijing_now
        from app.database import SessionLocal

        level_name = RISK_LEVEL_NAMES.get(level, "未知")
        name = fields.get("alert_name") or "未命名告警"
        db = SessionLocal()
        try:
            dispatch_notification(
                db,
                event_type="alert_high_risk",
                title=f"【{level_name}】{name}",
                content=(
                    f"告警规则「{rule.get('name')}」命中高危及以上告警：\n"
                    f"告警名称：{name}\n风险等级：{level_name}\n"
                    f"源 IP：{fields.get('src_ip') or '--'} → 目的 IP：{fields.get('dst_ip') or '--'}\n"
                    f"命中时间：{beijing_now().strftime('%Y-%m-%d %H:%M:%S')}"
                ),
                related_type="alert_rule",
                related_id=rid,
            )
            db.commit()
        finally:
            db.close()
    except Exception:  # noqa: BLE001
        logger.exception("高危告警通知推送失败（不影响流水线）")


def _record_suppressed(sink, data, result, norm, rule) -> None:
    """抑制/未命中条目记终态接收明细 + 解析指标（解析本身已成功）。"""
    if rule is not None:
        reason = (rule.get("override") or {}).get("reason") or ""
        note = f"命中抑制规则「{rule['name']}」（#{rule['id']}）"
        if reason:
            note += f"：{reason}"
        note += "，不产生告警"
    else:
        note = "未命中任何启用中的告警规则，不产生告警（严格模式）"
    sink.record_parsed(
        data.event.raw, result.status, note,
        strategy_id=result.strategy_id,
        strategy_name=result.strategy_name,
        rule_id=result.rule_id,
        log_type=result.log_type,
        parsed_fields=result.fields or None,
    )
    if data.engine is not None and data.engine.sink is not None:
        data.engine.sink.record_metrics(
            data.stat_hour, result.strategy_id, result.strategy_name,
            result.status, result.parse_ms,
        )


@stage_registry.register
class AlertRuleStage(BaseStage):
    """告警规则匹配步骤（严格模式：未命中任何规则的日志不落告警表）。"""

    name = "alert_rule"

    def process(self, data: PipelineData, sink, db) -> None:
        if not data.results:
            return
        rules = load_enabled_rules()
        match_rules = [r for r in rules if r.get("rule_type") != "stats"]
        stats_rules = [r for r in rules if r.get("rule_type") == "stats"]
        raw = data.event.raw
        kept_results, kept_normalized = [], []
        hits: dict[int, int] = {}  # rule_id → 本事件命中条数（批量累计 hit_count）
        hit_rows: list[dict] = []  # 命中记录（含抑制/调整/统计触发，近 7 天）
        suppressed = no_rule = stats_waiting = stats_fired = 0

        def _alert_path(result, norm, rule) -> None:
            """命中产生告警（匹配类 alert/adjust_level 或统计触发）共通处理。"""
            apply_rule_action(norm, rule)
            hits[rule["id"]] = hits.get(rule["id"], 0) + 1
            final = norm.to_alert_fields()
            hit_rows.append({
                "rule_id": rule["id"], "rule_name": rule["name"],
                "action": rule["action"], "uuid": str(final.get("uuid") or ""),
                "source_ip": str(final.get("src_ip") or "")[:255],
                "alert_name": str(final.get("alert_name") or "")[:512],
                "risk_level": final.get("risk_level") if isinstance(final.get("risk_level"), int) else -1,
                "parse_status": result.status,
            })
            # 高危及以上命中推送通知中心（节流去重）
            if isinstance(final.get("risk_level"), int) and final["risk_level"] <= 1:
                _notify_high_risk(rule, norm, final)
            kept_results.append(result)
            kept_normalized.append(norm)

        for result, norm in zip(data.results, data.normalized):
            # 注入解析状态供条件引用（如宽松兜底模板 parse_status == success）
            norm.set_field("parse_status", result.status)

            # 1) 匹配类规则优先链（首条命中即停）
            rule = match_alert_rules(norm, match_rules)
            if rule is not None and rule["action"] == "suppress":
                # 抑制拦截一切：不产生告警、不计入统计窗口
                suppressed += 1
                cur = norm.to_alert_fields()
                hit_rows.append({
                    "rule_id": rule["id"], "rule_name": rule["name"],
                    "action": "suppress", "uuid": str(cur.get("uuid") or ""),
                    "source_ip": str(cur.get("src_ip") or "")[:255],
                    "alert_name": str(cur.get("alert_name") or "")[:512],
                    "risk_level": cur.get("risk_level") if isinstance(cur.get("risk_level"), int) else -1,
                    "parse_status": result.status,
                })
                _record_suppressed(sink, data, result, norm, rule)
                continue

            # 2) 统计类规则独立计数（抑制不拦截才到这里；输入筛选匹配即计入）
            triggered_stats = None  # (rule, rec) 首个达到阈值的统计规则
            first_counted = None    # (rule, rec) 首个计入窗口的统计规则（未触发时的说明来源）
            for srule in stats_rules:
                device_type = norm.get_field("device_type") or ""
                if srule.get("scope") == "device_type" and srule.get("device_type") != device_type:
                    continue
                if not _conditions_match(norm, srule):
                    continue
                rec = record_stats_event(srule, norm)
                if first_counted is None:
                    first_counted = (srule, rec)
                if rec["triggered"] and triggered_stats is None:
                    triggered_stats = (srule, rec)

            # 3) 产生告警：匹配类规则优先；无匹配时统计触发兜底（单事件单告警）
            if rule is not None:
                _alert_path(result, norm, rule)
                continue
            if triggered_stats is not None:
                stats_fired += 1
                _alert_path(result, norm, triggered_stats[0])
                continue

            # 4) 未产生告警：统计窗口已计入 / 完全未命中
            if first_counted is not None:
                stats_waiting += 1
                srule, rec = first_counted
                note = (
                    f"计入统计规则「{srule['name']}」（#{srule['id']}）窗口"
                    f"（{rec['group_key'] or '全部分组'}：当前 {rec['count']}/{rec['threshold']}），"
                    "未达阈值不产生告警"
                )
                sink.record_parsed(
                    raw, result.status, note,
                    strategy_id=result.strategy_id,
                    strategy_name=result.strategy_name,
                    rule_id=result.rule_id,
                    log_type=result.log_type,
                    parsed_fields=result.fields or None,
                )
                if data.engine is not None and data.engine.sink is not None:
                    data.engine.sink.record_metrics(
                        data.stat_hour, result.strategy_id, result.strategy_name,
                        result.status, result.parse_ms,
                    )
                continue
            no_rule += 1
            _record_suppressed(sink, data, result, norm, None)

        data.results = kept_results
        data.normalized = kept_normalized
        # 批量累计规则命中数 + 写命中记录（独立会话，失败不影响流水线主事务）
        if hits:
            _bump_hit_counts(hits)
        if hit_rows:
            _record_hits(hit_rows)
        if suppressed or no_rule or stats_waiting or stats_fired:
            logger.info(
                "AlertRule 阶段：产生告警 %s（统计触发 %s）/ 抑制 %s / 窗口计数未触发 %s / 未命中 %s"
                "（receiver=%s 规则数=%s）",
                len(kept_results) - stats_fired, stats_fired, suppressed, stats_waiting, no_rule,
                data.event.receiver_id, len(rules),
            )
