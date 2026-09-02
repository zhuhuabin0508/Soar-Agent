"""工作流执行 Celery 任务（阶段四重构版）。

支持条件路由、AI 决策、防火墙封禁、人工审批阻塞与节点轨迹记录。
执行采用 BFS 遍历：从入度为 0 的入口节点出发，根据节点类型分发处理，
遇到 ``condition_branch`` 时依据 ``context["decision"]`` 选择生效下游分支；
当决策为 ``need_human_approval`` 时，通过 Redis 阻塞等待人工审批信号。
"""
import asyncio
import logging
from collections import deque
from datetime import datetime
from app.core.timezone import beijing_now, beijing_now_iso
from typing import Any, Callable, Optional

from app.agent.decision import run_agent_decision
from app.core.celery_app import celery_app
from app.core.dag import find_next_nodes
from app.core.redis_client import get_redis
from app.database import SessionLocal
from app.devices.firewall import block_ip_on_firewall
from app.models import Execution, ExecutionLog, ExecutionTrace

logger = logging.getLogger(__name__)


def _persist_logs(execution_id: Optional[int], logs: list[dict]) -> None:
    """将执行过程中收集的日志批量写入 ExecutionLog 表。

    Args:
        execution_id: 关联的 Execution 记录 ID；为 None 时直接返回不持久化。
        logs: 日志列表，每项含 ``node_id`` / ``level`` / ``message``。
    """
    if execution_id is None or not logs:
        return
    db = SessionLocal()
    try:
        for entry in logs:
            db.add(
                ExecutionLog(
                    execution_id=execution_id,
                    node_id=entry.get("node_id"),
                    level=entry.get("level", "info"),
                    message=entry.get("message", ""),
                )
            )
        db.commit()
        logger.info("已持久化 %d 条执行日志: execution_id=%s", len(logs), execution_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("持久化执行日志失败: %s", exc)
        db.rollback()
    finally:
        db.close()


@celery_app.task(
    name="execute_workflow",
    # P0-5：单任务超时（覆盖全局配置），防止死循环或卡住的 AI 调用
    soft_time_limit=300,
    time_limit=360,
)
def execute_workflow(
    workflow_id: int,
    payload: dict,
    graph_config: dict,
    execution_id: Optional[int] = None,
) -> dict:
    """异步执行工作流（支持条件路由 / AI 决策 / 封禁 / 人工审批）。

    Args:
        workflow_id: 工作流 ID。
        payload: 触发该执行的告警 payload（含 src_ip / dest_ip / alert_type 等）。
        graph_config: 工作流图配置，含 ``nodes`` 与 ``edges``。
        execution_id: 关联的 Execution 记录 ID，用于回写状态与节点轨迹。
            为 None 时仅执行不持久化。

    Returns:
        ``{"status": "success"/"failed", "context": context}``。
    """
    logger.info(
        "工作流开始执行: workflow_id=%s, execution_id=%s", workflow_id, execution_id
    )
    logger.debug("Payload: %s", payload)
    logger.debug("Graph config: %s", graph_config)

    # 贯穿执行的日志收集列表与回调
    logs: list[dict] = []

    def log(node_id: str, level: str, message: str) -> None:
        """收集日志到 logs 列表（结束时由 _persist_logs 批量写入 DB）。"""
        logs.append({"node_id": node_id, "level": level, "message": message})
        logger.debug("[exec-log] %s/%s: %s", node_id, level, message)

    log("workflow", "info", f"工作流开始执行: workflow_id={workflow_id}, execution_id={execution_id}")

    nodes: list[dict] = graph_config.get("nodes", [])
    edges: list[dict] = graph_config.get("edges", [])
    node_map: dict[str, dict] = {n["id"]: n for n in nodes}

    # 计算入度，确定入口节点（入度为 0）
    in_degree: dict[str, int] = {n["id"]: 0 for n in nodes}
    for edge in edges:
        target = edge.get("target")
        if target in in_degree:
            in_degree[target] += 1
    entry_nodes: list[str] = [nid for nid, deg in in_degree.items() if deg == 0]
    logger.info("入口节点(入度=0): %s", entry_nodes)
    log("workflow", "info", f"入口节点(入度=0): {entry_nodes}")

    if not entry_nodes:
        logger.error("未找到入口节点，工作流终止: workflow_id=%s", workflow_id)
        log("workflow", "error", "未找到入口节点，工作流终止")
        _persist_logs(execution_id, logs)
        _finalize_execution(execution_id, status="failed", result={"error": "no entry node"})
        return {"status": "failed", "context": {}}

    # 执行上下文：存各节点结果与跨节点共享数据
    context: dict[str, Any] = {"payload": payload}

    # 工作流级自定义变量：graph_config.variables = [{ name, description, default_value }]
    from app.core.workflow_runner import resolve_variables
    variables_list = graph_config.get("variables", []) or []
    workflow_vars: dict[str, Any] = {}
    for v in variables_list:
        name = v.get("name") if isinstance(v, dict) else None
        if name:
            workflow_vars[name] = v.get("default_value")
    context["variables"] = workflow_vars
    # 内置上下文变量
    context["execution_id"] = execution_id
    context["workflow_id"] = workflow_id
    context["timestamp"] = beijing_now_iso()
    if workflow_vars:
        log("workflow", "info", f"已加载 {len(workflow_vars)} 个工作流变量: {list(workflow_vars.keys())}")

    # 环境变量：从数据库加载并解密注入 ctx.env（供 ${env.名称} 引用）
    try:
        from app.core.security import decrypt_env_value
        from app.models.workflow import Workflow as _Workflow

        _env_db = SessionLocal()
        try:
            wf_for_env = _env_db.query(_Workflow).filter(_Workflow.id == workflow_id).first()
            env_vars_plain: dict[str, str] = {}
            if wf_for_env is not None:
                for v in (wf_for_env.env_vars or []):
                    if isinstance(v, dict) and v.get("name"):
                        env_vars_plain[v["name"]] = decrypt_env_value(v.get("value") or "")
            if env_vars_plain:
                context["env"] = env_vars_plain
                log("workflow", "info", f"已加载 {len(env_vars_plain)} 个环境变量: {list(env_vars_plain.keys())}")
        finally:
            _env_db.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("加载环境变量失败（忽略继续）: %s", exc)

    db = SessionLocal()
    execution: Optional[Execution] = None
    if execution_id is not None:
        execution = (
            db.query(Execution).filter(Execution.id == execution_id).first()
        )
        if execution is not None:
            execution.status = "running"
            db.commit()
            logger.info("Execution 状态更新为 running: id=%s", execution_id)

    # BFS 遍历
    queue: deque[str] = deque(entry_nodes)
    visited: set[str] = set()
    approval_handled: bool = False

    try:
        while queue:
            node_id = queue.popleft()
            if node_id in visited:
                continue
            visited.add(node_id)

            node = node_map.get(node_id)
            if node is None:
                logger.warning("节点不在图中，跳过: %s", node_id)
                continue

            node_type: str = node.get("type", "unknown")
            node_data: dict = node.get("data", {}) or {}
            # 执行前解析节点 data 中的 ${var} 变量引用（深拷贝后替换，不污染原图）
            node_data = resolve_variables(node_data, context)
            node_label: Optional[str] = node_data.get("label") or node.get("label")

            logger.info(
                "执行节点: id=%s, type=%s, label=%s", node_id, node_type, node_label
            )
            log(node_id, "info", f"开始执行节点: type={node_type}, label={node_label}")

            # 准备节点输入快照
            node_input = _build_node_input(node_type, node_data, context, payload)

            # 创建轨迹记录（started_at 由 DB server_default 生成）
            trace: Optional[ExecutionTrace] = None
            if execution_id is not None:
                trace = ExecutionTrace(
                    execution_id=execution_id,
                    node_id=node_id,
                    node_type=node_type,
                    node_label=node_label,
                    input=node_input,
                    status="running",
                )
                db.add(trace)
                db.commit()
                db.refresh(trace)
                logger.debug(
                    "轨迹记录已创建: trace_id=%s, node_id=%s", trace.id, node_id
                )

            # 执行节点
            try:
                output = _execute_node(node_type, node_data, context, payload, log=log)
                logger.info("节点执行成功: id=%s, output=%s", node_id, output)
                log(node_id, "info", f"节点执行成功: {output}")
            except Exception as exc:
                logger.exception("节点执行异常: id=%s, error=%s", node_id, exc)
                log(node_id, "error", f"节点执行异常: {exc}")
                if trace is not None:
                    trace.status = "failed"
                    trace.output = {"error": str(exc)}
                    trace.finished_at = beijing_now()
                    db.commit()
                _persist_logs(execution_id, logs)
                _finalize_execution(
                    execution_id,
                    status="failed",
                    result={"error": str(exc), "context": _safe_context(context)},
                )
                return {"status": "failed", "context": _safe_context(context)}

            # 写回轨迹输出
            if trace is not None:
                trace.status = "success"
                trace.output = output
                trace.finished_at = beijing_now()
                db.commit()
                logger.debug(
                    "轨迹记录已更新: trace_id=%s, status=success", trace.id
                )

            context[node_id] = output

            # 确定下游节点
            decision_value: Optional[str] = None
            if node_type == "condition_branch":
                decision_value = context.get("decision")
                logger.info(
                    "条件路由: node=%s, decision=%s", node_id, decision_value
                )
                log(node_id, "info", f"条件路由决策: decision={decision_value}")

            next_ids = find_next_nodes(edges, node_id, decision_value)

            # 人工审批阻塞触发条件：
            #   a) condition_branch 决策为 need_human_approval（兼容旧逻辑）
            #   b) human_review 节点（独立人工介入节点，走到即生成工单等待）
            need_approval = (
                node_type == "human_review"
                or (
                    node_type == "condition_branch"
                    and decision_value == "need_human_approval"
                )
            )
            if need_approval and not approval_handled:
                approval_handled = True
                logger.info(
                    "进入人工审批阻塞: execution_id=%s, node=%s, type=%s",
                    execution_id,
                    node_id,
                    node_type,
                )
                log(node_id, "info", "进入人工审批阻塞，等待审批信号")
                # 节点级元数据（标题/说明）一并写入工单，便于工作台展示
                node_meta = {
                    "title": node_data.get("title") or node_data.get("label") or "",
                    "description": node_data.get("description") or "",
                    "instructions": node_data.get("instructions") or "",
                }
                signal = _wait_for_approval(
                    execution_id, context, db, execution, node_meta
                )
                if signal == "reject":
                    logger.info(
                        "审批被拒绝（忽略），工作流结束: execution_id=%s", execution_id
                    )
                    log(node_id, "info", "工作人员选择忽略，工作流结束")
                    _persist_logs(execution_id, logs)
                    _finalize_execution(
                        execution_id,
                        status="success",
                        result={
                            "context": _safe_context(context),
                            "outcome": "rejected",
                            "review_node_id": node_id,
                        },
                    )
                    return {
                        "status": "success",
                        "context": _safe_context(context),
                        "outcome": "rejected",
                    }
                logger.info(
                    "审批通过（同意封禁），继续执行: execution_id=%s", execution_id
                )
                log(node_id, "info", "工作人员同意封禁，继续执行下游")
                context["human_review_decision"] = "approve"

            # 入队下游节点
            for nid in next_ids:
                if nid not in visited:
                    queue.append(nid)
                    logger.debug("入队下游节点: %s", nid)

        # 全部节点执行完成
        logger.info(
            "工作流执行完成: workflow_id=%s, execution_id=%s", workflow_id, execution_id
        )
        log("workflow", "info", "工作流执行完成")
        _persist_logs(execution_id, logs)
        _finalize_execution(
            execution_id,
            status="success",
            result={"context": _safe_context(context)},
        )
        return {"status": "success", "context": _safe_context(context)}
    finally:
        db.close()


def _execute_node(
    node_type: str,
    node_data: dict,
    context: dict,
    payload: dict,
    log: Optional[Callable[[str, str, str], None]] = None,
) -> dict:
    """根据节点类型执行对应逻辑并返回输出。

    Args:
        node_type: 节点类型。
        node_data: 节点附加数据。
        context: 执行上下文（可读写，用于跨节点传递 decision 等）。
        payload: 触发执行的告警 payload。
        log: 可选日志回调 ``(node_id, level, message)``；为 None 时仅写 logger。

    Returns:
        节点执行结果字典。
    """
    node_id = str(node_data.get("id", "") or node_data.get("node_id", "") or "unknown")

    def _emit(level: str, message: str) -> None:
        """同时写 logger 与可选 log 回调。"""
        getattr(logger, level if level in ("info", "warning", "error", "debug") else "info")(message)
        if log is not None:
            try:
                log(node_id, level, message)
            except Exception as exc:  # noqa: BLE001
                logger.debug("log 回调异常: %s", exc)

    if node_type == "webhook_trigger":
        logger.info("webhook_trigger: 接收告警 payload")
        _emit("info", "webhook_trigger: 接收告警 payload")
        return {"received": True, "alert_data": payload}

    if node_type == "http_request":
        url = node_data.get("url", "mock://request")
        logger.info("http_request: mock 请求 url=%s", url)
        _emit("info", f"http_request: mock 请求 url={url}")
        return {"status_code": 200, "body": "ok", "url": url}

    if node_type == "ai_agent":
        logger.info("ai_agent: 调用 AI 决策, payload=%s", payload)
        _emit("info", "ai_agent: 调用 AI 决策")
        # P0-5：AI 决策加 60s 超时，防止 LLM 调用卡住整个工作流
        try:
            agent_result = asyncio.run(
                asyncio.wait_for(run_agent_decision(payload), timeout=60)
            )
        except asyncio.TimeoutError:
            logger.error("ai_agent: AI 决策超时（60s）")
            _emit("error", "ai_agent: AI 决策超时（60s），使用降级决策")
            # 超时降级：返回 need_human_approval，转人工处理
            agent_result = {
                "decision": "need_human_approval",
                "target_ip": payload.get("src_ip", "unknown"),
                "reason": "AI 决策超时，需人工确认",
                "duration": "24h",
                "messages": [],
                "logs": [{"level": "error", "message": "AI 决策超时"}],
            }
        logger.info("ai_agent: 决策结果=%s", agent_result)
        _emit("info", f"ai_agent: 决策结果={agent_result.get('decision')}")
        # 将决策结果写入上下文，供 condition_branch 与 block_ip 使用
        context["decision"] = agent_result.get("decision")
        context["agent_decision"] = agent_result
        context["agent_messages"] = agent_result.get("messages", [])
        return agent_result

    if node_type == "condition_branch":
        decision = context.get("decision")
        logger.info("condition_branch: 当前决策=%s", decision)
        _emit("info", f"condition_branch: 当前决策={decision}")
        return {"decision": decision}

    if node_type == "block_ip":
        agent_decision = context.get("agent_decision", {}) or {}
        target_ip = agent_decision.get("target_ip") or payload.get(
            "src_ip", "unknown"
        )
        duration = agent_decision.get("duration", "24h")
        reason = agent_decision.get("reason", "auto block by SOAR")
        logger.info(
            "block_ip: 调用防火墙封禁 ip=%s, duration=%s, reason=%s",
            target_ip,
            duration,
            reason,
        )
        _emit("info", f"block_ip: 封禁 ip={target_ip}, duration={duration}")
        result = asyncio.run(
            block_ip_on_firewall(target_ip, duration, reason)
        )
        logger.info("block_ip: 封禁结果=%s", result)
        _emit("info", f"block_ip: 封禁结果={result.get('status')}")
        context["block_result"] = result
        return result

    if node_type == "send_notification":
        logger.info("send_notification: mock 发送通知")
        _emit("info", "send_notification: mock 发送通知")
        return {"sent": True, "channel": node_data.get("channel", "email")}

    if node_type == "end":
        logger.info("end: 工作流结束节点")
        _emit("info", "end: 工作流结束节点")
        return {"status": "ended", "end_type": node_data.get("end_type", "success")}

    if node_type == "human_review":
        # 同步执行路径（test-run）下不阻塞，仅标记需人工审批
        logger.info("human_review: 人工介入节点（同步模式不阻塞）")
        _emit("info", "human_review: 已生成工单，等待工作人员审批")
        return {
            "status": "waiting_for_approval",
            "message": "人工审批节点，等待工作人员处理",
            "title": node_data.get("title") or node_data.get("label") or "",
            "instructions": node_data.get("instructions") or "",
        }

    logger.warning("未知节点类型，返回默认结果: type=%s", node_type)
    _emit("warning", f"未知节点类型，返回默认结果: type={node_type}")
    return {"executed": True}


def _build_node_input(
    node_type: str, node_data: dict, context: dict, payload: dict
) -> dict:
    """为节点轨迹构建输入快照。

    Args:
        node_type: 节点类型。
        node_data: 节点附加数据。
        context: 当前执行上下文。
        payload: 告警 payload。

    Returns:
        该节点的输入字典（用于轨迹记录）。
    """
    if node_type == "webhook_trigger":
        return {"payload": payload}
    if node_type == "ai_agent":
        return {"payload": payload}
    if node_type == "condition_branch":
        return {"decision": context.get("decision")}
    if node_type == "block_ip":
        agent_decision = context.get("agent_decision", {}) or {}
        return {
            "target_ip": agent_decision.get("target_ip") or payload.get("src_ip"),
            "duration": agent_decision.get("duration"),
            "reason": agent_decision.get("reason"),
        }
    if node_type == "http_request":
        return {"url": node_data.get("url")}
    if node_type == "human_review":
        return {
            "title": node_data.get("title") or node_data.get("label") or "",
            "instructions": node_data.get("instructions") or "",
            "ctx_keys": list(context.keys()),
        }
    if node_type == "end":
        return {"end_type": node_data.get("end_type", "success")}
    return {}


def _wait_for_approval(
    execution_id: Optional[int],
    context: dict,
    db,
    execution: Optional[Execution],
    node_meta: Optional[dict] = None,
) -> str:
    """阻塞等待人工审批信号。

    将 Execution 状态置为 ``waiting_for_approval``，并把完整上下文与
    节点元数据写入 result 字段供工作台读取；随后向 Redis
    ``approval_queue`` 推送 execution_id，并通过 ``brpop`` 阻塞等待
    ``approval:{execution_id}`` 信号。

    Args:
        execution_id: 执行记录 ID。
        context: 执行上下文（含 payload、各节点输出等完整信息）。
        db: 数据库会话。
        execution: Execution ORM 对象。
        node_meta: 触发审批的节点元数据（title/description/instructions）。

    Returns:
        审批信号字符串（"approve" 或 "reject"）。
    """
    redis_client = get_redis()
    node_meta = node_meta or {}

    if execution is not None:
        execution.status = "waiting_for_approval"
        execution.result = {
            # 完整上下文，供工作台展示所有节点输入输出
            "context": _safe_context(context),
            # 兼容旧审批中心字段（仅含告警与 Agent 决策）
            "alert_data": context.get("payload"),
            "agent_messages": context.get("agent_messages", []),
            "agent_decision": context.get("agent_decision", {}),
            # 节点级元数据
            "review_meta": node_meta,
        }
        db.commit()
        logger.info(
            "Execution 状态更新为 waiting_for_approval: id=%s", execution_id
        )

    if execution_id is not None:
        redis_client.lpush("approval_queue", execution_id)
        logger.info("已推入审批队列: approval_queue <- %s", execution_id)

    logger.info("开始阻塞等待审批信号: approval:%s", execution_id)
    result = redis_client.brpop(f"approval:{execution_id}", timeout=0)
    signal: str = result[1] if result else "reject"
    logger.info(
        "收到审批信号: execution_id=%s, signal=%s", execution_id, signal
    )

    # 恢复执行状态
    if execution is not None:
        execution.status = "running"
        db.commit()
        logger.info(
            "Execution 状态恢复为 running: id=%s, signal=%s", execution_id, signal
        )

    return signal


def _finalize_execution(
    execution_id: Optional[int], status: str, result: dict
) -> None:
    """更新 Execution 最终状态与完成时间。

    Args:
        execution_id: 执行记录 ID；为 None 时直接返回。
        status: 最终状态（success / failed）。
        result: 最终结果数据。
    """
    if execution_id is None:
        return
    db = SessionLocal()
    try:
        execution = (
            db.query(Execution).filter(Execution.id == execution_id).first()
        )
        if execution is None:
            logger.warning(
                "Finalize 时未找到 Execution: id=%s", execution_id
            )
            return
        execution.status = status
        execution.result = result
        execution.finished_at = beijing_now()
        db.commit()
        logger.info(
            "Execution 已终结: id=%s, status=%s, finished_at=%s",
            execution_id,
            status,
            execution.finished_at,
        )

        # 执行失败时走通知规则路由派发通知
        if status == "failed":
            try:
                from app.core.notification_dispatch import dispatch_notification
                from app.models.workflow import Workflow as _Workflow

                wf = (
                    db.query(_Workflow)
                    .filter(_Workflow.id == execution.workflow_id)
                    .first()
                ) if execution.workflow_id else None
                wf_name = wf.name if wf else f"#{execution.workflow_id}"
                error_msg = ""
                if isinstance(result, dict):
                    err = result.get("error")
                    if err:
                        error_msg = str(err)[:300]
                dispatch_notification(
                    db,
                    event_type="execution_failed",
                    title=f"工作流执行失败：{wf_name}",
                    content=(
                        f"工作流「{wf_name}」执行失败。\n"
                        f"执行 ID：{execution_id}\n"
                        f"{'错误：' + error_msg if error_msg else '请查看执行追溯获取详情'}\n"
                        f"时间：{beijing_now().strftime('%Y-%m-%d %H:%M:%S')}"
                    ),
                    related_type="execution",
                    related_id=execution_id,
                    created_by="system",
                )
                logger.info("execution_failed 通知已派发: execution_id=%s", execution_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("派发 execution_failed 通知失败: %s", exc)
    finally:
        db.close()


def _safe_context(context: dict) -> dict:
    """对上下文做安全序列化（剥离不可 JSON 序列化的对象）。

    Args:
        context: 执行上下文。

    Returns:
        可安全写入 JSON 列的字典。
    """
    try:
        import json

        return json.loads(json.dumps(context, default=str, ensure_ascii=False))
    except Exception:
        return {"_serializable": False}
