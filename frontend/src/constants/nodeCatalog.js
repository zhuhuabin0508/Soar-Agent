// 节点目录：定义可拖拽节点
// 每种节点含：type / label / icon / color / defaultData / description / category
// color 使用十六进制色值，便于在自定义节点与卡片中以 inline style 应用，
// 避免 Tailwind 动态类名被 purge 的问题。
// icon 字段为 lucide-react 图标组件名（字符串），由渲染端通过 ICON_MAP 映射为组件。
// category 用于节点库分组折叠：trigger / logic / ai / device / notification / data / human / annotation

export const NODE_CATEGORIES = [
  { key: 'trigger', label: '触发器', icon: 'Zap', expanded: true },
  { key: 'logic', label: '逻辑控制', icon: 'GitBranch', expanded: true },
  { key: 'ai', label: 'AI 能力', icon: 'Bot', expanded: true },
  { key: 'device', label: '设备动作', icon: 'Shield', expanded: true },
  { key: 'notification', label: '通知', icon: 'Bell', expanded: true },
  { key: 'data', label: '数据处理', icon: 'Database', expanded: true },
  { key: 'human', label: '人工', icon: 'UserCheck', expanded: true },
  { key: 'annotation', label: '注释与分组', icon: 'StickyNote', expanded: false },
]

export const nodeCatalog = [
  {
    type: 'webhook_trigger',
    label: 'Webhook 触发器',
    icon: 'Webhook',
    color: '#f59e0b',
    category: 'trigger',
    description: '通过 Webhook 接收外部事件触发工作流',
    defaultData: {
      label: '',
      description: '',
      method: 'POST',
      content_type: 'application/json',
      query_params: [],
      header_params: [],
      body_params: [],
      response_status: 200,
      response_body: '{"status": "received"}',
      // Webhook 配置增强：签名验证 / 测试 / 重试
      secret_verify: false, // 是否启用签名验证
      secret_algorithm: 'HMAC-SHA256', // 签名算法
      secret_header: 'X-Webhook-Signature', // 签名头名称
      secret_value: '', // 签名密钥（用于校验）
      retry_max: 0, // 失败重试次数
      retry_interval: 5, // 重试间隔（秒）
      sample_payload: '', // 请求示例 Payload
    },
  },
  {
    type: 'schedule_trigger',
    label: '定时触发',
    icon: 'Clock',
    color: '#f97316',
    category: 'trigger',
    description: '按 Cron 表达式定时触发工作流',
    defaultData: {
      label: '',
      description: '',
      cron: '0 * * * *', // 每小时执行
      timezone: 'Asia/Shanghai',
    },
  },
  {
    type: 'event_trigger',
    label: '事件触发',
    icon: 'Radio',
    color: '#eab308',
    category: 'trigger',
    description: '监听系统事件（如告警、资产变更）触发工作流',
    defaultData: {
      label: '',
      description: '',
      event_source: 'alert', // alert / asset / system
      event_type: '*', // 事件类型过滤
    },
  },
  {
    type: 'manual_trigger',
    label: '手动触发',
    icon: 'Hand',
    color: '#84cc16',
    category: 'trigger',
    description: '人工点击「执行」按钮触发工作流',
    defaultData: {
      label: '',
      description: '',
      entry_form: [], // 启动时需填写的表单 [{ name, type, required, default }]
    },
  },
  {
    type: 'condition_branch',
    label: '条件分支',
    icon: 'Shuffle',
    color: '#a855f7',
    category: 'logic',
    description: '根据条件表达式进行分支流转',
    defaultData: {
      label: '',
      description: '',
      mode: 'if_else',
      logic: 'AND',
      conditions: [],
      true_label: '是',
      false_label: '否',
      cases: [],
    },
  },
  {
    type: 'loop',
    label: '循环',
    icon: 'Repeat',
    color: '#8b5cf6',
    category: 'logic',
    description: '按次数或条件循环执行子流程',
    defaultData: {
      label: '',
      description: '',
      loop_mode: 'count',
      count: 3,
      loop_condition: '',
      max_iterations: 100,
    },
  },
  {
    type: 'iteration',
    label: '迭代',
    icon: 'RefreshCw',
    color: '#06b6d4',
    category: 'logic',
    description: '遍历数组/列表，对每个元素执行子流程',
    defaultData: {
      label: '',
      description: '',
      data_source: 'input',
      ctx_var: '',
      custom_data: '',
    },
  },
  {
    type: 'wait',
    label: '等待',
    icon: 'Hourglass',
    color: '#7c3aed',
    category: 'logic',
    description: '工作流暂停一段时间后继续',
    defaultData: {
      label: '',
      description: '',
      wait_mode: 'duration', // duration | until
      duration: 60, // 等待秒数
      until_time: '', // 等待到指定时间
    },
  },
  {
    type: 'parallel',
    label: '并行',
    icon: 'GitMerge',
    color: '#6366f1',
    category: 'logic',
    description: '同时执行多个分支，全部完成后汇聚',
    defaultData: {
      label: '',
      description: '',
      branches: 2, // 并行分支数
      wait_all: true, // 是否等待全部完成（false=任一完成即继续）
    },
  },
  {
    type: 'sub_workflow',
    label: '子流程',
    icon: 'Box',
    color: '#4f46e5',
    category: 'logic',
    description: '调用另一个工作流作为子流程，复用复杂逻辑',
    defaultData: {
      label: '',
      description: '',
      sub_workflow_id: null, // 关联 Workflow.id
      input_mapping: {}, // 输入参数映射
    },
  },
  {
    type: 'ai_agent',
    label: 'AI 智能体',
    icon: 'Bot',
    color: '#22c55e',
    category: 'ai',
    description: '选择「智能体管理」中已创建的智能体进行调用，复用其模型/提示词/工具/知识库配置',
    defaultData: {
      label: '',
      description: '',
      agent_id: null,
      user_prompt: '',
      output_variables: [],
      // 错误处理配置
      timeout: 120,
      retry: 0,
      retry_interval: 5,
      on_failure: 'continue', // continue | stop | branch
      continue_on_error: false,
    },
  },
  {
    type: 'llm',
    label: 'LLM',
    icon: 'MessageSquare',
    color: '#8b5cf6',
    category: 'ai',
    description: '调用大模型生成文本（不带工具循环），适用于摘要/翻译/分类/信息抽取',
    defaultData: {
      label: '',
      description: '',
      model_config_id: null,
      model: '',
      system_prompt: '',
      user_prompt: '',
      temperature: 0.7,
      max_tokens: 1024,
      // 错误处理配置
      timeout: 60,
      retry: 0,
      retry_interval: 5,
      on_failure: 'continue',
      continue_on_error: false,
    },
  },
  {
    type: 'intent_recognition',
    label: '意图识别',
    icon: 'ScanSearch',
    color: '#10b981',
    category: 'ai',
    description: '基于 LLM 识别用户输入意图，路由到对应分支',
    defaultData: {
      label: '',
      description: '',
      intents: [], // [{ name, description }]
      fallback_intent: 'unknown',
    },
  },
  {
    type: 'block_ip',
    label: '下发封禁指令',
    icon: 'Ban',
    color: '#ef4444',
    category: 'device',
    description: '向安全设备下发 IP 封禁指令（旧版内置 mock）',
    defaultData: {
      label: '',
      description: '',
      action: 'block',
      target_ip: '{{alert_data.src_ip}}',
      duration_value: 24,
      duration_unit: '小时',
      reason: '',
      device: 'firewall-A',
      priority: '高',
      notify_on_success: true,
      remark: '',
      // 错误处理配置
      timeout: 30,
      retry: 2,
      retry_interval: 3,
      on_failure: 'continue',
      continue_on_error: false,
    },
  },
  {
    type: 'device_action',
    label: '设备动作',
    icon: 'Shield',
    color: '#0ea5e9',
    category: 'device',
    description: '选择「设备对接」中已配置的设备与动作，向真实安全设备下发处置指令',
    defaultData: {
      label: '',
      description: '',
      device_id: null,
      action_id: null,
      params: {},
      // 错误处理配置
      timeout: 30,
      retry: 2,
      retry_interval: 3,
      on_failure: 'continue',
      continue_on_error: false,
    },
  },
  {
    type: 'send_notification',
    label: '发送通知',
    icon: 'Megaphone',
    color: '#06b6d4',
    category: 'notification',
    description: '通过邮件 / Webhook / IM 发送告警通知',
    defaultData: {
      label: '',
      description: '',
      channel: 'email',
      severity: 'warning',
      smtp_host: 'smtp.qq.com',
      smtp_port: 465,
      use_ssl: true,
      smtp_username: '',
      smtp_password: '',
      from_email: '',
      charset: 'utf-8',
      recipients: '',
      cc: '',
      subject: '',
      body: '',
      webhook_url: '',
      attachments: '',
      // 错误处理配置
      timeout: 30,
      retry: 2,
      retry_interval: 5,
      on_failure: 'continue',
      continue_on_error: false,
    },
  },
  {
    type: 'tool',
    label: '工具调用',
    icon: 'Wrench',
    color: '#14b8a6',
    category: 'data',
    description: '调用已注册的自定义工具',
    defaultData: {
      label: '',
      description: '',
      tool_name: '',
      parameters: {},
      // 错误处理配置
      timeout: 60,
      retry: 0,
      retry_interval: 5,
      on_failure: 'continue',
      continue_on_error: false,
    },
  },
  {
    type: 'http_request',
    label: 'HTTP 请求',
    icon: 'Globe',
    color: '#3b82f6',
    category: 'data',
    description: '向外部服务发起 HTTP 调用',
    defaultData: {
      label: '',
      description: '',
      method: 'GET',
      url: '',
      auth_type: 'none',
      auth: { username: '', password: '', key_name: '', key_value: '', token: '' },
      headers: [],
      query_params: [],
      body_type: 'none',
      body_content: '',
      body_form: [],
      timeout: 30,
      retry: 0,
      response_format: 'json',
      // 错误处理配置
      retry_interval: 5,
      on_failure: 'continue',
      continue_on_error: false,
    },
  },
  {
    type: 'json_parse',
    label: 'JSON 解析',
    icon: 'Braces',
    color: '#0d9488',
    category: 'data',
    description: '解析 JSON 字符串为对象，支持字段提取',
    defaultData: {
      label: '',
      description: '',
      source: '', // 输入 JSON 字符串（支持变量引用）
      extract_fields: [], // [{ path, alias }] 提取字段
    },
  },
  {
    type: 'variable_assign',
    label: '变量赋值',
    icon: 'Variable',
    color: '#0891b2',
    category: 'data',
    description: '设置工作流上下文变量',
    defaultData: {
      label: '',
      description: '',
      assignments: [], // [{ name, value }] 变量赋值列表
    },
  },
  {
    type: 'code_execute',
    label: '代码执行',
    icon: 'Code2',
    color: '#10b981',
    category: 'data',
    description: '执行自定义 Python3 / JavaScript 代码，支持变量引用与结果输出',
    defaultData: {
      label: '',
      description: '',
      language: 'python', // python | javascript
      code: '# 可用变量：input_data（上游输入）、ctx（工作流上下文）\n# 将结果赋值给 result 变量作为节点输出\nresult = {"echo": input_data}\n',
      output_variables: [], // [{ name, description }] 输出变量声明
      // 错误处理配置
      timeout: 60,
      retry: 0,
      retry_interval: 5,
      on_failure: 'continue',
      continue_on_error: false,
    },
  },
  {
    type: 'human_review',
    label: '人工审批',
    icon: 'UserCheck',
    color: '#f97316',
    category: 'human',
    description: '工作流走到此节点时生成工单，由工作人员判断是否继续',
    defaultData: {
      label: '',
      description: '',
      title: '人工审批工单',
      instructions: '请基于以下信息判断是否继续执行工作流。',
      approvers: [], // 审批人列表
      timeout_hours: 24, // 超时时间
      on_timeout: 'approve', // approve | reject | continue
    },
  },
  {
    type: 'ticket_create',
    label: '工单创建',
    icon: 'FileText',
    color: '#ea580c',
    category: 'human',
    description: '向工单系统创建工单，记录事件并分配处理人',
    defaultData: {
      label: '',
      description: '',
      title: '',
      priority: 'normal', // low | normal | high | urgent
      assignee: '',
      description_content: '',
    },
  },
  {
    type: 'annotation',
    label: '注释便签',
    icon: 'StickyNote',
    color: '#fbbf24',
    category: 'annotation',
    description: '在画布上添加说明性注释，不影响流程执行',
    defaultData: {
      label: '',
      description: '',
      content: '在此输入注释内容…',
      color: '#fbbf24', // 便签背景色
    },
  },
  {
    type: 'group',
    label: '分组容器',
    icon: 'SquareStack',
    color: '#94a3b8',
    category: 'annotation',
    description: '框选区域添加背景色和标题（如：告警接收 → 研判）',
    defaultData: {
      label: '',
      description: '',
      group_title: '阶段分组',
      group_color: '#6366f1',
    },
  },
  {
    type: 'end',
    label: '结束',
    icon: 'CircleStop',
    color: '#6b7280',
    category: 'logic',
    description: '工作流结束节点，标识流程终止',
    defaultData: {
      label: '',
      description: '',
      end_type: 'success',
      remark: '',
    },
  },
]

// 根据 type 获取节点定义
export function getNodeDefinition(type) {
  return nodeCatalog.find((n) => n.type === type)
}

// 按 category 分组节点
export function getNodesByCategory() {
  const groups = {}
  nodeCatalog.forEach((n) => {
    const cat = n.category || 'other'
    if (!groups[cat]) groups[cat] = []
    groups[cat].push(n)
  })
  return groups
}
