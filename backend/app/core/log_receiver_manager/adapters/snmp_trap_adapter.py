"""SNMP Trap 输入适配器（pysnmp asyncio dispatcher 收 v1/v2c/v3 trap）。

varbinds 转 {oid: value} JSON 逐条 publish；pysnmp 未安装或 API 不兼容时
渠道标记 start_failed 给出安装提示。解析异常单包吞掉（不影响后续 trap）。

状态机：binding → listening / failed（默认端口 1162，避免特权端口 162）。
"""
import logging

from ..base_adapter import BaseAdapter
from ..registry import adapter_registry

logger = logging.getLogger(__name__)


@adapter_registry.register
class SnmpTrapAdapter(BaseAdapter):
    """SNMP Trap 接收适配器。"""

    source_type = "snmp_trap"
    display_name = "SNMP Trap 接收"
    default_ready_timeout_s = 3.0

    def run(self) -> None:
        receiver = self.ctx.receiver or {}
        cfg = receiver.get("adapter_config") or {}
        bind = (cfg.get("bind") or "0.0.0.0").strip() or "0.0.0.0"
        try:
            port = int(cfg.get("port") or 1162)
        except (ValueError, TypeError):
            port = 1162

        try:
            from pysnmp.carrier.asyncio.dispatcher import AsyncioDispatcher
            from pysnmp.carrier.asyncio.dgram import udp
        except Exception as exc:  # noqa: BLE001
            msg = f"未安装 pysnmp 依赖，无法接收 SNMP Trap: {exc}. 请 pip install pysnmp"
            self.ctx.mark_start_failed(msg)
            self.ctx.signal_ready(False, msg)
            return

        self.ctx.set_status("binding", None)
        dispatcher = None
        try:
            transport = udp.UdpTransport().openServerMode((bind, port))
            dispatcher = AsyncioDispatcher()
            dispatcher.registerTransport(udp.domainName, transport)
            dispatcher.registerRecvCbName(self._on_trap)
            dispatcher.jobStarted(1)
            self.ctx.runtime_ref["snmp_dispatcher"] = dispatcher
            self.ctx.signal_ready(True)
            self.ctx.set_status("listening", None)
            logger.info(
                "snmp_trap 监听已启动: %s:%s (receiver=%s gen=%s)",
                bind, port, self.ctx.receiver_id, self.ctx.generation,
            )
            dispatcher.runDispatcher()  # 阻塞直至 closeDispatcher
        except OSError as exc:
            msg = f"SNMP 端口绑定失败 {bind}:{port}: {exc}"
            self.ctx.mark_start_failed(msg)
            self.ctx.signal_ready(False, msg)
            return
        except Exception as exc:  # noqa: BLE001
            if not self.ctx.stop_event.is_set():
                logger.exception("snmp_trap 监听异常: %s", exc)
                self.ctx.set_status("failed", f"{type(exc).__name__}: {exc}")
                self.ctx.signal_ready(False, f"{type(exc).__name__}: {exc}")
        finally:
            self._close_dispatcher(dispatcher)
            if self.ctx.runtime_ref.get("snmp_dispatcher") is dispatcher:
                self.ctx.runtime_ref.pop("snmp_dispatcher", None)

    # ------------------------------------------------------------------
    # trap 回调：varbinds → JSON 事件
    # ------------------------------------------------------------------
    def _on_trap(self, dispatcher, transport_domain, transport_address, whole_msg):
        """pysnmp 收包回调：解析 varbinds 逐条 publish，返回 wholeMsg。"""
        import json

        source_ip = transport_address[0] if transport_address else None
        try:
            varbinds = self._parse_varbinds(whole_msg)
            if varbinds is not None:
                payload = {
                    "snmp_trap": True,
                    "source": source_ip,
                    "varbinds": varbinds,
                }
                self.ctx.publish(
                    json.dumps(payload, ensure_ascii=False, default=str),
                    source_ip=source_ip,
                    meta={"oid_count": len(varbinds)},
                )
                return whole_msg
        except Exception:  # noqa: BLE001
            logger.exception("snmp_trap 解析异常（忽略该包）")
        # 兜底：解析失败也留痕（hex），保证事件可追溯
        try:
            payload = {
                "snmp_trap": True,
                "source": source_ip,
                "raw_hex": whole_msg.hex() if whole_msg else "",
            }
            self.ctx.publish(json.dumps(payload, ensure_ascii=False), source_ip=source_ip)
        except Exception:  # noqa: BLE001
            logger.exception("snmp_trap 兜底入队异常（忽略）")
        return whole_msg

    @staticmethod
    def _parse_varbinds(whole_msg):
        """解析 SNMP 消息的 varbinds 列表为 [{oid, value}, ...]。

        pysnmp 7.x proto API 与 4.x 基本兼容；任何版本差异导致的异常由
        调用方兜底为 raw_hex 事件。
        """
        from pysnmp.proto import api as snmp_api
        from pyasn1.codec.ber import decoder

        rest = whole_msg
        while rest:
            msg_ver = int(rest[0])
            api = snmp_api.protoModules[msg_ver]
            msg, rest = decoder.decode(rest, asn1Spec=api.protoSpecification())
            msg = api.decodeMessageVersion(msg)
            pdu = api.apiMessage.getPDU(msg)
            if pdu is None:
                return None
            varbinds = []
            for oid, val in api.apiPDU.getVarBinds(pdu):
                try:
                    value = str(val)
                except Exception:  # noqa: BLE001
                    value = repr(val)
                varbinds.append({"oid": str(oid), "value": value})
            if varbinds:
                return varbinds
        return None

    # ------------------------------------------------------------------
    # 停止
    # ------------------------------------------------------------------
    def _close_dispatcher(self, dispatcher) -> None:
        if dispatcher is None:
            return
        try:
            dispatcher.closeDispatcher()
        except Exception:  # noqa: BLE001
            logger.exception("关闭 snmp dispatcher 异常（忽略）")

    def stop(self) -> None:
        """置位 stop_event 并主动关闭 dispatcher（让 runDispatcher 返回）。"""
        self.ctx.stop_event.set()
        dispatcher = self.ctx.runtime_ref.get("snmp_dispatcher")
        if dispatcher is not None:
            self._close_dispatcher(dispatcher)
