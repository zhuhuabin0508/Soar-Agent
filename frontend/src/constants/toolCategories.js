// 工具分类元数据：供 ToolList 和 AgentEditor 共用
// category 值 → 中文标签 + lucide 图标名 + 描述
// icon 字段为 lucide-react 图标组件名字符串，由使用方映射为组件渲染
export const CATEGORY_META = {
  file_operations: { label: '文件操作', icon: 'FileText', desc: '读取 Excel / Word / PDF / CSV 等上传文件' },
  security: { label: '安全运营', icon: 'Shield', desc: 'IP 查询、威胁情报、资产归属等 SOAR 安全工具' },
  pentest_recon: { label: '渗透侦察', icon: 'Radar', desc: 'Nmap 端口扫描、Subfinder 子域名、httpx 存活探测、dnsx 解析' },
  pentest_scan: { label: '漏洞扫描', icon: 'Bug', desc: 'Nuclei PoC 扫描、SQLMap 注入检测、Nikto / ZAP Web 扫描' },
  pentest_exploit: { label: '利用与报告', icon: 'Zap', desc: 'Metasploit 利用、SearchSploit 检索、DefectDojo 漏洞管理' },
  pentest_lateral: { label: '内网渗透', icon: 'Network', desc: 'BloodHound 域分析、Hydra 爆破、CrackMapExec 横向验证' },
  asset: { label: '资产管理', icon: 'ClipboardList', desc: '资产梳理、录入、查询、更新等资产管理工具' },
  cron_jobs: { label: '定时任务', icon: 'Clock', desc: '按 Cron 表达式周期性触发工作流' },
  memory: { label: '记忆', icon: 'Brain', desc: '智能体长期记忆的存取' },
  computer_use: { label: '计算机操作', icon: 'Monitor', desc: '命令执行、文件系统、浏览器等操作系统交互' },
  clarifying_question: { label: '澄清提问', icon: 'HelpCircle', desc: '向用户提问以澄清需求或获取决策' },
  task_planning: { label: '任务规划', icon: 'ListChecks', desc: '将复杂任务分解为有序步骤' },
  task_delegation: { label: '任务委派', icon: 'Send', desc: '委派子代理或触发工作流技能' },
}

export const UNCATEGORIZED = { label: '其他', icon: 'Package', desc: '未分类工具' }

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
