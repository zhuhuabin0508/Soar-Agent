/** 工作流创建模板（借鉴 Shuffle/n8n 模板库：新建先选模板，不直接进空白画布） */

export const WORKFLOW_TEMPLATE_STORAGE_KEY = 'soar:workflow:template'

export const WORKFLOW_TEMPLATES = [
  {
    key: 'alert_auto_remediation',
    name: '告警自动处置流程',
    description: 'Webhook 接收告警 → 条件判断 → IP 封禁 → 通知',
    scenario: '告警处置',
    tags: ['Webhook', '封禁', '通知'],
    template: {
      name: '告警自动处置流程',
      graph_config: {
        nodes: [
          { id: 'n_alert', type: 'webhook_trigger', position: { x: 80, y: 80 }, data: { label: '接收告警', method: 'POST', body_params: [{ name: 'src_ip', type: 'String', required: true }, { name: 'alert_type', type: 'String', required: true }] } },
          { id: 'n_branch', type: 'condition_branch', position: { x: 400, y: 80 }, data: { label: '高危判断', mode: 'if_else', logic: 'AND', conditions: [{ variable: '${n_alert.payload.alert_type}', operator: 'contains', value: 'brute_force' }] } },
          { id: 'n_block', type: 'block_ip', position: { x: 720, y: 40 }, data: { label: '封禁源 IP', ip: '${n_alert.payload.src_ip}', duration: 3600 } },
          { id: 'n_notify', type: 'send_notification', position: { x: 720, y: 200 }, data: { label: '发送通知', channel: 'email', title: '告警处置完成', content: '已封禁 IP: ${n_alert.payload.src_ip}' } },
        ],
        edges: [
          { id: 'e1', source: 'n_alert', target: 'n_branch', animated: true },
          { id: 'e2', source: 'n_branch', target: 'n_block', label: '是', animated: true },
          { id: 'e3', source: 'n_block', target: 'n_notify', animated: true },
        ],
        variables: [],
      },
    },
  },
  {
    key: 'asset_inspection',
    name: '资产巡检流程',
    description: '定时触发 → 设备动作采集 → AI 分析 → 生成报告',
    scenario: '资产运营',
    tags: ['定时', 'AI 分析'],
    template: {
      name: '资产巡检流程',
      graph_config: {
        nodes: [
          { id: 'n_cron', type: 'schedule_trigger', position: { x: 80, y: 80 }, data: { label: '每日巡检', cron: '0 9 * * *', timezone: 'Asia/Shanghai' } },
          { id: 'n_device', type: 'device_action', position: { x: 400, y: 80 }, data: { label: '采集资产状态', device_id: null, action: 'get_status', parameters: {} } },
          { id: 'n_ai', type: 'ai_agent', position: { x: 720, y: 80 }, data: { label: 'AI 风险分析', agent_id: null, user_prompt: '分析以下资产状态并识别风险: ${n_device.output}', output_variables: [{ name: 'risk_report', description: '风险分析报告' }] } },
          { id: 'n_notify', type: 'send_notification', position: { x: 1040, y: 80 }, data: { label: '推送报告', channel: 'email', title: '资产巡检报告', content: '${n_ai.risk_report}' } },
        ],
        edges: [
          { id: 'e1', source: 'n_cron', target: 'n_device', animated: true },
          { id: 'e2', source: 'n_device', target: 'n_ai', animated: true },
          { id: 'e3', source: 'n_ai', target: 'n_notify', animated: true },
        ],
        variables: [],
      },
    },
  },
  {
    key: 'notification_push',
    name: '通知推送流程',
    description: '手动触发 → 多渠道通知',
    scenario: '运营通知',
    tags: ['手动', '通知'],
    template: {
      name: '通知推送流程',
      graph_config: {
        nodes: [
          { id: 'n_manual', type: 'manual_trigger', position: { x: 80, y: 80 }, data: { label: '手动触发', entry_form: [{ name: 'message', type: 'String', required: true }] } },
          { id: 'n_email', type: 'send_notification', position: { x: 400, y: 40 }, data: { label: '邮件通知', channel: 'email', title: '系统通知', content: '${n_manual.payload.message}' } },
          { id: 'n_webhook', type: 'http_request', position: { x: 400, y: 200 }, data: { label: 'Webhook 推送', method: 'POST', url: 'https://example.com/notify', body: '{"message": "${n_manual.payload.message}"}' } },
        ],
        edges: [
          { id: 'e1', source: 'n_manual', target: 'n_email', animated: true },
          { id: 'e2', source: 'n_manual', target: 'n_webhook', animated: true },
        ],
        variables: [],
      },
    },
  },
]

export function stashWorkflowTemplate(key) {
  try {
    sessionStorage.setItem(WORKFLOW_TEMPLATE_STORAGE_KEY, key)
  } catch {
    /* ignore */
  }
}

export function loadStashedWorkflowTemplate() {
  try {
    const key = sessionStorage.getItem(WORKFLOW_TEMPLATE_STORAGE_KEY)
    if (!key) return null
    sessionStorage.removeItem(WORKFLOW_TEMPLATE_STORAGE_KEY)
    return WORKFLOW_TEMPLATES.find((t) => t.key === key) || null
  } catch {
    return null
  }
}

/** 规则化骨架：自然语言 → 最小可编辑工作流（V2.4 PoC，借鉴 n8n AI Builder 的「先出稿」） */
export function generateWorkflowSkeletonFromText(text) {
  const t = (text || '').toLowerCase()
  const hasBan = /封禁|block|ban/.test(t)
  const hasNotify = /通知|邮件|值班|alert/.test(t)
  const hasWebhook = /告警|webhook|入库/.test(t)
  const name = text.slice(0, 40) || 'AI 生成工作流草稿'
  const nodes = []
  const edges = []
  let lastId = null
  const add = (id, type, label, data = {}) => {
    nodes.push({ id, type, position: { x: 80 + nodes.length * 280, y: 80 }, data: { label, ...data } })
    if (lastId) edges.push({ id: `e_${lastId}_${id}`, source: lastId, target: id, animated: true })
    lastId = id
  }
  if (hasWebhook || !lastId) {
    add('n_webhook', 'webhook_trigger', '接收告警', {
      method: 'POST',
      body_params: [{ name: 'src_ip', type: 'String', required: true }, { name: 'alert_type', type: 'String', required: true }],
    })
  }
  add('n_agent', 'ai_agent', 'AI 研判', {
    agent_id: null,
    user_prompt: '请根据告警研判源 IP：{{payload.src_ip}}',
  })
  if (hasBan) {
    add('n_block', 'block_ip', '封禁 IP', { ip: '{{payload.src_ip}}', duration: 86400 })
  }
  if (hasNotify) {
    add('n_notify', 'send_notification', '发送通知', { channel: 'email', title: '处置完成', content: '工作流已执行' })
  }
  return { name, graph_config: { nodes, edges, variables: [] } }
}
