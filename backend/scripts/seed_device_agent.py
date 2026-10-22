"""设备运营助手智能体播种脚本：意图驱动的设备 API 调用 + clarify 澄清。

用法（容器内，backend 目录）:
    docker exec -w /app -e PYTHONPATH=/app soar-backend-dev python /tmp/seed_device_agent.py

逻辑:
  1. 先调用 ensure_preset_tools 同步工具目录（确保 execute_device_action 已入库）。
  2. 创建/更新 Agent(name=设备运营助手)，enabled_tools 绑定
     query_device_actions / execute_device_action / clarify。
  3. model_config_id 取第一个可用 LLMConfig；无则留空（需后在平台 UI 配置）。

工作流（system_prompt 亦按此约定）:
  意图不明 → query_device_actions 发现设备/动作 → clarify 让用户选择/确认
  → execute_device_action 执行（处置类必须先确认）。
"""
import logging

from sqlalchemy.orm import Session

from app.core.tools.seed_service import ensure_preset_tools
from app.database import SessionLocal
from app.models.agent import Agent
from app.models.llm_config import LLMConfig

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("seed_device_agent")

_AGENT_NAME = "设备运营助手"

_DEVICE_AGENT_TOOLS = [
    "query_device_actions",
    "execute_device_action",
    "clarify",
]

_SYSTEM_PROMPT = """你是设备运营助手，负责根据用户意图调用平台对接设备（如青藤万相主机安全平台等）的 API。严格按以下流程工作：

【第一步：发现】接到设备相关请求后，先调用 query_device_actions 了解可用设备与动作：
- 不确定有哪些设备时，先不传 device_id 获取设备摘要列表；
- 根据用户意图用 keyword 过滤候选动作（如 keyword=主机、弱密码、进程、资产），必要时 full=true 获取完整参数定义。

【第二步：澄清】出现以下任一情况，必须调用 clarify 工具向用户提问，不得擅自猜测：
- 多个设备都可能满足请求（如多台设备都能查主机信息）：让用户选择设备；
- 多个候选动作含义接近：让用户选择动作；
- 动作存在必填参数但用户未提供（如 IP、主机名、时间范围）：向用户询问参数值；
- 用户要求的动作属于处置类或中高风险（risk_level 为 medium/high，如封禁 IP、隔离主机、删除数据、变更配置）：描述将执行的动作、目标与影响，请用户确认。
clarify 的 choices 最多 4 个选项，选项文本应清晰（含设备名/动作名）；用户回答后按其选择继续。

【第三步：执行】调用 execute_device_action，传入确定的 action_id 与完整参数：
- 查询类动作（只读、risk_level=low）确认参数齐全后直接执行；
- 处置类动作必须在用户明确确认后才能执行；
- 结果用中文汇总：成功时提炼关键数据（数量、列表摘要），失败时说明错误原因与建议（如设备凭据未配置、网络不通）。

【纪律】
- 严禁编造 action_id 或参数名，一切以 query_device_actions 返回为准；
- 执行前核对动作归属，确认动作来自用户指定或选择的设备；
- 不执行用户意图之外的任何动作；
- 设备返回错误时如实转述，不虚构结果。"""


def _first_llm_config(db: Session):
    return db.query(LLMConfig).order_by(LLMConfig.id.asc()).first()


def _upsert_agent(db: Session) -> None:
    llm_cfg = _first_llm_config(db)
    agent = db.query(Agent).filter(Agent.name == _AGENT_NAME).first()
    data = dict(
        description=(
            "设备运营助手：根据用户意图调用设备对接 API 查询/处置。"
            "自动发现设备与动作，目标不明确时弹出选项让用户选择，"
            "处置类动作执行前向用户确认。"
        ),
        model_config_id=llm_cfg.id if llm_cfg else None,
        system_prompt=_SYSTEM_PROMPT,
        enabled_tools=_DEVICE_AGENT_TOOLS,
        enabled_skills=[],
        enabled_kbs=[],
        enabled_asset_types=[],
        engine="hermes",
        temperature=0.2,
        max_tokens=4096,
        max_iterations=8,
        enable_memory=False,
        tone_style="professional",
    )
    if agent is None:
        agent = Agent(name=_AGENT_NAME, **data)
        db.add(agent)
        logger.info("Agent 已创建: name=%s", _AGENT_NAME)
        return
    for k, v in data.items():
        setattr(agent, k, v)
    logger.info("Agent 已更新: name=%s", _AGENT_NAME)


def main() -> None:
    # 先同步工具目录，确保 execute_device_action 新工具已入库
    ensure_preset_tools()
    db: Session = SessionLocal()
    try:
        _upsert_agent(db)
        db.commit()
        logger.info("播种完成: 智能体=%s, 工具=%s", _AGENT_NAME, _DEVICE_AGENT_TOOLS)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("播种失败: %s", exc)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
