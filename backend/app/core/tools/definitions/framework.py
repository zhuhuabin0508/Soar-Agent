from typing import Any

HERMES_FRAMEWORK_TOOLS: list[dict[str, Any]] = [
    {
        "name": "trigger_workflow_skill",
        "description": (
            "触发一个已配置的工作流作为复杂技能。适用于需要多步骤编排、"
            "人工审批、设备操作的场景。先调用 list_workflow_skills 获取可用技能。"
        ),
        "parameters_schema": {
            "type": "object",
            "properties": {
                "workflow_id": {"type": "integer", "description": "工作流 ID"},
                "input": {"type": "object", "description": "技能输入参数", "additionalProperties": True},
                "resume_token": {"type": "string", "description": "恢复令牌（恢复被中断的技能时传入）"},
            },
            "required": ["workflow_id"],
        },
        "tool_type": "framework",
        "category": "task_delegation",
        "code": None,
        "enabled": True,
    },
    {
        "name": "list_workflow_skills",
        "description": "列出所有可作为技能触发的工作流（返回 id/name/description）。",
        "parameters_schema": {"type": "object", "properties": {}},
        "tool_type": "framework",
        "category": "task_delegation",
        "code": None,
        "enabled": True,
    },
    {
        "name": "delegate_task",
        "description": (
            "委派一个或多个子代理在隔离上下文中执行任务。"
            "子代理拥有独立的对话历史（看不到父代理历史）、继承的工具集（剥离部分工具）、"
            "独立的迭代预算。"
            "适用于：并行调研多个方向、把重复性子任务交给子代理、保持父上下文简洁。"
            "\n\n单任务：提供 goal（+可选 context）。"
            "批量：提供 tasks 数组 [{goal, context}, ...]（并行执行，汇总结果）。"
            "完成后返回汇总结果，父代理可继续推理。"
            "\n\n注意：子代理看不到你的对话历史，goal 必须 self-contained。"
            "子代理不能委派其他子代理（delegate_task 对子代理不可用）。"
        ),
        "parameters_schema": {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "子代理要完成的目标。必须具体且 self-contained——子代理对你的对话历史一无所知。",
                },
                "context": {
                    "type": "string",
                    "description": "子代理需要的背景信息：文件路径、错误消息、项目结构、约束。越具体，子代理表现越好。",
                },
                "tasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "goal": {"type": "string", "description": "任务目标"},
                            "context": {"type": "string", "description": "任务特定背景"},
                        },
                        "required": ["goal"],
                    },
                    "description": "批量任务数组。提供时忽略顶层 goal/context，每个任务独立执行后汇总。",
                },
            },
            "required": [],
        },
        "tool_type": "framework",
        "category": "task_delegation",
        "code": None,
        "enabled": True,
    },
    {
        "name": "clarify",
        "description": (
            "当你需要澄清、反馈或决策时向用户提问。支持两种模式：\n\n"
            "1. **多选** —— 提供最多 4 个选项，用户选一个或输入'其他'。\n"
            "2. **开放式** —— 不提供选项，用户自由文本回答。\n\n"
            "关键：提供选项时，每个选项只放 ``choices`` 数组，绝不把选项写进 ``question`` 文本。"
            "UI 会渲染 choices 为可选项；写进 question 的选项会变成死文本。\n\n"
            "正确: question='封禁多长时间？', choices=['1小时', '24小时', '永久']\n"
            "错误: question='封禁多长时间？1) 1小时 2) 24小时', choices=[]\n\n"
            "使用场景：\n"
            "- 告警信息不全（IP 为空、设备未指定）\n"
            "- 设备操作目标不明确（多台设备匹配）\n"
            "- 处置策略与告警严重程度不匹配\n"
            "- 决策有重大权衡，需用户参与\n\n"
            "不要用于危险命令的简单 yes/no 确认（写工具的 verification 机制处理）。"
            "低风险决策应自行做合理默认选择。"
        ),
        "parameters_schema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "问题本身，且只有问题（如 '封禁多长时间？'）。不要把答案选项嵌入这里。",
                },
                "choices": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 4,
                    "description": "提供可选项时必填：每个选项是数组的一个元素（最多 4 个）。",
                },
            },
            "required": ["question"],
        },
        "tool_type": "framework",
        "category": "clarifying_question",
        "code": None,
        "enabled": True,
    },
    {
        "name": "plan",
        "description": (
            "创建结构化的任务执行计划。当任务复杂、需要多步骤编排时调用此工具，"
            "将任务分解为有序步骤并明确每步的目标和依赖关系。"
            "计划生成后可作为后续执行的蓝图，也便于用户审阅和调整。"
        ),
        "parameters_schema": {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "任务的最终目标",
                },
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string", "description": "步骤动作描述"},
                            "tool": {"type": "string", "description": "该步骤使用的工具名（可选）"},
                            "depends_on": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "依赖的前置步骤序号",
                            },
                        },
                        "required": ["action"],
                    },
                    "description": "有序步骤列表",
                },
            },
            "required": ["goal", "steps"],
        },
        "tool_type": "framework",
        "category": "task_planning",
        "code": None,
        "enabled": True,
    },
    {
        "name": "schedule_cron",
        "description": (
            "调度一个定时（cron）任务，按指定时间规则周期性执行工作流或动作。"
            "适用于定期巡检、定时报表、周期性扫描等场景。"
        ),
        "parameters_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "定时任务名称"},
                "cron_expr": {
                    "type": "string",
                    "description": "Cron 表达式（如 '0 2 * * *' 表示每天凌晨 2 点）",
                },
                "workflow_id": {"type": "integer", "description": "要触发的工作流 ID"},
                "input": {"type": "object", "description": "传给工作流的输入参数", "additionalProperties": True},
            },
            "required": ["name", "cron_expr", "workflow_id"],
        },
        "tool_type": "framework",
        "category": "cron_jobs",
        "code": None,
        "enabled": True,
    },
    {
        "name": "computer_use",
        "description": (
            "执行计算机操作（如运行命令、操作文件系统、打开浏览器等）。"
            "适用于需要与操作系统或桌面环境交互的自动化场景。"
            "注意：此工具在沙箱中执行，受安全策略限制。"
        ),
        "parameters_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "要执行的操作类型：run_command / read_file / write_file / list_dir / open_url",
                },
                "target": {
                    "type": "string",
                    "description": "操作目标（命令、文件路径、URL 等）",
                },
                "args": {
                    "type": "object",
                    "description": "附加参数",
                    "additionalProperties": True,
                },
            },
            "required": ["action", "target"],
        },
        "tool_type": "framework",
        "category": "computer_use",
        "code": None,
        "enabled": True,
    },
    # ===== 智能体创建助手：构建类框架工具（tool_type='framework'，executor 拦截处理）=====
    # 处理逻辑在 app/agent/hermes/builder.py；仅对显式启用的智能体可见。
    {
        "name": "list_tools",
        "description": "列出平台现有的全部工具（id/name/description/category/tool_type/enabled），用于创建前盘点与命名查重。",
        "parameters_schema": {"type": "object", "properties": {}},
        "tool_type": "framework",
        "category": "agent_builder",
        "code": None,
        "enabled": True,
    },
    {
        "name": "list_skills",
        "description": "列出平台现有的全部技能（id/name/description/category/priority/enabled），用于创建前盘点与命名查重。",
        "parameters_schema": {"type": "object", "properties": {}},
        "tool_type": "framework",
        "category": "agent_builder",
        "code": None,
        "enabled": True,
    },
    {
        "name": "list_agents",
        "description": "列出平台现有的全部智能体（id/name/description/engine/enabled_tools/enabled_skills），用于创建前盘点与命名查重。",
        "parameters_schema": {"type": "object", "properties": {}},
        "tool_type": "framework",
        "category": "agent_builder",
        "code": None,
        "enabled": True,
    },
    {
        "name": "create_skill",
        "description": "创建一个技能（纯文本操作指引，注入智能体 system prompt）。参数：name 唯一、content 必填（Markdown 正文，支持 {{变量}} 占位）、description/category/tags/priority 可选。",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "技能名称，唯一"},
                "description": {"type": "string", "description": "技能简介"},
                "content": {"type": "string", "description": "技能正文（Markdown 操作指引，支持 {{变量}} 占位）"},
                "category": {"type": "string", "description": "技能分类"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "标签列表"},
                "priority": {"type": "integer", "description": "优先级，越大越靠前（默认 0）"},
            },
            "required": ["name", "content"],
        },
        "tool_type": "framework",
        "category": "agent_builder",
        "code": None,
        "enabled": True,
    },
    {
        "name": "create_tool",
        "description": "创建一个代码工具（仅供管理员）。参数：name 唯一（小写英文下划线）、code 必填（Python 代码，须定义 async def run(**kwargs) 返回 dict）、description 必填（写给 LLM 何时调用）、parameters_schema 数组 [{name,type,required,description}]。创建前请先用 test_tool_code 自检代码。",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "工具名，唯一，建议小写英文下划线"},
                "description": {"type": "string", "description": "工具描述（写给 LLM 看，说明何时调用）"},
                "parameters_schema": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "参数 schema 数组：[{name,type,required,description}]，type ∈ String/Integer/Boolean/List/Dict",
                },
                "code": {"type": "string", "description": "Python 代码，必须定义 async def run(**kwargs)，返回 dict"},
                "category": {"type": "string", "description": "工具分类（security/file_operations/asset 等）"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "标签列表"},
            },
            "required": ["name", "description", "parameters_schema", "code"],
        },
        "tool_type": "framework",
        "category": "agent_builder",
        "code": None,
        "enabled": True,
    },
    {
        "name": "create_agent",
        "description": "创建一个智能体。参数：name 必填；description/engine（默认 hermes）/system_prompt/enabled_tools（工具名数组）/enabled_skills（技能 id 数组）/greeting/suggested_questions/max_iterations/temperature 可选。创建前先用 list_tools/list_skills/list_agents 盘点可用的工具与技能。",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "智能体名称，唯一"},
                "description": {"type": "string", "description": "智能体描述"},
                "engine": {"type": "string", "description": "执行引擎：hermes（推荐）| langgraph"},
                "system_prompt": {"type": "string", "description": "系统提示词"},
                "enabled_tools": {"type": "array", "items": {"type": "string"}, "description": "启用的工具名列表"},
                "enabled_skills": {"type": "array", "items": {"type": "integer"}, "description": "启用的技能 id 列表"},
                "greeting": {"type": "string", "description": "开场白"},
                "suggested_questions": {"type": "array", "items": {"type": "string"}, "description": "开场引导问题"},
                "max_iterations": {"type": "integer", "description": "最大迭代轮数（默认 5）"},
                "temperature": {"type": "number", "description": "采样温度（默认 0.7）"},
            },
            "required": ["name"],
        },
        "tool_type": "framework",
        "category": "agent_builder",
        "code": None,
        "enabled": True,
    },
    {
        "name": "test_tool_code",
        "description": "对工具代码做静态安全审查与编译检查（创建工具前的自检）。参数：code 必填。返回 {ok, errors}。若未通过，根据错误信息修改代码后重试。",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "待校验的工具代码"},
            },
            "required": ["code"],
        },
        "tool_type": "framework",
        "category": "agent_builder",
        "code": None,
        "enabled": True,
    },
]
