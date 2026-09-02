"""内置 mock 服务：IP 风险研判智能体 + 封禁工具。

用于开发/验收环境替代真实外部服务：
- ``POST /internal/agent/ip-risk-analyze``：按告警上下文返回预置研判结论，
  支持 ``alert_context.mock_scenario`` 强制指定场景（ban_direct / ban_confirm /
  monitor / banned / fail / invalid_json），便于端到端验收。
- ``POST /internal/ban/record-ban``：记录调用参数并返回 record_id，
  IP 前缀 ``9.9.9.`` 模拟下发失败（HTTP 500）。

/internal 前缀不做用户态鉴权（仅供进程内工作流调用，等价 webhook）。
"""
import itertools
import logging
import threading

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["internal-mock"])

# mock 封禁记录：ip -> {record_id, plan}（进程内存，重启清空）
_ban_store: dict[str, dict] = {}
_ban_lock = threading.Lock()
_record_seq = itertools.count(1)


class AlertContext(BaseModel):
    alert_name: str = ""
    risk_level: str = ""
    threat_class: str = ""
    occur_timestamp: int | str | None = None
    src_country: str = ""
    mock_scenario: str = ""


class AnalyzeRequest(BaseModel):
    ip: str
    alert_context: AlertContext | None = None


class BanRequest(BaseModel):
    ip: str
    ban_level: str = "medium"
    ban_duration: int = 3600
    is_permanent: bool = False
    reason: str = ""
    region: str = ""


def _ban_plan(level: str = "high", duration: int = 3600, reason: str = "") -> dict:
    return {
        "ban_level": level,
        "ban_duration": duration,
        "is_permanent": False,
        "reason": reason,
        "region": "全网",
    }


@router.post("/agent/ip-risk-analyze")
def mock_ip_risk_analyze(body: AnalyzeRequest) -> dict:
    """mock 智能体：按场景返回预置结构化 JSON。

    默认判定逻辑（未指定 mock_scenario 时）：
    - 国内 IP（src_country=中国）→ 封禁 + 需人工确认
    - 严重/高危 且境外 → 封禁 + 免确认（直接封禁）
    - 其余 → 持续监控
    - 已在 mock 封禁名单 → is_banned=true
    """
    ctx = body.alert_context or AlertContext()
    ip = body.ip
    scenario = ctx.mock_scenario
    country = ctx.src_country or ""

    # IP 前缀场景约定（与封禁 mock 的 9.9.9. 约定一致，便于从入库入口端到端验收）：
    # - 7.7.7.* → 模拟智能体服务异常（HTTP 500）
    # - 5.5.5.* → 模拟响应缺少必填字段（按解析失败处理）
    if ip.startswith("7.7.7."):
        scenario = "fail"
    elif ip.startswith("5.5.5."):
        scenario = "invalid_json"

    # 场景强制覆盖（验收用）
    if scenario == "fail":
        raise HTTPException(status_code=500, detail="mock agent failure")
    if scenario == "invalid_json":
        return {"is_banned": False, "risk_level": "高危"}  # 缺少必填字段 → 调用方按解析失败处理
    if scenario == "banned":
        return _response(True, "高危", "ban", False, _ban_plan(reason="mock：已在封禁名单"), "已封禁 IP 重复告警", ["该 IP 已在封禁名单中"])
    if scenario == "ban_direct":
        return _response(False, "严重", "ban", False, _ban_plan("critical", 86400, "mock：境外高危恶意 IP"), "持续观察封禁后流量", ["境外恶意 IP", "威胁情报命中"])
    if scenario == "ban_confirm":
        return _response(False, "高危", "ban", True, _ban_plan("high", 7200, "mock：国内 IP 需人工确认"), "确认后封禁并观察", ["国内 IP 归属资产", "需人工复核"])
    if scenario == "monitor":
        return _response(False, "低危", "monitor", False, {}, "加入观察名单，持续监控 24 小时", ["风险等级较低", "建议持续观察"])

    # 已封禁判断（mock 封禁名单）
    with _ban_lock:
        already = ip in _ban_store
    if already:
        return _response(True, "高危", "ban", False, _ban_plan(reason="重复触发：已在封禁名单"), "无需重复封禁", ["该 IP 已在封禁名单中"])

    # 默认场景判定
    if country == "中国":
        return _response(False, "高危", "ban", True, _ban_plan("high", 7200, f"国内 IP 涉嫌{ctx.alert_name or '恶意行为'}，建议人工确认后封禁"), "确认后封禁并观察内网影响", ["国内 IP 归属资产", "需人工复核业务影响"])
    if ctx.risk_level in ("严重", "高危") and country not in ("中国", ""):
        return _response(False, ctx.risk_level, "ban", False, _ban_plan("critical" if ctx.risk_level == "严重" else "high", 86400, f"境外{ctx.risk_level}恶意 IP：{ctx.alert_name}"), "封禁后持续观察该网段", ["境外恶意 IP", f"告警等级 {ctx.risk_level}", f"威胁分类 {ctx.threat_class}"])
    return _response(False, ctx.risk_level or "低危", "monitor", False, {}, "加入观察名单，持续监控 24 小时", ["风险等级较低或信息不足", "建议持续观察"])


def _response(is_banned, risk_level, action, need_confirm, ban_plan, advice, reasons) -> dict:
    """构造带 _meta 元数据的标准响应（token 数为 mock 估值）。"""
    return {
        "is_banned": is_banned,
        "risk_level": risk_level,
        "action": action,
        "need_confirm": need_confirm,
        "ban_plan": ban_plan,
        "monitoring_advice": advice,
        "reasons": reasons,
        "_meta": {"model": "mock-ip-risk-agent", "input_tokens": 356, "output_tokens": 128},
    }


@router.post("/ban/record-ban")
def mock_record_ban(body: BanRequest) -> dict:
    """mock 封禁工具：记录调用参数，返回 record_id；9.9.9.* 前缀模拟失败。"""
    if body.ip.startswith("9.9.9."):
        raise HTTPException(status_code=500, detail="mock ban tool failure")
    with _ban_lock:
        record_id = f"BR-{next(_record_seq):06d}"
        _ban_store[body.ip] = {
            "record_id": record_id,
            "ban_level": body.ban_level,
            "ban_duration": body.ban_duration,
            "is_permanent": body.is_permanent,
            "reason": body.reason,
            "region": body.region,
        }
    logger.info("[mock] 封禁下发: ip=%s level=%s record_id=%s", body.ip, body.ban_level, record_id)
    return {"success": True, "record_id": record_id}


@router.get("/ban/records")
def mock_ban_records() -> dict:
    """mock 封禁工具记录查询（调试用）。"""
    with _ban_lock:
        return {"records": dict(_ban_store)}
