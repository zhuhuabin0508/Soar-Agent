"""Hermes 引擎核心数据结构。

定义工具调用、工具结果、技能上下文、SSE 事件、迭代预算等数据类。
所有数据类均为 dataclass，不可变字段用 frozen=True。
"""
from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from datetime import datetime
from app.core.timezone import beijing_now, beijing_now_iso
from typing import Any, Callable, Optional


# ============================================================================
# 工具调用相关
# ============================================================================


@dataclass
class ToolCall:
    """单次工具调用请求（来自 LLM 的 tool_calls 数组中的一项）。

    original_index 保证结果按 LLM emission 顺序回填，即使并行执行乱序完成。
    """

    original_index: int  # 在原始 batch 中的位置，保证结果顺序
    id: str  # tool_call_id（OpenAI 兼容）
    name: str
    arguments: dict  # 已解析的参数（解析失败为 {}，并标记 malformed=True）
    malformed: bool = False
    raw_arguments: str = ""  # 原始 JSON 字符串（用于日志/调试）


@dataclass
class ToolResult:
    """单次工具执行结果。

    content 已经过不可信包装 + 威胁扫描 + 预算持久化处理。
    persisted=True 时，content 为 preview，完整结果在 full_result_ref。
    """

    tool_call_id: str
    name: str
    content: Any  # 已经过不可信包装
    is_error: bool = False
    duration_ms: int = 0
    # 预算持久化相关（TIER 1 功能 3）
    persisted: bool = False
    preview: str = ""
    full_result_ref: str = ""  # Execution.variables 中的 key
    # 威胁扫描结果（TIER 1 功能 2）
    threat_findings: list[str] = field(default_factory=list)
    # 守卫决策（TIER 1 功能 1）
    guardrail_action: str = "allow"  # allow | warn | block | halt
    # 工具生成的输出文件（如 expand_risk_detail 的展开表）：{file_id, file_name, rows, columns}；
    # 由 executor 在 tool_end 事件后追加推送 file 事件，供前端消息气泡渲染下载卡片
    generated_file: Optional[dict] = None


@dataclass
class ToolEntry:
    """工具注册表条目。

    source 标识工具来源，决定并行安全性与不可信包装策略：
    - "db_code" / "db_http": 来自 DB 的 code/http 工具
    - "kb": 知识库工具（search_knowledge_base / query_kb_file）
    - "openapi_dynamic": 本次会话动态注册的 OpenAPI 工具
    - "workflow": 工作流包装工具（trigger_workflow_skill）
    - "builtin": 内置工具（check_whitelist 等）
    - "memory": 记忆工具（memory_search / memory_write）
    - "delegate": 委派工具（delegate_task）
    - "persisted": 持久化结果查询工具（query_persisted_result）
    """

    name: str
    description: str
    args_schema: Any  # pydantic BaseModel 类
    coroutine: Callable  # async (**kwargs) -> Any
    source: str = "builtin"
    parallel_safe: bool = False  # 见 tool_dispatch 分类
    untrusted: bool = False  # 结果是否需要不可信包装


# ============================================================================
# 技能（工作流桥接）相关
# ============================================================================


@dataclass
class SkillContext:
    """技能运行上下文（工作流桥接）。

    一个 SkillContext 对应一次工作流技能触发，可中断/恢复。
    """

    skill_run_id: str  # UUID
    workflow_id: int
    execution_id: int  # Soar Execution.id
    payload: dict
    node_outputs: dict[str, dict]  # node_id -> output dict（与 workflow_runner.ctx 同构）
    status: str = "running"  # "running" | "interrupted" | "completed" | "failed"
    interrupt_node_id: Optional[str] = None  # human_review 节点 id
    pending_approval: Optional[dict] = None  # 审批工单信息
    started_at: datetime = field(default_factory=beijing_now)
    finished_at: Optional[datetime] = None


# ============================================================================
# SSE 事件
# ============================================================================


@dataclass
class SSEEvent:
    """SSE 事件数据类。

    type 取值（现有契约的超集，前端兼容）：
    - start: 会话开始
    - status: 状态更新（如「正在调用工具...」）
    - token: LLM 流式 token
    - tool_start: 工具开始执行
    - tool_end: 工具执行结束
    - skill_interrupt: 技能被中断（含 execution_id）
    - delegate: 子代理事件（含嵌套事件）
    - log: 日志（含 level/message）
    - done: 会话结束（含最终回复）
    - error: 错误
    """

    type: str
    content: str = ""
    message: str = ""
    tool_name: str = ""
    tool_call_id: str = ""
    result: Any = None
    log: Optional[dict] = None
    skill: Optional[dict] = None


# ============================================================================
# 迭代预算
# ============================================================================


class IterationBudget:
    """线程安全迭代计数器（移植自 Hermes iteration_budget.py）。

    用于限制 ReAct 循环最大迭代次数，防止死循环。
    单实例无需跨进程共享（每个 HermesAgentExecutor 独立预算）。
    """

    def __init__(self, max_total: int):
        self._max = max_total
        self._used = 0
        self._lock = threading.Lock()

    def consume(self) -> bool:
        """消耗一次迭代。返回 True 表示还有预算，False 表示已耗尽。"""
        with self._lock:
            if self._used >= self._max:
                return False
            self._used += 1
            return True

    def refund(self) -> None:
        """退还一次迭代（用于工具被 guardrail block 时不计入）。"""
        with self._lock:
            if self._used > 0:
                self._used -= 1

    @property
    def used(self) -> int:
        with self._lock:
            return self._used

    @property
    def remaining(self) -> int:
        with self._lock:
            return max(0, self._max - self._used)

    @property
    def max_total(self) -> int:
        return self._max


# ============================================================================
# 异步事件工具
# ============================================================================


class AsyncInterruptEvent:
    """异步中断信号包装器。

    用于工具执行过程中接收外部中断信号（如用户停止）。
    """

    def __init__(self):
        self._event = asyncio.Event()

    def set(self) -> None:
        self._event.set()

    def is_set(self) -> bool:
        return self._event.is_set()

    async def wait(self, timeout: Optional[float] = None) -> bool:
        """等待中断信号。返回 True 表示已中断。"""
        try:
            if timeout is None:
                await self._event.wait()
                return True
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False
