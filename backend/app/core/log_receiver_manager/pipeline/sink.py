"""ReceiverSink：接收明细与接收指标持久化（自原 log_receiver_manager.py 平移）。

职责：
- ``record_raw_received``：写 device_receive_logs（received）+ total 指标 +
  log_receivers.received_count（独立会话，避免长事务）；
- ``record_parsed``：写解析结果明细（success/partial/fail）+ 对应指标，
  fail 时累计渠道 error_count（``_bump_counts`` 一并迁入本模块，
  因其唯一调用方即本类，原模块级位置无其他引用）。
"""
import json
import logging
from typing import Optional

from app.core.timezone import beijing_now
from app.database import SessionLocal

logger = logging.getLogger(__name__)

# 大值摘要阈值（字符）：超过该长度则不再原样入库，改为存储 长度+sha256+前 N 字预览，
# 避免超大 JSON/日志撑爆 device_receive_logs.raw_data（Text 上限）。
_SUMMARIZE_THRESHOLD = 4000
# 解析后字段 JSON 的摘要阈值：结构化字段是「解析结果」面板的展示数据，需完整入库
# （PG Text 列可承载 MB 级），仅对异常超大负载（>256KB）做摘要兜底。
_PARSED_FIELDS_SUMMARIZE_THRESHOLD = 262144
# 大值摘要时保留的预览字符数
_SUMMARIZE_PREVIEW = 512


def _serialize_parsed_fields(fields: Optional[dict]) -> Optional[str]:
    """解析后的标准模型字段序列化为 JSON 文本（超限走大值摘要），供详情页展示。"""
    if not fields:
        return None
    try:
        s = json.dumps(fields, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        return None
    if len(s) <= _PARSED_FIELDS_SUMMARIZE_THRESHOLD:
        return s
    return _summarize_large_value(s)


def _summarize_large_value(raw: str) -> str:
    """超限原始日志转为摘要：长度 + sha256 + 预览，便于定位与校验原文完整性。"""
    import hashlib

    digest = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()
    return "".join([
        f"[大值摘要] 原始长度={len(raw)} sha256={digest}\n",
        f"--- 前 {_SUMMARIZE_PREVIEW} 字符预览 ---\n",
        raw[:_SUMMARIZE_PREVIEW],
    ])


def _bump_counts(receiver_id: int, received: int = 0, errors: int = 0) -> None:
    """累计渠道接收/异常计数（独立短会话）。"""
    db = SessionLocal()
    try:
        from sqlalchemy import text as sa_text

        sql = sa_text(
            """
            UPDATE log_receivers
            SET received_count = received_count + :rc,
                error_count = error_count + :ec,
                last_received_at = :now
            WHERE id = :rid
            """
        )
        db.execute(sql, {"rc": received, "ec": errors, "rid": receiver_id, "now": beijing_now()})
        db.commit()
    finally:
        db.close()


class ReceiverSink:
    """把接收到的日志写入 device_receive_logs + 记录接收指标。

    实际解析入库复用 ingest.SQLAlchemySink（写入 alert_events 并触发封禁）。
    每个调用传入独立的 db 会话，适合在后台线程中使用。
    """

    def __init__(self, db, receiver: dict, source_ip: Optional[str] = None) -> None:
        self.db = db
        self.receiver_id = receiver.get("id")
        self.device_id = receiver.get("device_id")
        self.device_name = receiver.get("device_name") or ""
        self.protocol = receiver.get("protocol") or "syslog"
        self.receiver_name = receiver.get("name") or ""
        self.source_ip = source_ip

    def _record_receive_log(
        self, raw_data: str, parse_status: str, parse_error: str = "",
        alert_id: Optional[int] = None,
        strategy_id: Optional[int] = None, strategy_name: str = "",
        rule_id: str = "", log_type: str = "",
        parsed_fields: Optional[dict] = None,
    ) -> None:
        from app.models.log_receiver import DeviceReceiveLog

        rec = DeviceReceiveLog(
            receiver_id=self.receiver_id,
            device_id=self.device_id,
            device_name=self.device_name,
            protocol=self.protocol,
            raw_data=raw_data if len(raw_data) <= _SUMMARIZE_THRESHOLD else _summarize_large_value(raw_data),
            source_ip=self.source_ip,
            parse_status=parse_status,
            parse_error=parse_error[:2000] if parse_error else "",
            alert_id=alert_id,
            strategy_id=strategy_id,
            strategy_name=strategy_name or "",
            rule_id=rule_id or "",
            log_type=log_type or "",
            parsed_fields=_serialize_parsed_fields(parsed_fields),
        )
        self.db.add(rec)

    def _record_receive_metric(self, status: str) -> None:
        """按小时原子累加接收指标（INSERT ... ON CONFLICT upsert，并发安全）。"""
        from sqlalchemy import text as sa_text

        stat_hour = beijing_now().strftime("%Y-%m-%dT%H")
        col = "fail_count" if status == "unknown" else f"{status}_count"
        sql = sa_text(
            """
            INSERT INTO device_receive_metrics
                (stat_hour, receiver_id, receiver_name, device_id, protocol,
                 total_count, success_count, partial_count, fail_count, updated_at)
            VALUES (:hour, :rid, :rname, :did, :proto, 1, :s, :p, :f, :now)
            ON CONFLICT (stat_hour, receiver_id) DO UPDATE
            SET {col} = device_receive_metrics.{col} + 1,
                receiver_name = EXCLUDED.receiver_name,
                updated_at = EXCLUDED.updated_at
            """.format(col=col)
        )
        self.db.execute(
            sql,
            {
                "hour": stat_hour,
                "rid": self.receiver_id,
                "rname": self.receiver_name,
                "did": self.device_id,
                "proto": self.protocol,
                "s": 1 if status == "success" else 0,
                "p": 1 if status == "partial" else 0,
                "f": 1 if status in ("fail", "unknown") else 0,
                "now": beijing_now(),
            },
        )

    def record_raw_received(self, raw_data: str) -> None:
        """仅记录接收明细 + 指标（未进入解析）。"""
        from sqlalchemy import text as sa_text

        self._record_receive_log(raw_data, "received")
        # 计入 total 与 log_receivers.received_count（upsert，并发安全）
        stat_hour = beijing_now().strftime("%Y-%m-%dT%H")
        sql = sa_text(
            """
            INSERT INTO device_receive_metrics
                (stat_hour, receiver_id, receiver_name, device_id, protocol,
                 total_count, success_count, partial_count, fail_count, updated_at)
            VALUES (:hour, :rid, :rname, :did, :proto, 1, 0, 0, 0, :now)
            ON CONFLICT (stat_hour, receiver_id) DO UPDATE
            SET total_count = device_receive_metrics.total_count + 1,
                receiver_name = EXCLUDED.receiver_name,
                updated_at = EXCLUDED.updated_at
            """
        )
        self.db.execute(sql, {"rname": self.receiver_name, "hour": stat_hour,
                              "rid": self.receiver_id, "did": self.device_id,
                              "proto": self.protocol, "now": beijing_now()})
        db2 = SessionLocal()
        try:
            from sqlalchemy import text as t2

            db2.execute(
                t2(
                    """
                    UPDATE log_receivers
                    SET received_count = received_count + 1, last_received_at = :now
                    WHERE id = :rid
                    """
                ),
                {"rid": self.receiver_id, "now": beijing_now()},
            )
            db2.commit()
        finally:
            db2.close()

    def record_parsed(
        self, raw_data: str, parse_status: str, parse_error: str = "",
        alert_id: Optional[int] = None,
        strategy_id: Optional[int] = None, strategy_name: str = "",
        rule_id: str = "", log_type: str = "",
        parsed_fields: Optional[dict] = None,
    ) -> None:
        """记录解析结果（success/partial/fail/unknown）+ 对应指标。

        unknown（类型识别与路由失败，已进 unknown 兜底队列）：接收明细状态
        记 unknown 便于筛选排查；指标表无 unknown 列，按 fail 口径累计。
        strategy_id/strategy_name/rule_id/log_type/parsed_fields：解析命中信息，
        写入明细行供数据源条目详情「解析结果」面板展示命中的模板/规则与解析后内容。
        """
        self._record_receive_log(
            raw_data, parse_status, parse_error, alert_id,
            strategy_id=strategy_id, strategy_name=strategy_name,
            rule_id=rule_id, log_type=log_type,
            parsed_fields=parsed_fields,
        )
        self._record_receive_metric("fail" if parse_status == "unknown" else parse_status)
        if parse_status in ("fail", "unknown"):
            _bump_counts(self.receiver_id, errors=1)
