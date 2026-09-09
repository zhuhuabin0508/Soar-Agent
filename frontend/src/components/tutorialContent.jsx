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
          <li><b>名称</b>：工具的唯一标识，如 <code className="text-primary">get_asset_info</code></li>
          <li><b>描述</b>：告诉 LLM 这个工具做什么、什么时候用（写清楚 LLM 才能正确选用）</li>
          <li><b>参数 Schema</b>：定义工具接受的参数（名称、类型、是否必填、描述）</li>
          <li><b>执行代码</b>：Python 异步函数 <code className="text-primary">async def run(**kwargs)</code>，返回可 JSON 序列化的结果</li>
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
          <li><b>名称</b>：参数名，与代码中 <code className="text-primary">kwargs.get('参数名')</code> 一致</li>
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
        通过 <code className="text-primary">trigger_workflow_skill</code> 工具触发对应的工作流，
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
          <li><b>Model Name</b>：模型名，如 <code className="text-primary">claude-3-5-sonnet-20241022</code></li>
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

// ============ 材料管理教程 ============
export const DELIVERABLE_TUTORIAL = [
  {
    icon: '📖',
    title: '材料管理概述',
    content: (
      <p>
        材料管理用于按<b>树形目录</b>归档交付文件，支持最多 <b>10 级</b>子目录。
        页面分为左侧目录树 + 右侧材料列表 + 预览面板三栏布局，
        目录树宽度可在 180px–520px 之间拖拽调节（位置自动记住）。
        支持 13 种文件类型（xlsx / xls / doc / docx / ppt / pptx / pdf / zip / rar / 7z / txt / csv / md），单文件 ≤ 200MB。
      </p>
    ),
  },
  {
    icon: '📚',
    title: '目录树浏览',
    content: (
      <div className="space-y-2">
        <p>左侧目录树采用<b>纯缩进 + 字号递减</b>区分层级（无竖线连接线，降低视觉噪音）：</p>
        <ul className="ml-4 list-disc space-y-1">
          <li><b>层级缩进</b>：一级 16px → 二级 32px → 三级 52px → …每级固定 20px 递进</li>
          <li><b>空目录</b>：图标和文字统一降为灰色，提示该目录及子目录均无材料</li>
          <li><b>实目录</b>：保持亮色，数字徽章显示该目录及所有子目录的<b>递归材料数</b></li>
          <li><b>选中态</b>：左侧 3px 青色竖线 + 背景高亮，与右侧面包屑标签呼应</li>
          <li><b>名称截断</b>：长名自动截断省略号，悬停显示完整名称</li>
          <li><b>展开/折叠</b>：点击节点左侧箭头切换；展开状态自动持久化</li>
        </ul>
        <p>目录树顶部可「全部展开」「一键收起」「新建根目录」；底部显示<b>「共 X 个目录 · 已展开 Y」</b>统计与一键收起按钮。</p>
      </div>
    ),
    tips: [
      '右键目录节点可快速访问「新建子目录 / 编辑 / 移动 / 删除」操作',
      '面包屑导航可一键跳转到任意上级目录',
    ],
  },
  {
    icon: '✨',
    title: '创建与管理目录',
    content: (
      <div className="space-y-2">
        <p>有 <code className="text-primary">deliverable.edit</code> 权限的用户可创建/编辑/移动目录：</p>
        <ul className="ml-4 list-disc space-y-1">
          <li><b>新建目录</b>：选择父级（可选任意已有目录作为父级，「根级」为最顶层）、名称、描述</li>
          <li><b>新建子目录</b>：在目录节点上点击「+」或右键，自动以当前目录为父级</li>
          <li><b>编辑目录</b>：修改名称、描述</li>
          <li><b>移动目录</b>：选择新的父级目录，系统会阻止移动到自身或子孙目录（防止循环）</li>
          <li><b>删除目录</b>：仅当目录无子目录且无材料时可删除</li>
        </ul>
        <p>同级（同一父目录下）目录名称必须唯一；层级不得超过 10 级。</p>
      </div>
    ),
    tips: [
      '创建子目录后，父级目录会自动展开',
      '移动目录时层级会自动重算，系统会提示层级变化（如 L2 → L3）',
    ],
  },
  {
    icon: '📤',
    title: '上传材料',
    content: (
      <div className="space-y-2">
        <p>选中目录后点击「上传材料」，支持<b>文件 / 文件夹</b>两种迁入方式：</p>
        <ul className="ml-4 list-disc space-y-1">
          <li><b>拖拽文件夹</b>：像 Windows 复制文件夹一样，自动按原目录结构创建子目录</li>
          <li><b>选择文件夹</b>：点「选择文件夹」整夹上传，同级同名目录会复用</li>
          <li><b>选择文件</b>：仍可一次多选文件，直接落到当前目录</li>
          <li><b>批量设置</b>：版本号、描述会统一应用到本次上传的全部文件</li>
        </ul>
        <p>上传后系统自动记录<b>上传人、上传时间、文件大小、文件名</b>，文件列表会显示上传时间列。</p>
      </div>
    ),
    tips: [
      '允许的 13 种类型：xlsx / xls / doc / docx / ppt / pptx / pdf / zip / rar / 7z / txt / csv / md',
      '单文件不得超过 200MB，空文件会被拒绝',
      '可执行文件（exe/sh 等）严格禁止',
    ],
  },
  {
    icon: '🔍',
    title: '搜索与视图切换',
    content: (
      <div className="space-y-2">
        <p>右侧材料列表支持两种视图 + 搜索筛选：</p>
        <ul className="ml-4 list-disc space-y-1">
          <li><b>列表视图</b>：表格形式，固定列宽，长文件名自动截断省略号</li>
          <li><b>网格视图</b>：卡片形式，更适合可视化浏览</li>
          <li><b>搜索框</b>：按材料名称 / 文件名 / 版本模糊匹配，回车或点击搜索</li>
        </ul>
        <p>视图模式与目录树展开状态都会持久化到本地存储，刷新页面不丢失。</p>
      </div>
    ),
    tips: [
      '搜索结果为空时，空状态会提示「子目录中共有 N 个材料」，避免误以为整个模块为空',
    ],
  },
  {
    icon: '🧪',
    title: '预览与在线编辑',
    content: (
      <div className="space-y-2">
        <p>点击材料的「预览」按钮，根据类型在右侧面板展示：</p>
        <ul className="ml-4 list-disc space-y-1">
          <li><b>Word（.docx）</b>：浏览器内直接预览正文与分页</li>
          <li><b>Excel（.xlsx / .xls）</b>：表格在线预览，多工作表可切换（单表最多显示 2000 行）</li>
          <li><b>PDF</b>：iframe 内嵌预览（fetch blob 后渲染）</li>
          <li><b>TXT / CSV / MD</b>：可在线编辑的文本编辑器（≤ 5MB），修改后点击「保存」</li>
          <li><b>旧版 .doc / 压缩包 / PPT</b>：提示不支持预览，提供下载按钮</li>
        </ul>
        <p>文本编辑支持<b>未保存标记</b>，编辑后「保存」按钮才会高亮可用。</p>
      </div>
    ),
    tips: [
      '只有具备 deliverable.edit 权限的用户才能编辑文本内容，其他人为只读模式',
    ],
  },
  {
    icon: '📋',
    title: '单/批量下载',
    content: (
      <div className="space-y-2">
        <p>支持单个文件下载和<b>跨页批量下载</b>：</p>
        <ul className="ml-4 list-disc space-y-1">
          <li><b>单文件下载</b>：点击文件行的下载按钮</li>
          <li><b>批量下载</b>：勾选多个文件（可跨页），点击「批量下载 (N)」打包为 zip</li>
          <li><b>跨页全选</b>：当结果超过当前页时，可点击「全选 N」一次性选中所有匹配项（上限 10000）</li>
        </ul>
        <p>批量下载限制每次最多 50 个文件，超出请缩小搜索范围。</p>
      </div>
    ),
    tips: [
      '切换目录或翻页时不会清空已选，但切换搜索条件会清空',
      '已选数量以青色标签形式高亮显示，可一键清空',
    ],
  },
  {
    icon: '📊',
    title: '统计栏',
    content: (
      <p>
        顶部统计栏以「<b>图标 + 竖线分隔</b>」的形式紧凑展示目录总数、材料总数、当前目录信息。
        选中目录时，当前目录名以青色标签高亮，并显示「含子目录共 N 个材料」的递归统计。
      </p>
    ),
  },
  {
    icon: '🛡️',
    title: '权限说明',
    content: (
      <div className="space-y-2">
        <ul className="ml-4 list-disc space-y-1">
          <li><b>deliverable.view</b>：可见目录和材料、可预览/下载</li>
          <li><b>deliverable.edit</b>：可建目录、上传、在线编辑文本</li>
          <li><b>deliverable.delete</b>：可删除目录和材料</li>
        </ul>
        <p>非管理员用户仅能编辑/删除<b>自己创建</b>的资源；他人资源为只读，除非通过共享获得编辑权限。</p>
      </div>
    ),
    tips: [
      '空状态会根据权限智能提示：有权限显示「上传材料 / 新建子目录」按钮，无权限提示「等待有权限的用户上传」',
    ],
  },
]

// ============ 运营大屏教程 ============
export const DASHBOARD_TUTORIAL = [
  {
    icon: '📊',
    title: '运营大屏概述',
    content: (
      <p>
        运营大屏聚合展示<b>安全运营、AI 使用、材料管理</b>三大维度的实时数据。
        顶部支持 Tab 切换三个大屏，右上角可开关「自动刷新」（默认每 30 秒）并手动刷新。
        所有 KPI 卡片和图表模块均支持<b>点击下钻</b>，通过右侧抽屉展示过滤后的明细列表。
      </p>
    ),
  },
  {
    icon: '🛡️',
    title: '安全运营大屏',
    content: (
      <div className="space-y-2">
        <p>聚焦安全事件处置效率，包含：</p>
        <ul className="ml-4 list-disc space-y-1">
          <li><b>KPI 卡片</b>：今日告警、自动处置成功率、MTTR（平均处置时长）、待审批数，带环比微标</li>
          <li><b>近 7 日趋势</b>：自动化处置 vs 人工介入双折线对比</li>
          <li><b>告警分类占比</b>：环形图，点击扇区下钻到该类告警列表</li>
          <li><b>Top 10 恶意攻击源 IP</b>：横向柱状排行，点击下钻</li>
        </ul>
        <p>所有模块点击后弹出 HalfDrawer 抽屉展示过滤后的明细。</p>
      </div>
    ),
    tips: [
      'KPI 卡片右上角的 ↑15% / ↓3% 微标悬停可看环比详情，点击直接下钻',
    ],
  },
  {
    icon: '📚',
    title: '材料管理大屏',
    content: (
      <div className="space-y-2">
        <p>展示材料归档的全景统计，包含：</p>
        <ul className="ml-4 list-disc space-y-1">
          <li><b>KPI 卡片</b>：目录类别、材料总数、今日新增、本周新增、占用空间，均带环比趋势</li>
          <li><b>目录文件数统计</b>：可切换 <b>一级 / 二级 / 三级</b>目录的文件数排行（Top 8），递归含子目录材料</li>
          <li><b>文件类型分布</b>：环形图 + 详情列表（数量/占比/总大小/平均大小），点击扇区联动最近上传</li>
          <li><b>上传趋势</b>：近 7 日 / 近 30 日 / 本年度切换，7 日模式含双 Y 轴（文件数 + 大小）</li>
          <li><b>最近上传</b>：卡片列表，可按扩展名或日期联动筛选</li>
        </ul>
        <p>所有 KPI 卡片点击可跳转到材料管理页继续操作。</p>
      </div>
    ),
    tips: [
      '目录文件数统计的每个目录含递归子目录材料数，Top 3 用金银铜奖牌标识',
      '切换一级/二级/三级可对比不同层级的文件分布，Tooltip 显示完整路径区分同名子目录',
      '某层级无目录时，空状态会提示「切换其他层级，或创建目录并上传材料后将自动统计」',
    ],
  },
  {
    icon: '🧠',
    title: 'AI 使用大屏',
    content: (
      <p>
        展示 AI 模型的调用情况：总调用数、成功率、Token 用量、平均耗时等 KPI，
        以及按模型/按日趋势、Top 活跃用户等图表，帮助评估模型成本与服务健康度。
      </p>
    ),
  },
  {
    icon: '🔄',
    title: '自动刷新与下钻',
    content: (
      <div className="space-y-2">
        <ul className="ml-4 list-disc space-y-1">
          <li><b>自动刷新</b>：右上角开关，开启后每 30 秒重新拉取数据，状态指示灯闪烁</li>
          <li><b>手动刷新</b>：点击「刷新」按钮立即拉取，按钮图标旋转动画</li>
          <li><b>下钻抽屉</b>：KPI 卡片、图表元素点击后从右侧滑出 HalfDrawer，展示过滤明细</li>
        </ul>
      </div>
    ),
    tips: [
      '抽屉支持嵌套和滑动关闭（ESC 或点击遮罩）',
      '下钻数据基于当前大屏的统计范围，不会跨模块混入',
    ],
  },
]
