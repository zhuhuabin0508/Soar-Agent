"""解析策略模型。

一个策略描述一种设备/数据源的告警日志格式，以 JSON 存储。
新增设备时只需创建新策略，不需要修改引擎代码。

草稿/发布机制：
- ``config`` 始终是线上生效版本（引擎 StrategyLoader 只读它，零影响）；
- ``draft_config`` 为编辑中的草稿副本（NULL=无草稿，非 NULL=存在草稿），
  编辑已发布模板时写入草稿，测试通过后「发布」替换线上版本；
- ``published_version_no`` 对应 parse_strategy_versions.version_no 快照。
  ``status`` 保持 enabled/disabled 启停语义，与草稿/发布正交。
"""
from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint

from app.core.timezone import beijing_now
from app.database import Base


class ParseStrategy(Base):
    """解析策略配置。"""

    __tablename__ = "parse_strategies"

    id = Column(Integer, primary_key=True, index=True)
    strategy_name = Column(String(255), nullable=False, comment="策略名称")
    device_type = Column(String(64), default="", index=True, comment="设备类型标识")
    version = Column(String(32), default="1.0", comment="策略版本")
    status = Column(String(16), default="enabled", index=True, comment="enabled/disabled")
    config = Column(Text, nullable=False, comment="策略配置 JSON 全文（线上生效版本）")
    draft_config = Column(Text, nullable=True, comment="草稿副本 JSON（NULL=无草稿；有草稿时编辑不生效）")
    published_version_no = Column(Integer, nullable=True, comment="当前线上版本号（对应版本快照表）")
    created_at = Column(DateTime, default=beijing_now)
    updated_at = Column(DateTime, default=beijing_now, onupdate=beijing_now)

    def __repr__(self):
        return f"<ParseStrategy id={self.id} name={self.strategy_name!r} v={self.version!r}>"


class ParseStrategyVersion(Base):
    """解析模板版本快照（发布/回滚时生成，线上版本历史）。"""

    __tablename__ = "parse_strategy_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_id = Column(Integer, nullable=False, index=True, comment="所属模板 ID")
    version_no = Column(Integer, nullable=False, comment="版本号（同一模板内递增）")
    config = Column(Text, nullable=False, comment="该版本的模板配置 JSON 全文")
    published_by = Column(String(64), nullable=False, default="", comment="发布人（用户名）")
    published_at = Column(DateTime, default=beijing_now, comment="发布时间")
    remark = Column(String(512), nullable=False, default="", comment="版本说明（发布/回滚备注）")

    __table_args__ = (
        UniqueConstraint("strategy_id", "version_no", name="uq_parse_strategy_version_no"),
    )

    def __repr__(self):
        return f"<ParseStrategyVersion id={self.id} strategy={self.strategy_id} v{self.version_no}>"
