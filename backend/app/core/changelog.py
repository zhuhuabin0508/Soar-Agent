"""系统版本与更新日志。

每次发布新版本时，**必须**：
1. 递增 ``CURRENT_VERSION``（语义化版本，如 ``1.2.0``）。
2. 在 ``CHANGELOG`` 列表**顶部**插入新版本的更新条目。

启动时 ``notify_system_update()`` 会对比数据库中是否已存在当前版本的通知，
若不存在则向全员广播一条 ``system_update`` 通知（通知中心可见），
通知内容为本版本的更新明细。这样每次系统更新重启后，用户都能在通知中心
看到本次更新做了什么。

版本号同时驱动 ``app.main.app`` 的 ``FastAPI(version=...)``，保持一致。
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 当前系统版本（每次发版递增）
CURRENT_VERSION = "1.3.0"

# 更新日志（新版本插在顶部）
CHANGELOG: list[dict] = [
    {
        "version": "1.3.0",
        "date": "2026-07-29",
        "title": f"系统更新 v{CURRENT_VERSION}",
        "items": [
            "修复智能体工具并行调用问题：强制 LLM 每轮只调用一个工具（parallel_tool_calls=False），确保按提示词定义的顺序执行（如先查资产信息，未命中再查威胁情报），不再并行查询",
            "已封禁 IP 支持手动新增封禁记录，并新增来源标识（手动添加 / 智能体添加），列表与详情中均可区分",
            "已封禁 IP 支持硬删除（从数据库彻底移除记录，不可恢复），与解封（逻辑删除）明确区分；硬删除需输入 IP 二次确认",
            "删除知识库时同步清理所有智能体对该知识库的引用，读取智能体时自动剔除已不存在的知识库引用，保证配置与数据库一致",
            "修复平台名称修改后左上角未同步更新问题：左上角改为动态读取系统设置中的平台名称，并去掉副标题小字",
        ],
    },
    {
        "version": "1.2.0",
        "date": "2026-07-27",
        "title": "系统更新 v1.2.0",
        "items": [
            "修复路由配置：迁移到 createBrowserRouter，解决智能体编排/编辑页面 useBlocker 报错",
            "修复执行追溯页 500 错误（智能体测试执行的 workflow_id 为空导致序列化失败）",
            "执行监测、执行追溯页新增工作流筛选，可按工作流查看运行数据；追溯页增加状态筛选与分页",
            "修复编辑页面「放弃修改并离开」后确认弹窗不消失、关不掉的问题",
            "模型设置页新增模型监控功能：可查看每个模型的调用次数、成功率、平均耗时、Token 用量及最近调用明细",
            "工具、知识库、技能、模型设置、设备对接页新增图文使用教程入口",
            "智能体教程同步更新：补充读取未分段文档（read_document）等新功能说明",
        ],
    },
    {
        "version": "1.1.0",
        "date": "2026-07-27",
        "title": "系统更新 v1.1.0",
        "items": [
            "工作流「AI 智能体」节点改为选择已创建的智能体，复用其模型/提示词/工具/知识库配置，支持输入输出映射",
            "编辑页面（智能体/工具/工作流）切换时增加未保存修改提示，避免误丢失",
            "进入对话页自动滚动到最新消息，从其他页面切回也不再停在顶部",
            "修复 Excel 工作表名被独立分成一段的问题，工作表名现作为字段跟随数据行",
            "系统监控记录用户所有写操作（登录/增删改/执行等），含操作模块、资源ID、IP地址",
            "系统监控/服务健康页支持查看各服务（backend/worker/postgres/redis 等）实时日志",
            "智能体新增 read_document / list_documents 工具，可直接读取对话中上传的未分段文档原文",
            "系统更新后通过通知中心自动推送本次更新明细",
        ],
    },
    {
        "version": "1.0.0",
        "date": "2026-07-01",
        "title": "系统初始版本 v1.0.0",
        "items": [
            "SOAR 安全运营平台初始发布",
        ],
    },
]


def get_current_changelog() -> Optional[dict]:
    """获取当前版本的更新条目。"""
    for c in CHANGELOG:
        if c["version"] == CURRENT_VERSION:
            return c
    return None


def _format_update_content(cl: dict) -> str:
    """把更新条目格式化为通知正文。"""
    lines = [f"版本：v{cl['version']}", f"发布日期：{cl['date']}", "", "更新内容："]
    for i, item in enumerate(cl["items"], 1):
        lines.append(f"{i}. {item}")
    return "\n".join(lines)


def notify_system_update(db) -> None:
    """系统启动时，若当前版本未通知过，向全员广播更新通知。

    通过查询 ``notifications`` 表是否已有同标题的 ``system_update`` 通知来判断
    是否已通知过，避免重复推送。失败不阻断启动。
    """
    try:
        from app.models.notification import Notification

        cl = get_current_changelog()
        if not cl:
            logger.warning("未找到当前版本 %s 的更新日志，跳过更新通知", CURRENT_VERSION)
            return

        # 已存在同标题的更新通知则跳过（避免重启重复推送）
        existing = (
            db.query(Notification)
            .filter(
                Notification.type == "system_update",
                Notification.title == cl["title"],
            )
            .first()
        )
        if existing:
            logger.info("当前版本 %s 的更新通知已存在（id=%s），跳过", CURRENT_VERSION, existing.id)
            return

        n = Notification(
            user_id=None,  # 全员广播
            type="system_update",
            title=cl["title"],
            content=_format_update_content(cl),
            related_type="system",
            created_by="system",
        )
        db.add(n)
        db.commit()
        logger.info("已推送系统更新通知: %s", cl["title"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("推送系统更新通知失败（不阻断启动）: %s", exc)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
