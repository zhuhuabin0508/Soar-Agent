"""拉取类适配器（file_tail/rest_api/jdbc）的公共件：游标（水位）存取。

水位语义：
- 内存快照（state._runtime_receiver）即时更新，保证"运行中回写 → 重启前
  仍可读到"（start_receiver_sync 强制刷新 DB 例外，见下）；
- DB ``log_receivers.adapter_config`` JSON 列节流回写（30 秒或游标变化才
  UPDATE），避免高频写库；用户保存配置会整体覆盖 adapter_config，即
  "保存即重置游标"，属预期行为。

键约定：``_cursor`` 为运行时水位键（下划线前缀避免与用户配置项冲突），
值必须 JSON 可序列化（标量或 dict）。
"""
import json
import logging
import time

logger = logging.getLogger(__name__)

# 运行时水位在 adapter_config 中的键（下划线前缀 = 运行时状态，非用户配置）
CURSOR_KEY = "_cursor"
# 水位回写 DB 的最小间隔（秒）
CURSOR_FLUSH_INTERVAL_S = 30.0


class CursorStore:
    """某接收渠道的轮询游标（水位）读写句柄（仅监听线程单线程使用）。"""

    def __init__(self, ctx) -> None:
        self.ctx = ctx
        self._last_flush_ts: float = 0.0
        self._last_flush_value = None

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------
    def load(self):
        """读取当前水位（无则 None）。优先内存快照，退回启动快照。"""
        receiver = self.ctx.receiver or {}
        cfg = receiver.get("adapter_config") or {}
        try:
            return cfg.get(CURSOR_KEY)
        except AttributeError:  # cfg 非 dict（防御）
            return None

    # ------------------------------------------------------------------
    # 写入（内存即时 + DB 节流）
    # ------------------------------------------------------------------
    def save(self, value, force: bool = False) -> None:
        """更新水位：内存快照即时生效，DB 30 秒节流回写。

        force=True 跳过节流立即落库（stop 前收尾可调用）。
        """
        # 1) 内存快照即时更新（publish 用的 receiver dict 同源）
        try:
            receiver = self.ctx.receiver or {}
            cfg = receiver.setdefault("adapter_config", {})
            if isinstance(cfg, dict):
                cfg[CURSOR_KEY] = value
        except Exception:  # noqa: BLE001
            logger.exception("游标内存更新异常（忽略）")

        # 2) DB 节流回写
        now = time.time()
        if not force:
            if value == self._last_flush_value:
                return  # 值未变化不写
            if now - self._last_flush_ts < CURSOR_FLUSH_INTERVAL_S:
                return  # 未到节流窗口
        self._flush_to_db(value)
        self._last_flush_ts = now
        self._last_flush_value = value

    def flush_now(self) -> None:
        """立即把当前内存水位落库（供 stop() 收尾调用）。"""
        value = self.load()
        self._flush_to_db(value)
        self._last_flush_ts = time.time()
        self._last_flush_value = value

    def _flush_to_db(self, value) -> None:
        """把水位合并进 DB 行的 adapter_config（保留其他运行时键与用户配置）。"""
        receiver_id = self.ctx.receiver_id
        try:
            from app.database import SessionLocal
            from app.models.log_receiver import LogReceiver

            db = SessionLocal()
            try:
                rec = db.query(LogReceiver).filter(LogReceiver.id == receiver_id).first()
                if rec is None:
                    return
                try:
                    cfg = json.loads(rec.adapter_config or "{}")
                except (ValueError, TypeError):
                    cfg = {}
                if not isinstance(cfg, dict):
                    cfg = {}
                cfg[CURSOR_KEY] = value
                rec.adapter_config = json.dumps(cfg, ensure_ascii=False)
                db.commit()
            finally:
                db.close()
        except Exception:  # noqa: BLE001
            # 水位回写失败不影响采集主流程（下一窗口重试）
            logger.exception("游标回写 DB 异常（忽略）: receiver=%s", receiver_id)
