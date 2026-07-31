"""API v1 路由聚合。

所有业务路由统一前缀 ``/api/v1``，在此处聚合注册。
新增模块的 router 在此 include 即可。
"""
import logging

from fastapi import APIRouter

from app.api.v1 import (
    agents,
    agent_files,
    approvals,
    assets,
    auth,
    backup,
    banned_ips,
    dashboard,
    devices,
    executions,
    knowledge_base,
    llm_config,
    notifications,
    roles,
    skills,
    system_config,
    system_monitor,
    tools,
    tools_manage,
    users,
    webhook,
    workflows,
    workflow_versions,
)

logger = logging.getLogger(__name__)

api_router = APIRouter()

# 认证（登录/当前用户/改密）
api_router.include_router(auth.router)
# 工作流与执行
api_router.include_router(workflows.router)
api_router.include_router(workflow_versions.router)
api_router.include_router(webhook.router)
api_router.include_router(executions.router)
# 审批与大屏
api_router.include_router(approvals.router)
api_router.include_router(dashboard.router)
# 工具能力（IP 综合查询 / 封禁）
api_router.include_router(tools.router)
# 工具管理（可编辑 Python 工具）
api_router.include_router(tools_manage.router)
# LLM 配置
api_router.include_router(llm_config.router)
# 安全设备与设备动作管理
api_router.include_router(devices.router)
# 智能体
api_router.include_router(agents.router)
# 知识库
api_router.include_router(knowledge_base.router)
# 智能体文件（不做 RAG，原样存储供 read_document 工具读取）
api_router.include_router(agent_files.router)
# 技能（纯文本指令，注入 Agent system prompt）
api_router.include_router(skills.router)
# 用户与角色管理
api_router.include_router(users.router)
api_router.include_router(roles.router)
# 系统配置
api_router.include_router(system_config.router)
# 系统监控（健康检查/性能指标/审计日志）
api_router.include_router(system_monitor.router)
# 通知中心
api_router.include_router(notifications.router)
# 数据备份与恢复
api_router.include_router(backup.router)
# 已封禁 IP 管理
api_router.include_router(banned_ips.router)
# 资产管理
api_router.include_router(assets.router)


@api_router.get("/health", tags=["health"])
def health_check() -> dict:
    """健康检查端点。"""
    logger.info("Health check called")
    return {"status": "ok"}
