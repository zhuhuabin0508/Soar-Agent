"""端口镜像抓包输入适配器（scapy AsyncSniffer）。

每 IP 包提取五元组摘要；高流量默认 batch 模式（N 包聚合一条 JSONL 事件）
+ bpf_filter 限量，背压丢弃走既有窗口聚合告警。容器需 ``cap_add: NET_RAW``
（混杂模式另需 NET_ADMIN），Windows 开发机需 Npcap。

状态机：binding → listening / failed（权限不足明确提示）。
"""
import json
import logging
import threading
import time

from ..base_adapter import BaseAdapter
from ..registry import adapter_registry

logger = logging.getLogger(__name__)


@adapter_registry.register
class PcapAdapter(BaseAdapter):
    """端口镜像抓包适配器（scapy）。"""

    source_type = "pcap"
    display_name = "端口镜像抓包"
    default_ready_timeout_s = 3.0

    def run(self) -> None:
        receiver = self.ctx.receiver or {}
        cfg = receiver.get("adapter_config") or {}
        iface = (cfg.get("iface") or "").strip() or None  # None = 默认接口
        bpf = (cfg.get("bpf_filter") or "ip").strip() or "ip"
        emit_mode = (cfg.get("emit_mode") or "batch").lower()
        batch_size = max(1, int(cfg.get("batch_size") or 50))
        include_payload = bool(cfg.get("include_payload"))

        try:
            from scapy.sendrecv import AsyncSniffer  # noqa: F401
        except Exception as exc:  # noqa: BLE001
            msg = f"未安装 scapy 依赖（Windows 开发机另需 Npcap）: {exc}. 请 pip install scapy"
            self.ctx.mark_start_failed(msg)
            self.ctx.signal_ready(False, msg)
            return

        self.ctx.set_status("binding", None)
        self._batch: list[dict] = []
        self._batch_lock = threading.Lock()
        self._last_emit_ts = time.time()
        sniffer = None
        try:
            from scapy.sendrecv import AsyncSniffer

            sniffer = AsyncSniffer(
                iface=iface,
                filter=bpf,
                prn=self._on_packet,
                store=False,
            )
            sniffer.start()
            self.ctx.runtime_ref["sniffer"] = sniffer
            self.ctx.signal_ready(True)
            self.ctx.set_status("listening", None)
            logger.info(
                "pcap 抓包已启动: iface=%s filter=%s emit=%s (receiver=%s gen=%s)",
                iface or "<默认>", bpf, emit_mode, self.ctx.receiver_id, self.ctx.generation,
            )
            # 周期驱动：batch 模式的低流量兜底flush + 停止感知
            while not self.ctx.stop_event.is_set():
                self.ctx.stop_event.wait(1.0)
                if emit_mode == "batch":
                    self._flush_batch(force=False)
        except PermissionError as exc:
            msg = (
                f"抓包权限不足: {exc}. 容器部署请在 docker-compose.yml 为 backend 增加 "
                f"cap_add: [\"NET_RAW\"]（混杂监听另需 NET_ADMIN）；Windows 开发机需以管理员运行并安装 Npcap"
            )
            self.ctx.mark_start_failed(msg)
            self.ctx.signal_ready(False, msg)
            return
        except Exception as exc:  # noqa: BLE001
            if not self.ctx.stop_event.is_set():
                logger.exception("pcap 抓包启动失败: %s", exc)
                self.ctx.set_status("failed", f"{type(exc).__name__}: {exc}")
                self.ctx.signal_ready(False, f"{type(exc).__name__}: {exc}")
        finally:
            if sniffer is not None:
                try:
                    sniffer.stop()
                except Exception:  # noqa: BLE001
                    pass
            if emit_mode == "batch":
                self._flush_batch(force=True)
            if self.ctx.runtime_ref.get("sniffer") is sniffer:
                self.ctx.runtime_ref.pop("sniffer", None)

    # ------------------------------------------------------------------
    # 包回调（prn）：提取五元组摘要 → per_packet 直发 / batch 聚合
    # ------------------------------------------------------------------
    def _on_packet(self, pkt) -> None:
        try:
            cfg = self.ctx.receiver.get("adapter_config") or {}
            rec = self._summarize(pkt, include_payload=bool(cfg.get("include_payload")))
        except Exception:  # noqa: BLE001
            return  # 非预期包结构：丢弃
        if rec is None:
            return
        emit_mode = str((cfg.get("emit_mode") or "batch")).lower()
        if emit_mode == "per_packet":
            self._publish_batch([rec])
            return
        with self._batch_lock:
            self._batch.append(rec)
            should_flush = len(self._batch) >= self._batch_size()
        if should_flush:
            self._flush_batch(force=True)

    def _batch_size(self) -> int:
        try:
            return max(1, int((self.ctx.receiver.get("adapter_config") or {}).get("batch_size") or 50))
        except Exception:  # noqa: BLE001
            return 50

    @staticmethod
    def _summarize(pkt, include_payload: bool = False) -> dict | None:
        """IP 包 → {ts, src, dst, proto, sport, dport, len, tcp_flags[, payload_hex]}。"""
        from scapy.layers.inet import IP, TCP, UDP

        if IP not in pkt:
            return None
        ip = pkt[IP]
        rec = {
            "pcap": True,
            "ts": round(float(pkt.time), 6),
            "src_ip": ip.src,
            "dst_ip": ip.dst,
            "protocol": ip.proto,
            "length": len(pkt),
        }
        if TCP in pkt:
            rec["src_port"] = pkt[TCP].sport
            rec["dst_port"] = pkt[TCP].dport
            rec["tcp_flags"] = str(pkt[TCP].flags)
        elif UDP in pkt:
            rec["src_port"] = pkt[UDP].sport
            rec["dst_port"] = pkt[UDP].dport
        if include_payload:
            payload = bytes(ip.payload)[:64]  # 截断防大字段
            if payload:
                rec["payload_hex"] = payload.hex()
        return rec

    def _flush_batch(self, force: bool) -> None:
        """批量模式下聚合发射（低流量 5s 兜底，避免长时间不出事件）。"""
        with self._batch_lock:
            if not self._batch:
                return
            due = (time.time() - self._last_emit_ts) >= 5.0
            if not force and not due:
                return
            batch, self._batch = self._batch, []
        self._last_emit_ts = time.time()
        if batch:
            self._publish_batch(batch)

    def _publish_batch(self, records: list[dict]) -> None:
        """一批事件 → 一条 JSONL（逐行 JSON）入总线（队列满丢弃走窗口聚合）。"""
        payload = "\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in records)
        self.ctx.publish(payload, source_ip=None, meta={"packet_count": len(records)})

    def stop(self) -> None:
        """置位 stop_event 并停止 sniffer（主循环随后收尾 flush）。"""
        self.ctx.stop_event.set()
        sniffer = self.ctx.runtime_ref.get("sniffer")
        if sniffer is not None:
            try:
                sniffer.stop()
            except Exception:  # noqa: BLE001
                pass
