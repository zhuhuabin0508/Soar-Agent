"""HermesSkillEngine：工作流桥接器。

把 Soar Workflow 作为可中断技能触发。LLM 通过虚拟工具
``trigger_workflow_skill`` 调用本引擎启动一个工作流子流程。

设计要点：
- 不重新实现 DAG 状态机（SOAR 已有 workflow_runner + dag + node_executors）
- 复用现有 human_review 节点的审批机制（Redis 信号 + Execution.status）
- 变量传递用 ``skill_var.render_node_vars``（{{node_id.output.field}} 语法）
- 中断/恢复通过 Execution.status = "waiting_for_approval" 检测
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional
from uuid import uuid4

from app.agent.hermes.skill_var import render_node_vars
from app.agent.hermes.types import SkillContext

logger = logging.getLogger(__name__)


class HermesSkillEngine:
    """工作流桥接器：把 Soar Workflow 作为可中断技能触发。"""

    def __init__(self, db, agent, user, log_handler: Optional[Callable] = None):
        """初始化技能引擎。

        Args:
            db: 数据库会话
            agent: Agent ORM 实例
            user: 当前用户
            log_handler: 可选日志回调 (level, message)
        """
        self.db = db
        self.agent = agent
        self.user = user
        self.log_handler = log_handler
        # 活跃技能上下文（进程内缓存，skill_run_id -> SkillContext）
        self._active_skills: dict[str, SkillContext] = {}

    def _log(self, level: str, message: str) -> None:
        """输出日志。"""
        logger.log(getattr(logging, level.upper(), logging.INFO), message)
        if self.log_handler is not None:
            try:
                self.log_handler(level, message)
            except Exception:  # noqa: BLE001
                pass

    # ========================================================================
    # 工作流技能列表
    # ========================================================================

    def list_workflow_skills(self) -> list[dict]:
        """列出可作为技能触发的工作流（enabled=True）。

        Returns:
            [{"id", "name", "description", "input_schema"}]
            input_schema 从 graph_config 的入口 webhook_trigger 节点推导。
        """
        from app.models.workflow import Workflow

        workflows = (
            self.db.query(Workflow)
            .filter(Workflow.enabled.is_(True))
            .all()
        )
        result: list[dict] = []
        for wf in workflows:
            input_schema = self._infer_input_schema(wf.graph_config)
            # Workflow 模型没有 description 列：从 graph_config 推导，兜底用名称
            gc = wf.graph_config if isinstance(wf.graph_config, dict) else {}
            desc = (gc.get("description") or "").strip() if gc else ""
            if not desc:
                desc = f"工作流：{wf.name}"
            result.append({
                "id": wf.id,
                "name": wf.name,
                "description": desc,
                "input_schema": input_schema,
            })
        return result

    @staticmethod
    def _infer_input_schema(graph_config: dict) -> dict:
        """从 graph_config 推导输入 schema。"""
        nodes = graph_config.get("nodes", []) or []
        for node in nodes:
            node_type = node.get("type", "")
            if node_type in ("webhook_trigger", "manual_trigger", "start"):
                node_data = node.get("data", {}) or {}
                # 简化：返回 payload 的预期结构
                return {
                    "type": "object",
                    "properties": {
                        "input": {
                            "type": "object",
                            "description": "技能输入参数",
                        },
                    },
                    "additionalProperties": True,
                }
        return {"type": "object", "properties": {}, "additionalProperties": True}

    # ========================================================================
    # trigger_workflow_skill 虚拟工具
    # ========================================================================

    def get_trigger_tool_schema(self) -> dict:
        """返回 trigger_workflow_skill 工具的 OpenAI function schema。

        LLM 可调用此工具触发一个工作流作为子流程。
        """
        return {
            "type": "function",
            "function": {
                "name": "trigger_workflow_skill",
                "description": (
                    "触发一个已配置的工作流作为复杂技能。适用于需要多步骤编排、"
                    "人工审批、设备操作的场景。先调用 list_workflow_skills 获取可用技能。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "workflow_id": {
                            "type": "integer",
                            "description": "工作流 ID",
                        },
                        "input": {
                            "type": "object",
                            "description": "技能输入参数",
                            "additionalProperties": True,
                        },
                        "resume_token": {
                            "type": "string",
                            "description": "恢复令牌（恢复被中断的技能时传入）",
                        },
                    },
                    "required": ["workflow_id"],
                },
            },
        }

    def get_list_tool_schema(self) -> dict:
        """返回 list_workflow_skills 工具的 schema。"""
        return {
            "type": "function",
            "function": {
                "name": "list_workflow_skills",
                "description": "列出所有可作为技能触发的工作流（返回 id/name/description）。",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
        }

    # ========================================================================
    # 触发与恢复
    # ========================================================================

    async def trigger_skill(
        self,
        workflow_id: int,
        payload: dict,
        *,
        parent_execution_id: Optional[int] = None,
    ) -> SkillContext:
        """启动一个工作流作为技能。

        流程：
        1. 查 Workflow（enabled=True）
        2. 创建 Execution（trigger_type="agent_skill", agent_id=self.agent.id）
        3. 调 workflow_runner.run_workflow
        4. 检查结果状态：若含 human_review 且 status=waiting_for_approval → 标记中断
        5. 返回 SkillContext

        Args:
            workflow_id: 工作流 ID
            payload: 技能输入参数
            parent_execution_id: 父执行 ID（用于关联）

        Returns:
            SkillContext（status=completed/interrupted/failed）
        """
        from app.models.workflow import Workflow
        from app.models.execution import Execution

        # 1. 查工作流
        wf = self.db.query(Workflow).filter(
            Workflow.id == workflow_id,
            Workflow.enabled.is_(True),
        ).first()
        if wf is None:
            raise ValueError(f"工作流 {workflow_id} 不存在或未启用")

        # 2. 创建执行记录
        skill_run_id = uuid4().hex
        execution = Execution(
            workflow_id=workflow_id,
            trigger_type="agent_skill",
            status="running",
            agent_id=self.agent.id,
        )
        self.db.add(execution)
        self.db.commit()
        self.db.refresh(execution)

        # 3. 构造 SkillContext
        ctx = SkillContext(
            skill_run_id=skill_run_id,
            workflow_id=workflow_id,
            execution_id=execution.id,
            payload=payload,
            node_outputs={},
            status="running",
        )
        self._active_skills[skill_run_id] = ctx

        self._log("info", f"触发工作流技能: workflow_id={workflow_id}, execution_id={execution.id}, run_id={skill_run_id}")

        # 4. 执行工作流
        try:
            from app.core.workflow_runner import run_workflow

            result = await run_workflow(
                graph_config=wf.graph_config,
                payload=payload,
                execution_id=execution.id,
                workflow_id=workflow_id,
                trigger_type="agent_skill",
            )

            # 5. 检查状态
            status = result.get("status", "failed")
            ctx.node_outputs = self._extract_node_outputs(result.get("traces", []))

            if status == "waiting_for_approval":
                # 工作流遇到 human_review 节点，等待审批
                ctx.status = "interrupted"
                ctx.interrupt_node_id = self._find_interrupt_node(result.get("traces", []))
                ctx.pending_approval = {
                    "execution_id": execution.id,
                    "node_id": ctx.interrupt_node_id,
                }
                execution.status = "waiting_for_approval"
                self._log("info", f"工作流技能中断等待审批: run_id={skill_run_id}, node={ctx.interrupt_node_id}")
            elif status == "success":
                ctx.status = "completed"
                execution.status = "success"
                ctx.finished_at = execution.created_at
                self._log("info", f"工作流技能执行完成: run_id={skill_run_id}")
            else:
                ctx.status = "failed"
                execution.status = "failed"
                ctx.finished_at = execution.created_at
                self._log("warning", f"工作流技能执行失败: run_id={skill_run_id}, status={status}")

            execution.result = result
            self.db.commit()

        except Exception as exc:  # noqa: BLE001
            logger.exception("工作流技能执行异常: %s", exc)
            ctx.status = "failed"
            ctx.finished_at = None
            execution.status = "failed"
            execution.result = {"error": str(exc)}
            self.db.commit()
            self._log("error", f"工作流技能执行异常: {exc}")

        return ctx

    async def resume_skill(self, skill_run_id: str, decision: str) -> SkillContext:
        """恢复被中断的技能（审批通过/拒绝后调用）。

        复用现有审批端点机制：approval 已通过 Redis 信号通知 workflow_runner。
        本方法等待工作流继续执行并更新状态。

        Args:
            skill_run_id: 技能运行 ID
            decision: "approve" 或 "reject"

        Returns:
            更新后的 SkillContext
        """
        ctx = self._active_skills.get(skill_run_id)
        if ctx is None:
            raise ValueError(f"技能运行不存在或已完成: {skill_run_id}")

        if ctx.status != "interrupted":
            self._log("warning", f"技能未处于中断状态: run_id={skill_run_id}, status={ctx.status}")
            return ctx

        from app.models.execution import Execution

        execution = self.db.query(Execution).filter(Execution.id == ctx.execution_id).first()
        if execution is None:
            raise ValueError(f"执行记录不存在: {ctx.execution_id}")

        self._log("info", f"恢复工作流技能: run_id={skill_run_id}, decision={decision}")

        if decision == "reject":
            ctx.status = "failed"
            execution.status = "rejected"
            self.db.commit()
            self._log("info", f"工作流技能被拒绝: run_id={skill_run_id}")
            return ctx

        # approve：等待工作流继续执行（审批信号已由 /approvals/{id}/approve 发送）
        # 这里轮询 Execution.status 直到不再是 waiting_for_approval
        import asyncio

        for _ in range(60):  # 最多等 60 秒
            self.db.refresh(execution)
            if execution.status != "waiting_for_approval":
                break
            await asyncio.sleep(1)

        if execution.status == "waiting_for_approval":
            ctx.status = "interrupted"
            self._log("warning", f"工作流技能恢复超时: run_id={skill_run_id}")
        elif execution.status == "success":
            ctx.status = "completed"
            self._log("info", f"工作流技能恢复完成: run_id={skill_run_id}")
        else:
            ctx.status = "failed"
            self._log("warning", f"工作流技能恢复后失败: run_id={skill_run_id}, status={execution.status}")

        return ctx

    # ========================================================================
    # 变量解析
    # ========================================================================

    def resolve_node_var(self, skill_run_id: str, expr: str) -> Any:
        """解析 {{node_id.output.field}} 表达式。

        从 SkillContext.node_outputs 取值。

        Args:
            skill_run_id: 技能运行 ID
            expr: 表达式字符串

        Returns:
            解析后的值；技能不存在返回 None
        """
        ctx = self._active_skills.get(skill_run_id)
        if ctx is None:
            return None
        rendered = render_node_vars(expr, ctx.node_outputs)
        # 若替换成功（不再含 {{），尝试解析为 JSON
        if "{{" not in rendered:
            import json

            try:
                return json.loads(rendered)
            except (json.JSONDecodeError, ValueError):
                return rendered
        return None

    # ========================================================================
    # 辅助方法
    # ========================================================================

    @staticmethod
    def _extract_node_outputs(traces: list[dict]) -> dict[str, dict]:
        """从工作流执行 traces 提取各节点输出。

        Args:
            traces: run_workflow 返回的 traces 列表

        Returns:
            {node_id: output_dict}
        """
        outputs: dict[str, dict] = {}
        for trace in traces:
            node_id = trace.get("node_id")
            output = trace.get("output")
            if node_id and output is not None:
                outputs[node_id] = output if isinstance(output, dict) else {"value": output}
        return outputs

    @staticmethod
    def _find_interrupt_node(traces: list[dict]) -> Optional[str]:
        """从 traces 中找到中断节点（human_review 节点）。"""
        for trace in traces:
            node_type = trace.get("node_type", "")
            status = trace.get("status", "")
            if node_type == "human_review" or status == "waiting_for_approval":
                return trace.get("node_id")
        return None

    def get_active_skill(self, skill_run_id: str) -> Optional[SkillContext]:
        """获取活跃技能上下文。"""
        return self._active_skills.get(skill_run_id)
