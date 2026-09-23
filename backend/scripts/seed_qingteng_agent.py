"""青藤智能体播种脚本：幂等创建 qingteng Skill + Agent 并绑定工具。

用法（在 backend 目录下，需已安装 backend 依赖 + 可连数据库）:
    python -m scripts.seed_qingteng_agent

逻辑:
  1. 创建/更新 Skill(name=qingteng)，content 提炼自 qingteng_skill 完整包 SKILL.md
     （语义路由 / 时间规范 / 直连模式 / 安全纪律 / 业务组映射 / 风险导出）。
  2. 创建/更新 Agent(name=青藤安全助手)，enabled_skills 绑定 qingteng skill，
     enabled_tools 绑定 qingteng_* 工具（工具由 ensure_preset_tools 自动同步，
     见 app/core/tools/catalog.py 的 qingteng_definitions）。
  3. model_config_id 取第一个可用 LLMConfig；无则留空（需后在平台 UI 配置）。
"""
import logging

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.agent import Agent
from app.models.llm_config import LLMConfig
from app.models.skill import Skill

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("seed_qingteng")

_SKILL_NAME = "qingteng"
_AGENT_NAME = "青藤安全助手"

_QINGTENG_TOOLS = [
    "qingteng_login", "qingteng_query", "qingteng_post",
    "qingteng_assets", "qingteng_detect", "qingteng_risk",
    "qingteng_vul_check", "qingteng_baseline", "qingteng_system_audit",
    "qingteng_microseg", "qingteng_export_all",
]

_SKILL_CONTENT = """你是青藤云安全平台（主机安全/入侵检测/风险治理/合规基线/系统审计/微隔离）的操作引擎。所有青藤相关任务必须先完成模式与模块判断，再调用 qingteng_* 工具。

【语义路由】用户关键词 → 目标工具：
- 主机资产/进程/账号/端口/网站/数据库/安装包 → qingteng_assets
- 可疑操作/暴力破解/异常登录/WebShell/后门/蜜罐 → qingteng_detect
- 补丁/风险/弱密码/风险文件/漏洞扫描/作业管理 → qingteng_risk
- 合规基线/基线检查/授权/基线任务 → qingteng_baseline
- 系统审计/谁改了配置/谁执行了操作 → qingteng_system_audit
- 快速体检/快速风险扫描 → qingteng_vul_check
- 微隔离/网络隔离策略 → qingteng_microseg（高风险）

【操作模式】本平台采用「直连 API 模式」：通过注入的 qingteng_* 函数直连青藤 v3 External API（签名协议）。
- device 参数：gongwuyun（政务云，https://10.132.0.9）/ baremetal（裸金属，http://10.223.132.25/）/ apptjd（应用推进处，**必须 https**://szh-qhsds.sz.gov.cn）
- 登录 POST {base}/v1/api/auth → signKey/jwt/comId；GET 签名 sha1(comId+按key排序的key+value拼接+timestamp+signKey)；POST 签名 sha1(comId+body_json+timestamp+signKey)；请求头 comId/timestamp/sign/Authorization: Bearer jwt
- 真实路径（同 qingteng handler）：
  * 资产列表 GET /external/api/assets/{resource}/{os_type}（resource∈host/container/vm）
  * 弱密码 GET /external/api/vul/weakpwd/{os_type}/list
  * 风险列表 GET /external/api/vul/{risk_type}/{os_type}/list
  * 补丁 GET /external/api/vul/patch/{os_type}/list
  * 弱文件 GET /external/api/websecurity/weakfile/{os_type}
  * POC GET /external/api/vul/poc/{os_type}/list

【时间字段规范】
- 查询参数 time_range/begin_time/end_time 必须动态计算，禁止硬编码/自然语言脑补；DateRange 格式：yyyy-MM-dd HH:mm:ss - yyyy-MM-dd HH:mm:ss
- 返回结果：字段名含 time/Time 且文档标注 Integer(10)（logTime/loginTime/modifyTime/createTime/eventTime 等）按 Unix 秒级时间戳处理；需要可读时间时转换并保留原始值，标注时区 Asia/Shanghai UTC+8

【安全纪律】
- 高风险写操作（刷新/删除/封停/扫描任务/基线任务/微隔离策略变更）必须二次确认，用户未明确要求时不执行
- 登录失败先测连通性；查询类与任务类动作严格区分，默认仅用只读查询能力
- 分页返回结构：assets 分页 data 是 {rows:[...], total:N, ...}，字段用 rows 不是 list/data/records

【业务组映射】
- 政务云：查表映射（88 条，如 鹏城靶场 → (安全管理中心, 鹏城靶场)）
- 应用推进处：'关键绩效调度信息系统' 保持原值，其余统一 (应用推进处, 一网统管)
- 裸金属：部门固定 '安全管理中心'，业务组保持原值
- 所有 bizGroup 匹配前去除直引号和弯引号（归一化键后再查映射）

【弱密码详情字段】（GET /external/api/vul/weakpwd/{os_type}/{id}）
- 账号=uname；漏洞名=vulName；应用=app；端口=port；描述=desc；密码=password
- 弱密码类型=weakType（整数枚举：1=空密码、2=弱口令、3=默认密码、4=通用口令、6=明文口令）
- 绑定IP=bindIp；进程PID=pid；版本=version；路径=binPath；列表接口无账号/端口，需逐条调详情

【风险导出 Excel 后处理】
- 「风险详情」列是 JSON 字符串，需展开为独立列（用平台注入的 load_excel_workbook/find_col/save_workbook_as_agent_file/DEFAULT_RISK_COLUMNS 实现）
- 弱口令 22 字段白名单精简走 canonical 流程
- 用户只甩一行数据样例时，必须先确认源文件完整路径，不臆测/盲搜

【任务归属】青藤平台相关技术操作默认归属网络架构列表；仅交付协调/签收/汇报归属交付列表。
"""


def _upsert_skill(db: Session) -> int:
    skill = db.query(Skill).filter(Skill.name == _SKILL_NAME).first()
    if skill is None:
        skill = Skill(
            name=_SKILL_NAME,
            description="青藤云安全平台综合操作技能（资产/入侵检测/风险/基线/系统审计/漏洞/微隔离）",
            content=_SKILL_CONTENT,
            category="领域规则",
            tags=["青藤", "qingteng", "安全", "资产", "风险管理"],
            enabled=True,
            priority=10,
        )
        db.add(skill)
        db.flush()
        logger.info("Skill 已创建: id=%s name=%s", skill.id, skill.name)
        return skill.id
    if skill.content != _SKILL_CONTENT:
        skill.content = _SKILL_CONTENT
        logger.info("Skill 已更新 content: name=%s", skill.name)
    return skill.id


def _first_llm_config(db: Session):
    return db.query(LLMConfig).order_by(LLMConfig.id.asc()).first()


def _upsert_agent(db: Session, skill_id: int) -> None:
    llm_cfg = _first_llm_config(db)
    agent = db.query(Agent).filter(Agent.name == _AGENT_NAME).first()
    data = dict(
        description="青藤云安全分析助手：资产盘点、入侵检测、风险治理、基线合规、系统审计、微隔离查询。",
        model_config_id=llm_cfg.id if llm_cfg else None,
        system_prompt=(
            "你是青藤云安全平台的分析助手。严格遵循注入的 qingteng skill 语义路由，"
            "先判断用户意图对应模块，再调用对应 qingteng_* 工具查询；"
            "只读优先，高风险写操作必须向用户二次确认。结果用中文清晰汇总。"
        ),
        enabled_tools=_QINGTENG_TOOLS + ["expand_risk_detail"],
        enabled_skills=[skill_id],
        enabled_kbs=[],
        enabled_asset_types=[],
        engine="hermes",
        temperature=0.3,
        max_tokens=2048,
        max_iterations=5,
        enable_memory=False,
        tone_style="professional",
    )
    if agent is None:
        agent = Agent(name=_AGENT_NAME, **data)
        db.add(agent)
        logger.info("Agent 已创建: name=%s", _AGENT_NAME)
        return
    for k, v in data.items():
        setattr(agent, k, v)
    logger.info("Agent 已更新: name=%s", _AGENT_NAME)


def main() -> None:
    db: Session = SessionLocal()
    try:
        skill_id = _upsert_skill(db)
        _upsert_agent(db, skill_id)
        db.commit()
        logger.info("播种完成。qingteng 工具已由 ensure_preset_tools 同步为 DB 记录。")
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("播种失败: %s", exc)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
