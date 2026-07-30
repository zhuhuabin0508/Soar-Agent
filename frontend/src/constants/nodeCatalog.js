// 节点目录：定义 6 种可拖拽节点
// 每种节点含：type / label / icon / color / defaultData / description
// color 使用十六进制色值，便于在自定义节点与卡片中以 inline style 应用，
// 避免 Tailwind 动态类名被 purge 的问题。

export const nodeCatalog = [
  {
    type: 'webhook_trigger',
    label: 'Webhook 触发器',
    icon: '🪝',
    color: '#f59e0b', // 琥珀色
    description: '通过 Webhook 接收外部事件触发工作流',
    defaultData: {
      label: '', // 用户自定义节点名称（空则显示 def.label）
      description: '', // 用户自定义节点描述
      method: 'POST',
      content_type: 'application/json',
      query_params: [], // [{ name, type, required }]
      header_params: [], // [{ key, required }]
      body_params: [], // [{ name, type, required }]
      response_status: 200,
      response_body: '{"status": "received"}',
    },
  },
  {
    type: 'condition_branch',
    label: '条件分支',
    icon: '🔀',
    color: '#a855f7', // 紫色
    description: '根据条件表达式进行分支流转',
    defaultData: {
      label: '',
      description: '',
      mode: 'if_else', // 'if_else' | 'switch'
      logic: 'AND', // 条件连接符 AND | OR
      conditions: [], // [{ variable, operator, value }]
      true_label: '是',
      false_label: '否',
      cases: [], // [{ label, logic, conditions }] 用于 switch
    },
  },
  {
    type: 'http_request',
    label: 'HTTP 请求',
    icon: '🌐',
    color: '#3b82f6', // 蓝色
    description: '向外部服务发起 HTTP 调用',
    defaultData: {
      label: '',
      description: '',
      method: 'GET',
      url: '',
      auth_type: 'none', // none | basic | api_key | bearer
      auth: {
        username: '',
        password: '',
        key_name: '',
        key_value: '',
        token: '',
      },
      headers: [], // [{ key, value }]
      query_params: [], // [{ key, value }]
      body_type: 'none', // none | json | form | urlencoded | raw
      body_content: '', // json / raw 文本
      body_form: [], // [{ key, value }] form / urlencoded
      timeout: 30,
      retry: 0,
      response_format: 'json', // json | text | base64
    },
  },
  {
    type: 'ai_agent',
    label: 'AI 智能体',
    icon: '🤖',
    color: '#22c55e', // 绿色
    description: '选择「智能体管理」中已创建的智能体进行调用，复用其模型/提示词/工具/知识库配置',
    defaultData: {
      label: '',
      description: '',
      agent_id: null, // 关联已创建的 Agent.id（复用其完整配置）
      user_prompt: '', // 输入提示词，支持 ${node_id.field} 引用上游节点输出
      output_variables: [], // [{ name, description }] 自定义输出变量声明
    },
  },
  {
    type: 'llm',
    label: 'LLM',
    icon: '💭',
    color: '#8b5cf6', // 紫罗兰色（区别于 ai_agent 的绿色，强调纯文本生成）
    description: '调用大模型生成文本（不带工具循环），适用于摘要/翻译/分类/信息抽取',
    defaultData: {
      label: '',
      description: '',
      model_config_id: null, // 关联 DB 中的 LLMConfig，留空则用默认配置
      model: '', // 模型名（留空则用 LLMConfig 中的 model_name）
      system_prompt: '', // 系统提示词（支持 ${node.field} 变量引用）
      user_prompt: '', // 用户提示词（支持 ${node.field} 变量引用）
      temperature: 0.7,
      max_tokens: 1024,
    },
  },
  {
    type: 'block_ip',
    label: '下发封禁指令',
    icon: '🚫',
    color: '#ef4444', // 红色
    description: '向安全设备下发 IP 封禁指令（旧版内置 mock）',
    defaultData: {
      label: '',
      description: '',
      action: 'block', // block | unblock
      target_ip: '{{alert_data.src_ip}}',
      duration_value: 24,
      duration_unit: '小时', // 分钟 | 小时 | 天
      reason: '',
      device: 'firewall-A', // firewall-A | firewall-B | ids
      priority: '高', // 低 | 中 | 高 | 紧急
      notify_on_success: true,
      remark: '',
    },
  },
  {
    type: 'device_action',
    label: '设备动作',
    icon: '🛡️',
    color: '#0ea5e9', // 天蓝色（区别于 block_ip 的红色，强调通用设备对接）
    description: '选择「设备对接」中已配置的设备与动作，向真实安全设备下发处置指令',
    defaultData: {
      label: '',
      description: '',
      device_id: null, // 关联 Device.id
      action_id: null, // 关联 DeviceAction.id
      params: {}, // 动作参数（键值对，值支持 ${node.field} 变量引用）
    },
  },
  {
    type: 'send_notification',
    label: '发送通知',
    icon: '📢',
    color: '#06b6d4', // 青色
    description: '通过邮件 / Webhook / IM 发送告警通知',
    defaultData: {
      label: '',
      description: '',
      channel: 'email', // email | webhook | im | sms
      severity: 'warning', // info | warning | error | critical
      // —— 邮件 SMTP 配置（QQ 邮箱示例：smtp.qq.com / 465 / SSL / 授权码）——
      smtp_host: 'smtp.qq.com',
      smtp_port: 465,
      use_ssl: true, // 465 用 SSL；587 用 STARTTLS（此处设 false）
      smtp_username: '', // 发件邮箱，如 xxx@qq.com
      smtp_password: '', // QQ 邮箱填授权码（非登录密码）
      from_email: '', // 留空则用 smtp_username
      charset: 'utf-8',
      // —— 收件人 ——
      recipients: '',
      cc: '',
      // —— 通知内容（支持 {{节点.字段}} 变量引用）——
      subject: '',
      body: '',
      // —— Webhook 渠道 ——
      webhook_url: '',
      attachments: '',
    },
  },
  {
    type: 'tool',
    label: '工具调用',
    icon: '🛠️',
    color: '#14b8a6', // 青绿色
    description: '调用已注册的自定义工具',
    defaultData: {
      label: '',
      description: '',
      tool_name: '',
      parameters: {},
    },
  },
  {
    type: 'human_review',
    label: '人工介入',
    icon: '👤',
    color: '#f97316', // 橙色
    description: '工作流走到此节点时生成工单，由工作人员判断是否封禁',
    defaultData: {
      label: '',
      description: '',
      title: '人工审批工单',
      instructions:
        '请基于以下告警信息与 Agent 推理结果，判断是否需要封禁源 IP。点击「同意封禁」将继续执行下游封禁节点；点击「忽略」将终止工作流。',
    },
  },
  {
    type: 'code_execute',
    label: '代码执行',
    icon: '🐍',
    color: '#10b981', // 翠绿色
    description: '执行自定义 Python3 代码，支持变量引用与结果输出',
    defaultData: {
      label: '',
      description: '',
      // 代码中可用：input_data（上游输入）、ctx（工作流上下文）
      // 将结果赋值给 result 变量即为节点输出
      code: '# 可用变量：input_data（上游输入）、ctx（工作流上下文）\n# 将结果赋值给 result 变量作为节点输出\nresult = {"echo": input_data}\n',
    },
  },
  {
    type: 'loop',
    label: '循环',
    icon: '🔁',
    color: '#8b5cf6', // 紫罗兰色
    description: '按次数或条件循环执行子流程',
    defaultData: {
      label: '',
      description: '',
      loop_mode: 'count', // count（固定次数）| while（条件循环）
      count: 3, // count 模式的循环次数
      loop_condition: '', // while 模式的条件表达式，如 ctx.get("should_continue")
      max_iterations: 100, // while 模式的最大循环次数（防死循环）
    },
  },
  {
    type: 'iteration',
    label: '迭代',
    icon: '🔄',
    color: '#06b6d4', // 青色
    description: '遍历数组/列表，对每个元素执行子流程',
    defaultData: {
      label: '',
      description: '',
      data_source: 'input', // input（上游输入）| ctx（上下文变量）| custom（自定义JSON）
      ctx_var: '', // data_source=ctx 时引用的变量路径，如 agent_decision.messages
      custom_data: '', // data_source=custom 时的 JSON 数组字符串
    },
  },
  {
    type: 'end',
    label: '结束',
    icon: '⏹️',
    color: '#6b7280', // 灰色
    description: '工作流结束节点，标识流程终止',
    defaultData: {
      label: '',
      description: '',
      end_type: 'success', // success | failed | cancelled
      remark: '',
    },
  },
]

// 根据 type 获取节点定义
export function getNodeDefinition(type) {
  return nodeCatalog.find((n) => n.type === type)
}
