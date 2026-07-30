"""权限矩阵定义。

按模块划分权限，每个模块包含若干动作（view/edit/delete/execute 等）。
角色通过 permissions JSON 字段存储 ``{模块: [动作列表]}`` 结构。

用于 ``require_permission(module, action)`` 依赖校验。
"""
from typing import Any

# 权限模块与可用动作
# 新增模块时在此注册，前端角色管理页面会动态读取
PERMISSION_MODULES: dict[str, list[str]] = {
    "workflow": ["view", "edit", "delete", "execute"],
    "tool": ["view", "edit", "delete", "execute"],
    "agent": ["view", "edit", "delete", "execute"],
    "knowledge_base": ["view", "edit", "delete"],
    "skill": ["view", "edit", "delete"],
    "llm_config": ["view", "edit", "delete"],
    "dashboard": ["view"],
    "approval": ["view", "approve"],
    "execution": ["view"],
    "user": ["view", "edit", "delete"],
    "role": ["view", "edit", "delete"],
    "system_config": ["view", "edit"],
    "audit_log": ["view"],
    "system_monitor": ["view"],
    "notification": ["view", "edit"],
}

# 模块中文标签（前端展示用）
MODULE_LABELS: dict[str, str] = {
    "workflow": "工作流",
    "tool": "工具",
    "agent": "智能体",
    "knowledge_base": "知识库",
    "skill": "技能",
    "llm_config": "模型配置",
    "dashboard": "运营大屏",
    "approval": "工作台/审批",
    "execution": "执行追溯",
    "user": "用户管理",
    "role": "角色管理",
    "system_config": "系统设置",
    "audit_log": "审计日志",
    "system_monitor": "系统监控",
    "notification": "通知中心",
}

# 动作中文标签
ACTION_LABELS: dict[str, str] = {
    "view": "查看",
    "edit": "编辑",
    "delete": "删除",
    "execute": "执行",
    "approve": "审批",
}

# 默认角色权限（种子数据用）
DEFAULT_ROLES: list[dict[str, Any]] = [
    {
        "name": "admin",
        "description": "超级管理员，拥有所有权限",
        "is_system": True,
        "permissions": {mod: list(actions) for mod, actions in PERMISSION_MODULES.items()},
    },
    {
        "name": "analyst",
        "description": "安全运营人员，可编辑工作流/智能体/知识库、处理审批",
        "is_system": True,
        "permissions": {
            "workflow": ["view", "edit", "delete", "execute"],
            "tool": ["view", "execute"],
            "agent": ["view", "edit", "execute"],
            "knowledge_base": ["view", "edit"],
            "skill": ["view", "edit"],
            "llm_config": ["view"],
            "dashboard": ["view"],
            "approval": ["view", "approve"],
            "execution": ["view"],
        },
    },
    {
        "name": "viewer",
        "description": "只读用户，仅可查看",
        "is_system": True,
        "permissions": {
            "workflow": ["view"],
            "tool": ["view"],
            "agent": ["view"],
            "knowledge_base": ["view"],
            "skill": ["view"],
            "llm_config": ["view"],
            "dashboard": ["view"],
            "approval": ["view"],
            "execution": ["view"],
        },
    },
]


def has_permission(permissions: dict[str, list[str]] | None, module: str, action: str) -> bool:
    """检查权限矩阵是否包含指定模块的动作。

    Args:
        permissions: 角色的 permissions 字典 ``{模块: [动作]}``
        module: 权限模块名
        action: 动作名

    Returns:
        是否有权限
    """
    if not permissions:
        return False
    actions = permissions.get(module, [])
    return action in actions
