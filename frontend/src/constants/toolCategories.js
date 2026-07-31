// 工具分类元数据：供 ToolList 和 AgentEditor 共用
// category 值 → 中文标签 + 图标 + 描述
export const CATEGORY_META = {
  file_operations: { label: '文件操作', icon: '📁', desc: '读取 Excel / Word / PDF / CSV 等上传文件' },
  security: { label: '安全运营', icon: '🛡️', desc: 'IP 查询、威胁情报、资产归属等 SOAR 安全工具' },
  asset: { label: '资产管理', icon: '📋', desc: '资产梳理、录入、查询、更新等资产管理工具' },
  cron_jobs: { label: '定时任务', icon: '⏰', desc: '按 Cron 表达式周期性触发工作流' },
  memory: { label: '记忆', icon: '🧠', desc: '智能体长期记忆的存取' },
  computer_use: { label: '计算机操作', icon: '💻', desc: '命令执行、文件系统、浏览器等操作系统交互' },
  clarifying_question: { label: '澄清提问', icon: '❓', desc: '向用户提问以澄清需求或获取决策' },
  task_planning: { label: '任务规划', icon: '📋', desc: '将复杂任务分解为有序步骤' },
  task_delegation: { label: '任务委派', icon: '📤', desc: '委派子代理或触发工作流技能' },
}

export const UNCATEGORIZED = { label: '其他', icon: '📦', desc: '未分类工具' }

/**
 * 将工具列表按 category 分组
 * @param {Array} tools - 工具列表，每项需有 category 字段
 * @returns {Array<{category: string, meta: object, tools: Array}>} 分组后的数组
 */
export function groupToolsByCategory(tools) {
  const groups = {}
  for (const t of tools) {
    const cat = t.category || '_uncategorized'
    if (!groups[cat]) groups[cat] = []
    groups[cat].push(t)
  }
  // 按 CATEGORY_META 的定义顺序排列，未分类放最后
  const orderedCats = [...Object.keys(CATEGORY_META), '_uncategorized']
  return orderedCats
    .filter((c) => groups[c]?.length > 0)
    .map((c) => ({
      category: c,
      meta: c === '_uncategorized' ? UNCATEGORIZED : (CATEGORY_META[c] || UNCATEGORIZED),
      tools: groups[c],
    }))
}
