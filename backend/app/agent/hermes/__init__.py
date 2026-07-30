"""Hermes 风格智能体引擎包。

对标 Hermes Agent 架构，提供：
- 工具引擎（分段并行调度 + JSON 容错 + 不可信结果包装）
- 技能引擎（工作流桥接 + 中断/恢复 + 变量传递）
- ReAct 执行器（迭代预算 + SSE 流式 + 响应拦截）
- 上下文压缩（token 阈值 + 滑动窗口 + LLM 摘要）
- 多用户记忆（PostgreSQL 全文检索 + provider 抽象 + curator）
- 子代理委派（ContextVar 深度限制 + 事件转发）

额外功能（TIER 1+2）：
- 工具循环守卫（guardrails）
- 威胁模式扫描器（threat_scanner）
- 工具结果预算（budget + 大结果持久化）
- 中间件系统（middleware + 审计/脱敏/限流）
- 工具搜索（渐进式工具披露）
- 委派实时日志

设计原则：
- 对 ``engine=langgraph``（默认）的 Agent 零侵入
- 所有对 ``app.agent.decision`` / ``app.core.*`` 的引用用延迟导入避免循环依赖
- 多用户隔离：所有记忆/中间件按 (user_id, agent_id) 分区
"""

# 延迟导出，避免 import 时拉起整个依赖链
# HermesAgentExecutor 和 sse_stream 在需要时从 executor / sse 模块导入

__all__ = [
    "HermesAgentExecutor",
    "sse_stream",
]


def __getattr__(name: str):
    """PEP 562 模块级 __getattr__：延迟导入避免循环依赖。"""
    if name == "HermesAgentExecutor":
        from app.agent.hermes.executor import HermesAgentExecutor
        return HermesAgentExecutor
    if name == "sse_stream":
        from app.agent.hermes.sse import sse_stream
        return sse_stream
    raise AttributeError(f"module 'app.agent.hermes' has no attribute {name!r}")
