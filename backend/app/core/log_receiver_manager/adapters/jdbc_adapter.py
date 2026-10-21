"""JDBC/数据库拉取输入适配器（SQLAlchemy 轮询 + 水位）。

按配置周期执行 query（可含 :since 命名占位绑定当前水位），结果行转
JSON 逐条 publish；cursor_column（默认取结果首列）作为水位推进依据，
持久化到 adapter_config（_cursor），重启后从上次位置继续拉取。

状态机：connecting → running / failed；publish 失败不推进水位，下轮
重拉该批（数据库采集不丢数据）。
"""
import logging
from datetime import date, datetime

from ..base_adapter import BaseAdapter
from ..registry import adapter_registry
from ._polling import CursorStore

logger = logging.getLogger(__name__)


def _row_value(v):
    """行值 JSON 序列化（datetime/date → ISO 文本，其余原样）。"""
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray)):
        try:
            return bytes(v).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            return repr(v)
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    return str(v)


@adapter_registry.register
class JdbcAdapter(BaseAdapter):
    """数据库轮询拉取适配器（SQLAlchemy 连接串）。"""

    source_type = "jdbc"
    display_name = "数据库拉取"
    default_ready_timeout_s = 8.0  # 首连需要网络往返
    required_config_keys = [
        ("url", "数据库连接串（SQLAlchemy URL）"),
        ("query", "查询 SQL（可含 :since 占位）"),
    ]

    def run(self) -> None:
        receiver = self.ctx.receiver or {}
        cfg = receiver.get("adapter_config") or {}
        url = (cfg.get("url") or "").strip()
        query = (cfg.get("query") or "").strip()
        if not url or not query:
            self.ctx.mark_start_failed("未配置数据库连接串或查询 SQL（adapter_config.url / query）")
            self.ctx.signal_ready(False, "未配置数据库连接串或查询 SQL")
            return

        self._cursor = CursorStore(self.ctx)
        initial_cursor = cfg.get("initial_cursor")

        self.ctx.set_status("connecting", None)
        engine = None
        try:
            from sqlalchemy import create_engine, text

            # 连接失败同步报错（供保存接口实时反馈）
            engine = create_engine(url, pool_pre_ping=True, future=True)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001
            msg = f"数据库连接失败: {type(exc).__name__}: {exc}"
            self.ctx.mark_start_failed(msg)
            self.ctx.signal_ready(False, msg)
            return

        self.ctx.signal_ready(True)
        self.ctx.set_status("running", None)
        logger.info(
            "jdbc 拉取已启动 (receiver=%s gen=%s)", self.ctx.receiver_id, self.ctx.generation,
        )

        # 水位初始化：_cursor 已有值 > initial_cursor（latest=查 MAX / earliest=0 / 显式值）
        cursor_value = self._cursor.load()
        if cursor_value is None:
            cursor_value = self._resolve_initial_cursor(cfg, engine)
            self._cursor.save(cursor_value, force=True)

        interval = max(1.0, float(cfg.get("poll_interval_seconds") or 10))
        batch_size = max(1, int(cfg.get("batch_size") or 1000))
        cursor_column = (cfg.get("cursor_column") or "").strip() or None

        while not self.ctx.stop_event.is_set():
            try:
                cursor_value = self._poll_once(cfg, engine, query, cursor_value, batch_size, cursor_column)
            except Exception as exc:  # noqa: BLE001
                logger.exception("jdbc 轮询异常（忽略本轮）: %s", exc)
            self.ctx.stop_event.wait(interval)

        try:
            engine.dispose()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # 水位初始化
    # ------------------------------------------------------------------
    def _resolve_initial_cursor(self, cfg: dict, engine):
        """initial_cursor: latest（当前最大值，跳过存量）/ earliest（0 从头）/ 显式值。"""
        initial = cfg.get("initial_cursor")
        if initial in (None, "", "earliest"):
            return 0
        if initial == "latest":
            cursor_column = (cfg.get("cursor_column") or "").strip()
            if not cursor_column:
                return None  # 无水位列且 latest：退化为"不拉存量"（首轮空水位全量）
            try:
                from sqlalchemy import text

                with engine.connect() as conn:
                    row = conn.execute(
                        text(f"SELECT MAX({cursor_column}) FROM ({cfg.get('query')}) AS _soar_sub")
                    ).fetchone()
                return row[0] if row and row[0] is not None else 0
            except Exception:  # noqa: BLE001
                logger.exception("jdbc 水位初始化（latest）失败，退化为 0")
                return 0
        return initial

    # ------------------------------------------------------------------
    # 单轮拉取
    # ------------------------------------------------------------------
    def _poll_once(self, cfg, engine, query: str, cursor_value, batch_size: int, cursor_column):
        import json

        from sqlalchemy import text

        stmt = text(query)
        params = {}
        if ":since" in query and cursor_value is not None:
            params["since"] = cursor_value
        if ":limit" in query:
            params["limit"] = batch_size

        with engine.connect() as conn:
            result = conn.execute(stmt, params) if params else conn.execute(stmt)
            cols = list(result.keys())
            rows = result.fetchmany(batch_size)

        last_cursor = cursor_value
        for row in rows:
            rec = {col: _row_value(val) for col, val in zip(cols, row)}
            # 水位列：显式 cursor_column > 约定 cursor 字段 > 首列
            if cursor_column and cursor_column in rec:
                last_cursor = rec[cursor_column]
            elif "cursor" in rec:
                last_cursor = rec["cursor"]
            elif cols:
                last_cursor = rec[cols[0]]
            ok = self.ctx.publish(
                json.dumps(rec, ensure_ascii=False, default=str),
                source_ip=None, blocking=True, timeout=5.0,
            )
            if not ok:
                # 总线满：不推进水位，下轮重拉本批
                return cursor_value
        if rows and last_cursor != cursor_value:
            self._cursor.save(last_cursor)  # 节流回写 DB
            return last_cursor
        return cursor_value

    def stop(self) -> None:
        """停止前把水位落库。"""
        self.ctx.stop_event.set()
        cursor = getattr(self, "_cursor", None)
        if cursor is not None:
            try:
                cursor.flush_now()
            except Exception:  # noqa: BLE001
                pass
