"""资产管理智能体定时扫描任务。

每小时扫描所有「资产管理智能体」（engine=hermes 且 enabled_tools 含 discover_new_kbs），
检查是否有新勾选但尚未梳理到资产表的知识库。若发现新知识库，触发 Hermes 引擎
自动梳理资产并录入资产表。

触发方式：
- Celery beat 定时调度（celery_app.conf.beat_schedule，每小时整点）
- API 手动触发（POST /api/v1/assets/scan → scan_asset_agents.delay()）

设计要点：
- 先用轻量 DB 查询检查是否有新知识库（避免无谓地启动 LLM）
- 仅在有新知识库时才实例化 HermesAgentExecutor（重量级：构建 LLM + 工具引擎）
- 每个智能体在独立 DB session + 独立 asyncio 事件循环中运行，互不干扰
- 系统用户取第一个 active admin（Celery 无 HTTP 请求上下文）
"""
import asyncio
import logging
from typing import Any, Optional

from app.core.celery_app import celery_app
from app.database import SessionLocal
from app.models.agent import Agent
from app.models.asset import Asset
from app.models.user import User

logger = logging.getLogger(__name__)

# 资产管理智能体识别标记：enabled_tools 中含此工具名即视为资产智能体
_ASSET_AGENT_MARKER = "discover_new_kbs"

# 自动扫描时发送给智能体的提示词
_SCAN_PROMPT = (
    "请检查是否有新增的知识库需要梳理资产。"
    "先调用 discover_new_kbs 发现尚未梳理的知识库，"
    "对每个新知识库调用 fetch_kb_content 拉取内容，"
    "然后逐段提取资产信息并调用 add_asset 录入（source=kb_ingest）。"
    "录入前务必先 query_asset 检查是否已存在，避免重复录入。"
    "完成后用 list_assets 汇总当前资产总数。"
)


def _find_asset_agents(db) -> list[Agent]:
    """查找所有资产管理智能体（engine=hermes 且 enabled_tools 含 discover_new_kbs）。"""
    agents = db.query(Agent).filter(Agent.engine == "hermes").all()
    return [
        agent for agent in agents
        if _ASSET_AGENT_MARKER in (agent.enabled_tools or [])
    ]


def _find_new_kbs(db, agent: Agent) -> list[dict]:
    """检查智能体是否有新勾选但尚未梳理的知识库（直接 DB 查询，不经过工具）。

    与 discover_new_kbs 工具逻辑一致，但在 Celery 侧直接查 DB，
    避免无新知识库时白启动一次 Hermes 引擎（LLM 调用开销大）。
    """
    from app.models.knowledge_base import KnowledgeBase

    kb_ids = list(agent.enabled_kbs or [])
    if not kb_ids:
        return []
    # 已梳理的 kb_id（assets 表中存在的）
    ingested = set(
        r[0] for r in db.query(Asset.kb_id).filter(
            Asset.agent_id == agent.id,
            Asset.kb_id.in_(kb_ids),
        ).distinct().all()
    )
    # 查询 KB 名称
    kbs = db.query(KnowledgeBase).filter(KnowledgeBase.id.in_(kb_ids)).all()
    kb_name_map = {kb.id: kb.name for kb in kbs}
    new_kbs = []
    for kb_id in kb_ids:
        if kb_id not in ingested:
            new_kbs.append({
                "kb_id": kb_id,
                "kb_name": kb_name_map.get(kb_id, f"知识库-{kb_id}"),
            })
    return new_kbs


def _get_system_user(db) -> Optional[User]:
    """获取系统管理员用户（用于 Celery 任务中执行智能体的 user 上下文）。

    Celery 任务无 HTTP 请求上下文，无法从 JWT 获取当前用户。
    取第一个 active admin 作为系统用户。
    """
    admin = db.query(User).filter(
        User.role == "admin", User.is_active.is_(True)
    ).first()
    if admin is not None:
        return admin
    # 降级：取任意 active 用户
    return db.query(User).filter(User.is_active.is_(True)).first()


async def _run_agent_scan(agent_id: int, user_id: int) -> dict[str, Any]:
    """异步运行资产管理智能体扫描新知识库。

    实例化 HermesAgentExecutor 并发送扫描提示词，
    消费 SSE 事件流直到完成，返回扫描结果摘要。

    Args:
        agent_id: 智能体 ID（在独立 session 中重新查询，避免 detached 实例）
        user_id: 系统用户 ID

    Returns:
        扫描结果摘要 dict。
    """
    from app.agent.hermes import HermesAgentExecutor

    # 为每次扫描创建独立 DB session（避免长事务占用连接）
    db = SessionLocal()
    try:
        agent = db.query(Agent).filter(Agent.id == agent_id).first()
        if agent is None:
            return {"ok": False, "error": f"Agent {agent_id} 不存在"}
        user = db.query(User).filter(User.id == user_id).first()
        if user is None:
            return {"ok": False, "error": f"User {user_id} 不存在"}

        executor = HermesAgentExecutor(
            db=db,
            agent=agent,
            user=user,
            log_handler=lambda level, msg: logger.log(
                getattr(logging, level.upper(), logging.INFO),
                f"[asset-scan agent={agent.id}] {msg}",
            ),
        )

        final_reply = ""
        tool_calls = 0
        errors: list[str] = []
        session_id = f"asset-scan-{agent_id}"

        async for event in executor.run(_SCAN_PROMPT, session_id=session_id):
            if event.type == "token":
                final_reply += event.content
            elif event.type == "tool_end":
                tool_calls += 1
            elif event.type == "error":
                errors.append(event.message)

        return {
            "ok": len(errors) == 0,
            "agent_id": agent_id,
            "agent_name": agent.name,
            "tool_calls": tool_calls,
            "errors": errors,
            "reply_length": len(final_reply),
            "reply_preview": final_reply[:500],
        }
    finally:
        db.close()


@celery_app.task(name="scan_asset_agents", soft_time_limit=600, time_limit=720)
def scan_asset_agents() -> dict[str, Any]:
    """定时扫描所有资产管理智能体，发现新知识库并自动梳理资产。

    每小时由 Celery beat 触发。遍历所有 engine=hermes 且 enabled_tools 含
    discover_new_kbs 的智能体，检查是否有新勾选但尚未梳理的知识库，
    若有则触发 Hermes 引擎自动梳理。

    Returns:
        ``{"scanned": N, "triggered": M, "details": [...]}``
    """
    logger.info("资产管理智能体定时扫描任务启动")
    db = SessionLocal()
    try:
        asset_agents = _find_asset_agents(db)
        system_user = _get_system_user(db)
        if system_user is None:
            logger.error("未找到可用用户，无法执行资产扫描任务")
            return {"scanned": 0, "triggered": 0, "error": "无可用用户"}

        details: list[dict] = []
        triggered = 0
        for agent in asset_agents:
            new_kbs = _find_new_kbs(db, agent)
            if not new_kbs:
                logger.info("Agent %s (%s): 无新知识库，跳过", agent.id, agent.name)
                details.append({
                    "agent_id": agent.id,
                    "agent_name": agent.name,
                    "action": "skip",
                    "reason": "无新知识库",
                })
                continue

            kb_names = [kb["kb_name"] for kb in new_kbs]
            logger.info(
                "Agent %s (%s): 发现 %d 个新知识库 %s，触发扫描",
                agent.id, agent.name, len(new_kbs), kb_names,
            )
            try:
                result = asyncio.run(
                    _run_agent_scan(agent.id, system_user.id)
                )
                triggered += 1
                details.append({
                    "agent_id": agent.id,
                    "agent_name": agent.name,
                    "action": "scanned",
                    "new_kbs": new_kbs,
                    "result": result,
                })
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "Agent %s (%s) 扫描失败: %s", agent.id, agent.name, exc
                )
                details.append({
                    "agent_id": agent.id,
                    "agent_name": agent.name,
                    "action": "failed",
                    "new_kbs": new_kbs,
                    "error": str(exc),
                })

        logger.info(
            "资产管理智能体定时扫描完成: 扫描 %d 个，触发 %d 个",
            len(asset_agents), triggered,
        )
        return {
            "scanned": len(asset_agents),
            "triggered": triggered,
            "details": details,
        }
    finally:
        db.close()
