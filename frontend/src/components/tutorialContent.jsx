/**
 * 各功能模块的教程内容定义。
 * 供 TutorialDrawer 渲染：每个导出是一个 sections 数组。
 *
 * 每个 section: { icon, title, content: JSX, tips?: [string] }
 */

// ============ 工具管理教程 ============
export const TOOL_TUTORIAL = [
  {
    icon: '🔧',
    title: '工具概述',
    content: (
      <p>
        工具是智能体可以调用的外部能力，例如查询 IP 资产信息、封禁防火墙、查询威胁情报等。
        每个工具定义了名称、描述、参数 schema 和执行代码。智能体在对话中根据用户意图自动选择并调用合适的工具。
      </p>
    ),
  },
  {
    icon: '✨',
    title: '创建工具',
    content: (
      <div className="space-y-2">
        <p>点击页面右上角「新建工具」按钮，填写以下信息：</p>
        <ul className="ml-4 list-disc space-y-1">
          <li><b>名称</b>：工具的唯一标识，如 <code className="text-brand-300">get_asset_info</code></li>
          <li><b>描述</b>：告诉 LLM 这个工具做什么、什么时候用（写清楚 LLM 才能正确选用）</li>
          <li><b>参数 Schema</b>：定义工具接受的参数（名称、类型、是否必填、描述）</li>
          <li><b>执行代码</b>：Python 异步函数 <code className="text-brand-300">async def run(**kwargs)</code>，返回可 JSON 序列化的结果</li>
        </ul>
      </div>
    ),
    tips: [
      '描述要写给 LLM 看，越清晰越好，例如「查询 IP 对应的资产归属信息，包括部门、负责人」',
      '执行代码中不能使用 import 语句（沙箱安全限制），所有依赖需在函数内调用已有模块',
    ],
  },
  {
    icon: '📋',
    title: '参数 Schema 配置',
    content: (
      <div className="space-y-2">
        <p>每个参数包含：</p>
        <ul className="ml-4 list-disc space-y-1">
          <li><b>名称</b>：参数名，与代码中 <code className="text-brand-300">kwargs.get('参数名')</code> 一致</li>
          <li><b>类型</b>：String / Integer / Boolean / Number</li>
          <li><b>必填</b>：是否必须提供</li>
          <li><b>描述</b>：参数说明，帮 LLM 理解该传什么值</li>
        </ul>
      </div>
    ),
  },
  {
    icon: '🧪',
    title: '测试工具',
    content: (
      <p>
        在工具列表中点击「测试」按钮，填入参数后执行。测试结果会显示工具返回的完整内容，
        方便验证工具逻辑是否正确。测试不影响线上智能体。
      </p>
    ),
  },
  {
    icon: '🔗',
    title: '关联到智能体',
    content: (
      <p>
        工具创建后，在「智能体管理」→ 编辑智能体 →「工具配置」中勾选要启用的工具。
        只有被勾选的工具才会出现在智能体的可用工具列表中。
      </p>
    ),
    tips: [
      '智能体不会自动使用任何工具，必须在配置中显式勾选',
      'read_document 和 list_documents 是内置工具，用于读取上传的未分段文档原文',
    ],
  },
]

// ============ 知识库教程 ============
export const KNOWLEDGE_BASE_TUTORIAL = [
  {
    icon: '📚',
    title: '知识库概述',
    content: (
      <p>
        知识库用于存储和检索结构化/非结构化文档。上传文档后系统自动分段、向量化，
        智能体对话时通过 RAG（检索增强生成）从知识库中召回相关片段，提供准确的上下文。
      </p>
    ),
  },
  {
    icon: '✨',
    title: '创建知识库',
    content: (
      <div className="space-y-2">
        <p>点击「新建知识库」，配置以下核心选项：</p>
        <ul className="ml-4 list-disc space-y-1">
          <li><b>名称</b>：知识库标识</li>
          <li><b>分段模式</b>：
            <ul className="ml-4 list-disc">
              <li>固定长度：按字符数分段</li>
              <li>按行分段：每行作为一个段落（适合表格、IP 列表）</li>
              <li>按段落标记：按空行或标题分段</li>
            </ul>
          </li>
          <li><b>索引模式</b>：向量索引（语义检索）或全文索引（关键词检索）</li>
          <li><b>Embedding 模型</b>：用于生成向量的嵌入模型</li>
          <li><b>检索设置</b>：Top-K（返回前 K 条相关结果）、相似度阈值</li>
        </ul>
      </div>
    ),
    tips: [
      'IP 地址表等结构化数据推荐用「按行分段」，每行包含完整信息',
      '检索 Top-K 建议设为 3-5，太多会引入噪音，太少可能遗漏',
    ],
  },
  {
    icon: '📤',
    title: '上传文档',
    content: (
      <div className="space-y-2">
        <p>支持以下格式：</p>
        <ul className="ml-4 list-disc space-y-1">
          <li><b>Excel</b>：.xlsx / .xls（按行解析，每行一个段落）</li>
          <li><b>Word</b>：.docx</li>
          <li><b>PDF</b>：.pdf</li>
          <li><b>文本</b>：.csv / .txt / .json / .md</li>
        </ul>
        <p>上传后系统自动分段并生成向量索引，可在文档列表查看分段数和状态。</p>
      </div>
    ),
    tips: [
      '如果上传后分段数为 0，检查文件格式是否正确或重新解析',
      'Excel 文件的工作表名会作为字段跟随数据行，不会被独立分成一段',
    ],
  },
  {
    icon: '🔍',
    title: '检索测试',
    content: (
      <p>
        在文档列表中点击「检索测试」，输入查询内容，系统会返回最相关的分段结果，
        帮你验证知识库的检索效果。可以调整 Top-K 和相似度阈值来优化召回。
      </p>
    ),
  },
  {
    icon: '🔗',
    title: '关联到智能体',
    content: (
      <p>
        在智能体编辑页的「知识库对接」中勾选要关联的知识库。智能体对话时会自动检索关联知识库的相关内容。
      </p>
    ),
    tips: [
      'read_document 工具是知识库的补充：知识库做精准片段检索，read_document 读取整篇文档原文',
    ],
  },
]

// ============ 技能管理教程 ============
export const SKILL_TUTORIAL = [
  {
    icon: '🎯',
    title: '技能概述',
    content: (
      <p>
        技能是将工作流封装为智能体可调用的能力。创建技能后，智能体可以在对话中
        通过 <code className="text-brand-300">trigger_workflow_skill</code> 工具触发对应的工作流，
        实现复杂的多步骤自动化。
      </p>
    ),
  },
  {
    icon: '✨',
    title: '创建技能',
    content: (
      <div className="space-y-2">
        <p>创建技能需要指定：</p>
        <ul className="ml-4 list-disc space-y-1">
          <li><b>名称</b>：技能标识</li>
          <li><b>关联工作流</b>：技能触发后执行的工作流</li>
          <li><b>描述</b>：告诉 LLM 什么时候用这个技能</li>
          <li><b>输入参数</b>：技能接受参数的 schema（映射到工作流输入）</li>
        </ul>
      </div>
    ),
  },
  {
    icon: '⚙️',
    title: '技能与工作流的关系',
    content: (
      <p>
        技能是工作流的「智能体接口」。工作流定义了执行逻辑（节点编排），
        技能定义了智能体如何触发它（参数映射、触发条件）。一个工作流可以对应多个技能。
      </p>
    ),
    tips: [
      '技能描述要写清楚使用场景，例如「当用户需要封禁 IP 时触发防火墙封禁工作流」',
    ],
  },
  {
    icon: '🔄',
    title: '中断与审批',
    content: (
      <p>
        如果工作流中包含「人工审批」节点，技能触发后会中断等待审批。
        审批通过后自动恢复执行。在「审批中心」可以处理待审批的技能执行。
      </p>
    ),
  },
]

// ============ 模型设置教程 ============
export const LLM_TUTORIAL = [
  {
    icon: '🧠',
    title: '模型配置概述',
    content: (
      <p>
        模型设置页管理所有 LLM 供应商配置（API Key、Base URL、模型名等）。
        智能体和工作流节点通过引用这些配置来调用大模型。可标记一个为「默认配置」。
      </p>
    ),
  },
  {
    icon: '✨',
    title: '添加模型配置',
    content: (
      <div className="space-y-2">
        <p>点击「新建配置」，填写：</p>
        <ul className="ml-4 list-disc space-y-1">
          <li><b>名称</b>：配置标识，如「Claude 默认配置」</li>
          <li><b>Provider</b>：供应商（Anthropic / OpenAI / DeepSeek / 火山引擎 等）</li>
          <li><b>Model Name</b>：模型名，如 <code className="text-brand-300">claude-3-5-sonnet-20241022</code></li>
          <li><b>API Key</b>：供应商提供的密钥（会自动去除首尾空白）</li>
          <li><b>Base URL</b>：自定义 API 地址（可空，使用供应商默认地址）</li>
        </ul>
      </div>
    ),
    tips: [
      'API Key 会自动去除首尾空白，避免复制粘贴引入的换行符',
      '火山引擎等 OpenAI 兼容服务，Base URL 不要带 /chat/completions 后缀（系统会自动处理）',
    ],
  },
  {
    icon: '🧪',
    title: '测试连通性',
    content: (
      <p>
        配置完成后点击「测试」按钮，系统会发送一条简单消息验证模型是否可用。
        测试结果会显示模型回复内容。测试调用也会被记录到监控统计中。
      </p>
    ),
  },
  {
    icon: '📊',
    title: '调用监控',
    content: (
      <div className="space-y-2">
        <p>切换到「调用监控」Tab，可以查看每个模型的调用情况：</p>
        <ul className="ml-4 list-disc space-y-1">
          <li><b>调用次数</b>：总调用次数（含成功和失败）</li>
          <li><b>成功率</b>：成功调用占比</li>
          <li><b>平均/最大耗时</b>：响应延迟统计</li>
          <li><b>Token 用量</b>：输入/输出 Token 总量</li>
          <li><b>调用明细</b>：点击「明细」查看最近 100 次调用的详细记录</li>
        </ul>
        <p>支持按 1/7/14/30 天筛选统计范围。</p>
      </div>
    ),
    tips: [
      '如果成功率突然下降，检查 API Key 是否过期或额度是否用尽',
      'Token 用量可以帮助评估模型成本',
    ],
  },
]

// ============ 设备对接教程 ============
export const DEVICE_TUTORIAL = [
  {
    icon: '🔌',
    title: '设备对接概述',
    content: (
      <p>
        设备对接页管理安全设备的连接和操作。支持防火墙、IDS/IPS、SIEM 等设备的对接，
        智能体和工作流可以通过工具调用对设备下发操作指令（如封禁 IP、查询日志）。
      </p>
    ),
  },
  {
    icon: '✨',
    title: '添加设备',
    content: (
      <div className="space-y-2">
        <p>点击「添加设备」，填写设备信息：</p>
        <ul className="ml-4 list-disc space-y-1">
          <li><b>名称</b>：设备标识</li>
          <li><b>类型</b>：防火墙 / IDS / IPS / SIEM / WAF 等</li>
          <li><b>连接地址</b>：IP 或域名</li>
          <li><b>认证信息</b>：API Token 或用户名密码</li>
          <li><b>接口配置</b>：API 端点路径、请求方法等</li>
        </ul>
      </div>
    ),
    tips: [
      '设备凭据会加密存储，不会明文暴露',
    ],
  },
  {
    icon: '⚙️',
    title: '设备操作',
    content: (
      <p>
        每个设备可以定义多个操作（如 block_ip、query_log、list_rules）。
        每个操作对应一个 API 调用，定义了请求方法、路径、参数映射。
        智能体通过工具调用这些操作来控制设备。
      </p>
    ),
  },
  {
    icon: '🧪',
    title: '测试设备连接',
    content: (
      <p>
        添加设备后点击「测试连接」验证设备是否可达。也可以单独测试某个操作，
        查看设备返回的实际响应，确认接口配置是否正确。
      </p>
    ),
    tips: [
      '测试前确保设备 API 已开放访问权限',
      '防火墙操作（如封禁 IP）通常是幂等的，重复执行不会产生副作用',
    ],
  },
]
