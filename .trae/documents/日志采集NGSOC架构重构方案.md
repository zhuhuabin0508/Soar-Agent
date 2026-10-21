# 日志采集功能 NGSOC 式架构重构方案

## 一、背景与目标

**背景**：现有日志采集仅支持 syslog(UDP/TCP)/Kafka/webhook 三种源，全部逻辑集中在 `backend/app/core/log_receiver_manager.py`（约 1400 行）：厂商预处理（青藤）硬编码 if/elif、流水线步骤（规整→预处理→解析→入库）不可插拔。参考奇安信 NGSOC 的"多源输入层 + 范式化流水线"架构进行优化。

**目标**：
1. **多源输入层**：7 种输入适配器（Syslog、JDBC、SNMP Trap、NetFlow、REST API、端口镜像抓包、日志文件跟踪），插件化注册，统一输出 `RawEvent` 标准原始事件
2. **范式化流水线**：解析→过滤→富化→内容转译→范式化 五步可插拔组件，输出 ECS 风格 `NormalizedEvent`，末端映射到现有 `AlertEvent`（下游告警页/工作流/看板零改动）
3. **可插拔总线**：`RawEventBus` 抽象，默认进程内有界队列（沿用现有背压），可配置切换 Kafka
4. **三原则**：插件化（注册表模式）、可配置（JSON 配置驱动，不硬编码）、统一 schema

**用户已确认的决策**：原地重构（不建并行子系统）、可插拔总线（默认进程内）、中间层事件+末端映射（AlertEvent 不动）、7 种适配器全部可运行。

## 二、架构总览

```
设备/数据源
   │
   ▼
┌─ 多源输入层（7 适配器，插件注册）──────────────────────────┐
│ Syslog │ JDBC │ SNMP Trap │ NetFlow │ REST API │ 抓包 │ 文件跟踪 │
│   (每个适配器独立线程，复用 generation/stop_event 状态机)      │
└──────────────┬──────────────────────────────────────┘
               ▼ 统一 RawEvent{receiver_id, device_id, source_type,
                 source_ip, transport, received_at, raw, meta, receiver}
┌─ RawEventBus（可插拔总线）───────────────────────────────┐
│ 默认: InProcessBus(queue.Queue(2000) + 8 worker + 丢包窗口聚合) │
│ 可选: KafkaBus(LOG_BUS_BACKEND=kafka 切换)                   │
└──────────────┬──────────────────────────────────────┘
               ▼ worker 逐事件执行 PipelineRunner（五步可插拔）
┌─ 范式化流水线 ───────────────────────────────────────────┐
│ [预处理插件链] → ①Parser(复用ParseEngine+策略JSON)          │
│   → ②Filter(可配置丢弃规则,默认禁用) → ③Enricher(资产富化等)  │
│   → ④Translator(标准词表补填) → ⑤Normalizer(NormalizedEvent  │
│   → AlertEvent 落库, 复用 SQLAlchemySink 重复→partial 语义)  │
└──────────────┬──────────────────────────────────────┘
               ▼
   AlertEvent / DeviceReceiveLog / DeviceReceiveMetric / ParseErrorQueue（表不变）
```

## 三、目录结构（原地重构：模块转同名包）

**`log_receiver_manager.py` 转为 `log_receiver_manager/` 包**——`from app.core.log_receiver_manager import X` 的 6 处引用路径（[main.py:264](file:///d:/trae%20project/soar-src/backend/app/main.py)、[devices.py:424](file:///d:/trae%20project/soar-src/backend/app/api/v1/devices.py)、[log_receivers.py:22,342,358,384](file:///d:/trae%20project/soar-src/backend/app/api/v1/log_receivers.py)）零改动。

```
backend/app/core/log_receiver_manager/          # 原 .py → 同名包（唯一采集子系统）
├── __init__.py                # 门面：re-export 全部原对外符号
│                              #   start_log_receiver_manager / ensure_receiver_thread /
│                              #   start_receiver_sync / stop_receiver_thread /
│                              #   reload_all_receivers / get_receiver_runtime_status /
│                              #   ReceiverSink / parse_qingteng_syslog / _coerce_payload（防测试脚本引用）
├── events.py                  # RawEvent / NormalizedEvent（ECS 风格统一 schema）
├── registry.py                # AdapterRegistry / StageRegistry / PreprocessorRegistry
├── adapter_context.py         # AdapterContext：适配器运行时句柄
├── base_adapter.py            # BaseAdapter 抽象基类
├── runtime.py                 # 状态机/启停/reload/健康检查/文件锁/worker 池（自原文件平移）
├── adapters/
│   ├── __init__.py            # import 触发各适配器自注册（插件发现点）
│   ├── syslog_adapter.py      # 迁移自 _run_syslog_listener + socketserver
│   ├── kafka_adapter.py       # 迁移自 _run_kafka_consumer（aiokafka 循环+积压采样）
│   ├── jdbc_adapter.py        # SQLAlchemy 轮询 + 时间水位
│   ├── snmp_trap_adapter.py   # pysnmp 收 trap
│   ├── netflow_adapter.py     # UDP 收 v5(手解)/v9+IPFIX(netflow 库)
│   ├── rest_api_adapter.py    # httpx 轮询分页拉取
│   ├── pcap_adapter.py        # scapy AsyncSniffer（容器需 NET_RAW）
│   └── file_tail_adapter.py   # tail -F 语义（零新依赖）
├── bus/
│   ├── base.py                # RawEventBus 抽象接口
│   ├── inprocess_bus.py       # 默认：包装现有 queue(2000)+8worker+丢包窗口
│   └── kafka_bus.py           # 可选 Kafka 后端（aiokafka，环境变量切换）
└── pipeline/
    ├── preprocessors.py       # RawPreprocessor 插件：json/青藤/纯文本 三内置
    ├── base_stage.py          # BaseStage 抽象 + PipelineData 流转对象
    ├── parser_stage.py        # 复用 ParseEngine（策略优先级：渠道固定>设备绑定>自动）
    ├── filter_stage.py        # config 驱动丢弃规则（默认 enabled=false）
    ├── enricher_stage.py      # 富化器插件（内置资产关联）
    ├── translator_stage.py    # 标准词表翻译（risk_level/deal_status 等，仅补空值）
    ├── normalizer_stage.py    # NormalizedEvent 构建 → AlertEvent 映射落库
    ├── sink.py                # ReceiverSink + _summarize_large_value 平移
    ├── runner.py              # PipelineRunner：组装五步链（按 config hash 缓存）
    └── pipeline_default.json  # 流水线默认配置
```

## 四、核心类设计（代码骨架）

### 4.1 统一 schema（events.py）

```python
@dataclass
class RawEvent:
    """适配器输出的标准原始事件（所有源类型统一结构）。"""
    receiver_id: int
    device_id: Optional[int]
    source_type: str            # = LogReceiver.protocol
    source_ip: Optional[str]    # syslog 对端/netflow exporter；拉取类为远端地址
    transport: str              # udp/tcp/kafka/jdbc/rest_api/file/pcap/snmp
    received_at: datetime
    raw: str                    # 原始报文文本
    meta: dict = field(default_factory=dict)    # topic/partition、netflow 版本、轮询游标等
    receiver: dict = field(default_factory=dict)  # 渠道配置快照（沿用现有扁平 dict）

@dataclass
class NormalizedEvent:
    """ECS 风格范式化事件；末端映射回 AlertEvent。"""
    # ECS event.*
    uuid: str = ""; event_name: str = ""; event_content: str = ""
    risk_level: int = -1; risk_level_name: str = ""
    threat_class: str = ""; threat_type: str = ""; threat_sub_type: str = ""
    recommendation: str = ""; severity: int = -1; confidence: int = -1
    # ECS source.* / destination.*
    src_ip: str = ""; src_port: str = ""; src_region_name: str = ""
    dst_ip: str = ""; dst_port: str = ""; dst_region_name: str = ""
    direction: str = ""; protocol: str = ""
    # ECS host.* / user.*
    host_ip: str = ""; user_name: str = ""; account_name: str = ""
    agent_id: str = ""; asset_id: str = ""
    # 时间
    occur_timestamp: Optional[datetime] = None
    upload_timestamp: Optional[datetime] = None
    first_timestamp: Optional[datetime] = None
    last_timestamp: Optional[datetime] = None
    # 规则元数据
    strategy_id: Optional[int] = None
    device_type: str = ""; rule_id: str = ""; log_type: str = ""
    parse_status: str = "success"; parse_warnings: list = field(default_factory=list)
    # 兜底
    extra_fields: dict = field(default_factory=dict)  # 未列入清单的 AlertEvent 列原样透传
    extensions: dict = field(default_factory=dict)
    raw_data: str = ""; ecs_version: str = "soar-ecs-1.0"

    @classmethod
    def from_parse_result(cls, result) -> "NormalizedEvent":
        """ParseEngine 输出的 fields dict（键=AlertEvent 列名）→ ECS 事件：
        约 40 个核心键提为 ECS 字段，其余进 extra_fields。"""

    def to_alert_fields(self) -> dict:
        """ECS 字段 + extra_fields 合并 → AlertEvent(**fields) 兼容 dict；
        extensions/parse_warnings → json.dumps。与今日 ParseEngine 输出逐键等价。"""
```

**兼容桥关键**：ParseEngine 输出本来就是 AlertEvent 列名 dict，`from_parse_result → to_alert_fields` 无损往返，实现"统一 schema"且"下游零改动"。

### 4.2 适配器基类与运行时句柄

```python
class AdapterContext:
    """runtime 注入给适配器的句柄（替代直接摸 _runtimes）。"""
    receiver_id: int; generation: int
    stop_event: threading.Event
    receiver: dict                          # 含 adapter_config 解析结果
    runtime_ref: dict                       # 适配器可存放 server/sniffer 等供 stop() 用
    def signal_ready(self, success: bool, error: str = "") -> None: ...  # 迁移自 _signal_generation_started
    def set_status(self, status: str, error: Optional[str] = None) -> None: ...
    def publish(self, raw: str, source_ip: Optional[str] = None,
                meta: Optional[dict] = None, blocking: bool = False,
                timeout: float = 5.0) -> bool:
        """投递 RawEvent 到总线；blocking=True 走 kafka 式阻塞背压，
        否则丢弃+窗口聚合告警（沿用现两种提交语义）。"""

class BaseAdapter(ABC):
    source_type: ClassVar[str]              # "syslog"/"jdbc"/"snmp_trap"...
    display_name: ClassVar[str]
    default_ready_timeout_s: ClassVar[float] = 8.0   # start_receiver_sync 同步等待超时
    required_config_keys: ClassVar[list] = []        # [(键,中文说明)] 供 API 校验与前端提示

    def __init__(self, ctx: AdapterContext) -> None: self.ctx = ctx

    @abstractmethod
    def run(self) -> None:
        """阻塞运行至 stop；必须先 signal_ready(成功/失败)；异常吞掉记日志+set_status("failed")。"""

    def stop(self) -> None:
        """默认 stop_event.set()；持有 socket/sniffer 的适配器覆写主动 shutdown。"""
```

线程模型维持现状：**每 receiver 一条监听线程**，generation/stop_event/ready 三事件机制原样保留在 `runtime.py`，`start_receiver_sync` 的"停旧代→开新一代→同步等 ready"不变，仅 target 选择从 if/elif 换成注册表查找。

### 4.3 插件注册表（registry.py）

```python
class AdapterRegistry:
    def register(self, cls) -> cls: ...                      # 装饰器注册，按 source_type 键
    def get(self, source_type: str) -> Optional[type]: ...
    def source_types(self) -> list[dict]: ...                # [{value,label,required_config_keys}]
    def validate_config(self, source_type: str, cfg: dict) -> list[str]: ...  # 中文错误列表

adapter_registry = AdapterRegistry()      # 模块级单例
# StageRegistry（流水线组件按 name 注册）、PreprocessorRegistry（预处理器按 name 注册）同模式
```

### 4.4 可插拔总线（bus/）

```python
class RawEventBus(ABC):
    def publish(self, event: RawEvent, blocking=False, timeout=5.0) -> bool: ...
    def consume(self) -> RawEvent: ...          # worker 阻塞取
    def task_done(self) -> None: ...
    def start(self) -> None: ...                # 启动 N 个 worker 线程
    def stats(self) -> dict: ...                # {"qsize","maxsize","dropped"}
    def stop(self) -> None: ...
```

- **InProcessBus（默认）**：内部即现 `queue.Queue(2000)` + 8 worker，`_drop_warning_record/_flush` 窗口聚合迁入类方法；worker 循环体=现 `_ingest_worker`，从 3 元组换 `RawEvent`
- **KafkaBus（可选）**：aiokafka producer/consumer，RawEvent 加 `to_dict()/from_dict()` JSON 序列化；环境变量 `LOG_BUS_BACKEND=inprocess|kafka`、`LOG_BUS_KAFKA_BOOTSTRAP`、`LOG_BUS_KAFKA_TOPIC` 切换，默认 inprocess

### 4.5 流水线五步（pipeline/）

```python
@dataclass
class PipelineData:
    """流水线流转对象。"""
    event: RawEvent
    payload: Any = None                       # 预处理器输出（dict 或 list[dict]）
    items: list[dict] = field(default_factory=list)     # Parser 展开的逐条 dict
    results: list = field(default_factory=list)         # ParseResult 列表
    normalized: list[NormalizedEvent] = field(default_factory=list)
    dropped: int = 0                          # Filter 丢弃计数（写指标）
    enrichments: dict = field(default_factory=dict)

class BaseStage(ABC):
    name: ClassVar[str]
    def __init__(self, config: dict): self.config = config
    @abstractmethod
    def process(self, data: PipelineData, sink, db) -> None: ...
```

`PipelineRunner` 按 receiver 的 `adapter_config.pipeline`（缺省用 `pipeline_default.json`）深合并构造五步链，按 `(receiver_id, config_hash)` 缓存，`_refresh_runtime_receiver` 时失效。

## 五、七种适配器设计

| 适配器 | source_type | 线程模型 | 依赖 | 关键配置（adapter_config JSON） | ready 超时 | 状态机 |
|---|---|---|---|---|---|---|
| Syslog | `syslog` | socketserver UDP/TCP，serve_forever | 标准库 | 沿用类型化列 syslog_port/proto/bind | 3.0s | binding→listening/failed |
| Kafka | `kafka` | 线程内 asyncio + 积压采样 | aiokafka(已有) | 沿用类型化列 kafka_* | 8.0s | connecting→running/failed |
| JDBC | `jdbc` | 单轮询线程：query→逐行 publish→水位持久化→wait(interval) | sqlalchemy(已有)，驱动按需 | url、query(可含:since)、cursor_column、poll_interval_seconds(10)、batch_size(1000)、initial_cursor(latest/earliest) | 8.0s | connecting→running/failed |
| SNMP Trap | `snmp_trap` | pysnmp Asyncio Dispatcher 收 trap→varbinds 转 dict | pysnmp | bind、port(默认1162避免特权162)、community | 3.0s | binding→listening/failed |
| NetFlow | `netflow` | ThreadingUDPServer 收裸 UDP→v5 struct 手解/v9+IPFIX 走库 | netflow(缺库自动降级仅v5) | bind、port(默认2055)、versions(["v5","v9","ipfix"]) | 3.0s | binding→listening/failed |
| REST API | `rest_api` | 单轮询线程：httpx 请求→records_path 提取→游标水位 | httpx(已有) | base_url、path、method、headers、auth(none/api_key/basic/bearer)、params/body_template、records_path(点路径)、pagination(none/page/cursor)、cursor_path、poll_interval_seconds(30)、verify_tls(false)、timeout | 8.0s | connecting→running/failed |
| 抓包 | `pcap` | scapy AsyncSniffer 后台线程，prn 回调组包 | scapy（容器 NET_RAW） | iface、bpf_filter(默认"ip")、emit_mode(per_packet/batch 默认batch)、batch_size(50)、include_payload(false) | 3.0s | binding→listening/failed |
| 文件跟踪 | `file_tail` | 单线程 tail -F（EOF 记 offset，轮询检测轮转重开） | 零新依赖 | path、encoding(utf-8)、from_beginning(false)、poll_interval_seconds(2)、line_format(jsonl/raw) | 3.0s | connecting→running/failed |

代表性骨架——SyslogAdapter（迁移封装，行为等价）：

```python
@adapter_registry.register
class SyslogAdapter(BaseAdapter):
    source_type, display_name = "syslog", "Syslog 监听"
    default_ready_timeout_s = 3.0

    class _Handler(socketserver.BaseRequestHandler):
        def handle(self):
            raw = self.request[0].strip().decode("utf-8", errors="replace")
            self.server.ctx.publish(raw, source_ip=self.client_address[0])

    def run(self):
        cfg = self.ctx.receiver
        port = cfg["syslog_port"]
        if not port:
            self.ctx.set_status("start_failed", "未配置 syslog 监听端口")
            self.ctx.signal_ready(False, "未配置端口"); return
        bind = cfg.get("syslog_bind") or "0.0.0.0"
        self.ctx.set_status("binding", None)
        server = _make_server(cfg.get("syslog_proto", "udp"), bind, port, self._Handler)
        server.ctx = self.ctx
        self.ctx.runtime_ref["server"] = server      # 供 stop() shutdown
        self.ctx.signal_ready(True); self.ctx.set_status("listening", None)
        try:
            server.serve_forever()
        finally:
            server.server_close()

    def stop(self):
        self.ctx.stop_event.set()
        srv = self.ctx.runtime_ref.get("server")
        if srv: srv.shutdown()
```

## 六、流水线五步与现有引擎的复用映射

| 步骤 | 实现 | 与现有代码关系 |
|---|---|---|
| 预处理（Parser 前置插件） | `preprocessors.py`：JsonPreprocessor / QingtengSyslogPreprocessor / PlainMessagePreprocessor | `parse_qingteng_syslog`、`_coerce_payload` 函数体**原样迁入**，从硬编码优先级链变为注册表驱动链（默认链 json→qingteng_syslog→plain_message 与现行为逐字节等价）；青藤产出 `__source=qingteng_syslog` 供 route_rules 命中，**策略 JSON 零改动** |
| ① Parser | ParserStage | **复用 ParseEngine 不重写**。策略优先级照抄现逻辑：receiver.strategy_id（固定）→ Device.parser_strategy_id（设备绑定）→ loader.match 自动路由；list payload 逐条展开 |
| ② Filter | FilterStage（新） | config 驱动：`{"enabled":false,"match":"all","rules":[{"field":"risk_level","op":"gte","value":0},...],"action":"drop"}`，op ∈ eq/ne/in/not_in/gte/lte/regex/exists/empty；丢弃计数写指标。**默认禁用全透传**保证重构后行为等价 |
| ③ Enricher | EnricherStage（新） | 富化器插件（`enrich(normalized, db)` 协议）；内置 AssetEnricher（按 src_ip/host_ip 关联设备/资产表补 asset_id、内网外网标注）；GeoIP/威胁情报占位（配置存在才启用）。富化结果写 `extensions["enrichment"]` 不覆盖原字段 |
| ④ Translator | TranslatorStage（新） | 标准词表 config 驱动补填（risk_level/deal_status/direction 中文映射）；与策略级 enum_maps 分工：**策略管厂商私有词表（不变），Translator 管跨设备标准词表**，仅当目标字段为空时补填 |
| ⑤ Normalizer | NormalizerStage（新） | `NormalizedEvent.from_parse_result` → `to_alert_fields` → 复用 SQLAlchemySink.save_alert（含重复→partial 与封禁触发）→ ReceiverSink.record_parsed + metrics，照抄现尾部逻辑 |

## 七、数据模型与迁移

**新增通用 `adapter_config` 列（Text 存 JSON），保留全部现有类型化列。**

- 理由：7 新适配器 × 平均 6 配置项 ≈ 40+ 列，类型化列每加适配器都要 DDL；通用 JSON 列让"新增源类型零迁移"。syslog/kafka 现有列继续生效（旧数据零迁移）
- [log_receiver.py](file:///d:/trae%20project/soar-src/backend/app/models/log_receiver.py)：`protocol` 注释扩展为 8 种取值；新增 `adapter_config = Column(Text, nullable=False, default="{}")`
- 迁移遵循项目惯例（无 Alembic）：[security.py](file:///d:/trae%20project/soar-src/backend/app/core/security.py) `run_lightweight_migrations()` 追加 `ensure_columns(engine, "log_receivers", {"adapter_config": "TEXT NOT NULL DEFAULT '{}'"})`
- 轮询水位（jdbc/rest_api 游标）存回 `adapter_config` JSON，由适配器单线程独占写、30s 节流回写，无需新表
- **API 层新增端口唯一性校验**（项目硬约束扩展）：绑端口的源类型（syslog/snmp_trap/netflow）创建/更新时校验同 bind:port 不与其它 enabled 渠道冲突（409）

## 八、API 变更（[log_receivers.py](file:///d:/trae%20project/soar-src/backend/app/api/v1/log_receivers.py)，向后兼容）

- `LogReceiverBase` 增 `adapter_config: dict = Field(default_factory=dict)`；现有扁平字段全保留
- `_validate_payload` 注册表驱动：`protocol not in adapter_registry.source_types()` → 422；`validate_config(protocol, adapter_config)` 逐条中文报错（syslog/kafka 走旧扁平字段校验分支）
- `_serialize` 增 `"adapter_config": json.loads(rec.adapter_config or "{}")`；`_apply_fields` 写 `json.dumps`
- `start_receiver_sync` 超时与 target 选择查 `adapter_registry.get(protocol)`

## 九、前端改造（[LogReceivers.jsx](file:///d:/trae%20project/soar-src/frontend/src/pages/devices/LogReceivers.jsx)）

1. 新建 `SOURCE_TYPE_META` 常量（value/label/hint/fields[]，field 含 key/label/type:number|text|password|select|json/required/placeholder/options），8 种源类型各一组；`ProtocolSelect` 下拉扩至 8 项
2. 配置区组件化：现有 `protocol === 'syslog'` 条件块抽成 `AdapterConfigSection`，按 META 动态渲染，值读写 `form.adapter_config[key]`；syslog/kafka 保持现有扁平字段渲染（后端双轨兼容）
3. 提交组装 `adapter_config`（JSON 字段 try parse）；required 校验与后端 `required_config_keys` 对齐
4. 列表"接入信息"列按 8 类渲染（如 `bind:port(proto)`、`topic←bootstrap`、`path`、`iface[filter]`）
5. statusMeta 补 `binding/connecting`（灰色过渡）、`listening`（绿色=running）

## 十、配置体系（三层）

1. **适配器实例配置（DB）**：`log_receivers` 行 = protocol + 类型化列 + `adapter_config` JSON（适配器参数 + 可选 pipeline 覆盖段）
2. **流水线组件配置（文件+覆盖）**：全局默认 `pipeline/pipeline_default.json`（预处理器链、filter 规则、enrichers 清单、标准词表）；`adapter_config.pipeline` 深覆盖；Runner 按 config hash 缓存。**不引入 YAML**（项目全用 JSON）
3. **解析策略（不变）**：`parse_strategies` 表与 `engine/strategies/*.json` 完全不动

## 十一、实施步骤（每阶段独立可验证）

| 阶段 | 内容 | 验证 |
|---|---|---|
| 0 依赖与骨架 | requirements 增可选依赖；建包空骨架 | `python -m compileall` 通过 |
| 1 等价迁移（核心） | events/registry/context/base_adapter/bus(InProcess)/pipeline 全模块；Syslog+Kafka 适配器迁移；runtime.py 平移状态机；preprocessors 平移；五步 Stage 按"默认=现行为"实现（filter 禁用/enricher 只标注/translator 只补空）；.py 转包+门面 | compileall；pytest 全绿（新增 test_collector_registry/test_inprocess_bus/test_preprocessors/test_pipeline_stages + 原 test_parser_engine 不回归）；容器重启后发青藤样例 → 三表（receive_logs/alert_events/metrics）与重构前**逐字段一致** |
| 2 模型+API | ensure_columns 迁移 + LogReceiver 列 + API adapter_config + 端口唯一性 | 容器启动日志见 ALTER；curl 创建 file_tail 渠道 422/201 |
| 3-6 逐个适配器 | 顺序：FileTail → RestApi → Jdbc → SnmpTrap → NetFlow → Pcap（依赖从零到多） | 每个按第十二节对应行验证 |
| 7 前端动态表单 | SOURCE_TYPE_META + AdapterConfigSection + 列表渲染 | 8 类创建/启停联调 |
| 8 可选项与文档 | KafkaBus（默认关闭，仅单测）；docs 增采集架构说明（NET_RAW/驱动/端口清单） | 单测通过；文档评审 |

## 十二、验证方案

| 项 | 方法 | 通过标准 |
|---|---|---|
| 语法 | `python -m compileall backend/app/core/log_receiver_manager backend/app/core` | 无异常 |
| 单测（本机） | `pytest backend/tests/test_collector_*.py backend/tests/test_parser_engine.py -v`（新用例不依赖 DB：注册/校验、总线满载丢包、青藤预处理样例、Filter op 矩阵、Translator 补填、NormalizedEvent↔fields 往返等价；socket 类用 localhost 随机端口；平台不支持项 importorskip） | 全绿且不回归 |
| 容器 | `docker compose restart backend-dev && docker logs -f soar-backend-dev` | "日志接收管理器已启动"、无 trace |
| Syslog 端到端 | python 脚本 `socket.sendto(青藤样例, (ip,514))` | receive_logs success + alert_events 新告警 + metrics +1 |
| Kafka | 现有青藤 kafka 渠道重启后照常消费 | running、lag 采样正常 |
| FileTail | 容器内 `echo '{...}' >> 挂载卷/test.log` | 每行一条 receive log |
| RestApi | 容器内 `python -m http.server` 静态 JSON 或临时分页接口，cursor 轮询 | 拉全量、游标推进、重启不重拉 |
| Jdbc | 渠道指向平台自身 postgres（`select id,raw_data,received_at from device_receive_logs order by id`），向 514 发日志驱动数据 | 水位前进、无重复入库 |
| SnmpTrap | `snmptrap -v 2c -c public <ip>:1162 '' 1.3.6.1.6.3.1.1.5.1`（或 pysnmp 脚本） | varbinds 转 JSON 入库 |
| NetFlow | python struct 手工组 v5 包（24B header+N record）发 UDP 2055 | flow 字段 JSON 入库 |
| Pcap | docker-compose 加 `cap_add: [NET_RAW]` 后容器内 ping 网关 | 抓到包事件；未加权限时 start_failed 且 last_error 提示 NET_RAW |

## 十三、依赖清单与容器变更

requirements.txt 新增（Python 3.11 兼容）：
```
pysnmp==7.1.15        # SNMP Trap 接收
scapy==2.6.1          # 端口镜像抓包（容器需 NET_RAW；Windows 开发机需 Npcap，测试默认 skip）
netflow==0.1.1        # NetFlow v9/IPFIX 解析（缺失自动降级仅 v5）
watchdog==6.0.0       # 文件跟踪可选加速（手写 tail 轮询为默认）
pygrok==0.11.0        # 可选：未来 Grok 模式预处理插件
PyMySQL==1.1.1        # 可选：JDBC 拉 MySQL（按目标库按需）
```
httpx/aiokafka/sqlalchemy 已存在。新依赖需 `docker compose build backend-dev` 重建镜像（或容器内 pip install 后固化）。

docker-compose.yml：backend-dev 追加注释说明——pcap 渠道加 `cap_add: ["NET_RAW"]`（混杂监听加 NET_ADMIN）；snmp/netflow 渠道按需 ports 增加 `1162:1162/udp`、`2055:2055/udp`。

## 十四、关键风险与对策

1. **行为等价性**：阶段 1 验收基准=青藤样例重构前后三表逐字段一致，用固定样例 A/B 对比
2. **pysnmp 7.x API 变动大**：先独立单测验证收发再接 ctx
3. **pcap 高流量打满队列**：默认 batch 模式（50 包聚合）+ bpf_filter 限量，丢弃走既有窗口聚合
4. **水位并发回写**：单线程模型天然独占写 + 30s 节流
5. **端口唯一性**：UDP 类新源类型共用"bind:port 冲突=409"，复用 syslog 现有报错路径
6. **Windows 开发机**：scapy/Npcap 不支持时 `pytest.importorskip` 跳过；fcntl 等跨平台处理沿用现有先例

## 涉及关键文件

- backend/app/core/log_receiver_manager.py → log_receiver_manager/ 包（重构核心）
- backend/app/models/log_receiver.py（adapter_config 列、protocol 枚举扩展）
- backend/app/api/v1/log_receivers.py（schema/校验/序列化/端口唯一性）
- backend/app/core/security.py（run_lightweight_migrations 追加 ensure_columns）
- backend/requirements.txt（可选依赖）
- frontend/src/pages/devices/LogReceivers.jsx（SOURCE_TYPE_META 动态表单）
- backend/tests/（新增 test_collector_* 系列用例）
- **不动**：backend/app/engine/ 全部（ParseEngine/策略 JSON/规则引擎原样复用）、AlertEvent 等模型表
