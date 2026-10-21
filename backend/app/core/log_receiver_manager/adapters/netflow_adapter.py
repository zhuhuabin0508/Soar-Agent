"""NetFlow 输入适配器（UDP 收包：v5 struct 手解，v9/IPFIX 手动模板解析）。

每条 flow record 转统一 JSON 逐条 publish。v9/IPFIX 模板按来源 IP 维护
缓存（模板包先于数据包到达），未知模板的数据包丢弃。默认端口 2055。

状态机：binding → listening / failed。
"""
import json
import logging
import socketserver
import struct

from ..base_adapter import BaseAdapter
from ..registry import adapter_registry

logger = logging.getLogger(__name__)

# NetFlow v5 头 24 字节 + 每条 record 48 字节
# record: src(I) dst(I) nexthop(I) input(H) output(H) dPkts(I) dOctets(I)
#         First(I) Last(I) srcport(H) dstport(H) pad(B) flags(B) prot(B) tos(B)
#         src_as(H) dst_as(H) src_mask(B) dst_mask(B) pad2(H)
_V5_HEADER = struct.Struct("!HHIIIIBBH")
_V5_RECORD = struct.Struct("!IIIHHIIIIHHBBBBHHBBH")

_V9_VERSION = 9
_IPFIX_VERSION = 10

# v9/IPFIX 通用信息元素（IE）映射：{类型号: (输出字段名, 解码方式)}
# 解码方式：u=大端无符号整数 / ip4=IPv4 / ip6=IPv6 / skip=跳过
_FIELD_TYPES = {
    1: ("octets", "u"),
    2: ("packets", "u"),
    3: ("flows", "u"),
    4: ("protocol", "u"),
    5: ("tos", "u"),
    6: ("tcp_flags", "u"),
    7: ("src_port", "u"),
    8: ("src_ip", "ip4"),
    9: ("src_mask", "u"),
    10: ("input_if", "u"),
    11: ("dst_port", "u"),
    12: ("dst_ip", "ip4"),
    13: ("dst_mask", "u"),
    14: ("output_if", "u"),
    15: ("next_hop", "ip4"),
    16: ("src_as", "u"),
    17: ("dst_as", "u"),
    21: ("last_uptime_ms", "u"),
    22: ("first_uptime_ms", "u"),
    34: ("sampling_interval", "u"),
    60: ("ip_version", "u"),
    61: ("direction", "u"),
}
# IPFIX 中 27/28 = IPv6 源/目的（v9 中为保留类型）
_IPFIX_FIELD_TYPES = dict(_FIELD_TYPES)
_IPFIX_FIELD_TYPES[27] = ("src_ip", "ip6")
_IPFIX_FIELD_TYPES[28] = ("dst_ip", "ip6")


def _ip_from_uint(v: int) -> str:
    return ".".join(str((v >> s) & 0xFF) for s in (24, 16, 8, 0))


def _norm_version(v) -> str:
    """版本标识归一化："v5"/"5"→"5"，"v9"/"9"→"9"，"ipfix"/"10"→"ipfix"。"""
    s = str(v).strip().lower()
    if s in ("5", "v5"):
        return "5"
    if s in ("9", "v9"):
        return "9"
    if s in ("ipfix", "v10", "10"):
        return "ipfix"
    return s


def _ip6_from_bytes(b: bytes) -> str:
    import ipaddress

    try:
        return str(ipaddress.IPv6Address(b))
    except Exception:  # noqa: BLE001
        return b.hex()


def _parse_v5(data: bytes) -> list[dict]:
    """NetFlow v5：24B 头 + N×48B record，全部字段手解。"""
    if len(data) < _V5_HEADER.size:
        raise ValueError("v5 包长度不足 24 字节")
    version, count, sys_uptime, unix_secs, _, sequence, _, _, _ = _V5_HEADER.unpack_from(data, 0)
    if version != 5:
        raise ValueError(f"非 v5 版本: {version}")
    flows = []
    offset = _V5_HEADER.size
    for i in range(count):
        if offset + _V5_RECORD.size > len(data):
            break
        (src, dst, nexthop, inp, outp, dpkts, doctets, first, last,
         sport, dport, _, tcp_flags, proto, tos, src_as, dst_as, src_mask, dst_mask, _) = \
            _V5_RECORD.unpack_from(data, offset)
        offset += _V5_RECORD.size
        flows.append({
            "version": 5,
            "sequence": sequence + i,
            "src_ip": _ip_from_uint(src),
            "dst_ip": _ip_from_uint(dst),
            "next_hop": _ip_from_uint(nexthop),
            "input_if": inp,
            "output_if": outp,
            "packets": dpkts,
            "octets": doctets,
            "first_uptime_ms": first,
            "last_uptime_ms": last,
            "src_port": sport,
            "dst_port": dport,
            "tcp_flags": tcp_flags,
            "protocol": proto,
            "tos": tos,
            "src_as": src_as,
            "dst_as": dst_as,
            "src_mask": src_mask,
            "dst_mask": dst_mask,
            "timestamp": unix_secs,
        })
    return flows


class _NetFlowUDPServer(socketserver.ThreadingUDPServer):
    allow_reuse_address = True


@adapter_registry.register
class NetFlowAdapter(BaseAdapter):
    """NetFlow v5/v9/IPFIX 接收适配器（零第三方依赖，模板手动解析）。"""

    source_type = "netflow"
    display_name = "NetFlow 接收"
    default_ready_timeout_s = 3.0

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        # 模板缓存：{来源IP: {template_id: [(字段类型, 长度), ...]}}
        self._templates: dict[str, dict[int, list]] = {}

    def run(self) -> None:
        receiver = self.ctx.receiver or {}
        cfg = receiver.get("adapter_config") or {}
        bind = (cfg.get("bind") or "0.0.0.0").strip() or "0.0.0.0"
        try:
            port = int(cfg.get("port") or 2055)
        except (ValueError, TypeError):
            port = 2055
        versions = set(
            _norm_version(v) for v in (cfg.get("versions") or ["v5", "v9", "ipfix"])
        )

        self.ctx.set_status("binding", None)
        server = None
        try:
            server = _NetFlowUDPServer((bind, port), self._make_handler(versions))
            server.ctx = self.ctx
            self.ctx.runtime_ref["netflow_server"] = server
            self.ctx.signal_ready(True)
            self.ctx.set_status("listening", None)
            logger.info(
                "netflow 监听已启动: %s:%s versions=%s (receiver=%s gen=%s)",
                bind, port, sorted(versions), self.ctx.receiver_id, self.ctx.generation,
            )
            server.serve_forever()
        except OSError as exc:
            msg = f"netflow 端口绑定失败 {bind}:{port}: {exc}"
            self.ctx.mark_start_failed(msg)
            self.ctx.signal_ready(False, msg)
            return
        except Exception as exc:  # noqa: BLE001
            if not self.ctx.stop_event.is_set():
                logger.exception("netflow 监听异常: %s", exc)
                self.ctx.set_status("failed", f"{type(exc).__name__}: {exc}")
                self.ctx.signal_ready(False, f"{type(exc).__name__}: {exc}")
        finally:
            self._safe_close(server)
            if self.ctx.runtime_ref.get("netflow_server") is server:
                self.ctx.runtime_ref.pop("netflow_server", None)

    # ------------------------------------------------------------------
    # 收包处理
    # ------------------------------------------------------------------
    def _make_handler(self, versions: set):
        adapter = self

        class _Handler(socketserver.BaseRequestHandler):
            def handle(self):
                data = self.request[0]
                client_ip = self.client_address[0] if self.client_address else None
                try:
                    flows = adapter._parse_packet(data, versions, client_ip)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("netflow 包解析失败（忽略）: %s", exc)
                    return
                for flow in flows:
                    adapter.ctx.publish(
                        json.dumps(flow, ensure_ascii=False, default=str),
                        source_ip=client_ip,
                        meta={"netflow_version": flow.get("version")},
                    )

        return _Handler

    def _parse_packet(self, data: bytes, versions: set, client_ip) -> list[dict]:
        """按包头版本字段路由：v5 手解；v9/IPFIX 手动模板解析。"""
        if len(data) < 4:
            return []
        version = int.from_bytes(data[0:2], "big")
        if version == 5 and "5" in versions:
            return _parse_v5(data)
        if version == _V9_VERSION and "9" in versions:
            return self._parse_v9(data, client_ip, _V9_VERSION)
        if version == _IPFIX_VERSION and "ipfix" in versions:
            return self._parse_v9(data, client_ip, _IPFIX_VERSION)
        logger.debug("netflow 版本 %s 不在启用列表，丢弃", version)
        return []

    # ------------------------------------------------------------------
    # v9 / IPFIX（头部 20B；集合流式解析）
    #   v9 头:  版本(2) 数量(2) 系统运行ms(4) unix秒(4) 序列(4) 源ID(4)
    #   IPFIX头: 版本(2) 长度(2) unix秒(4) 序列(4) 观察域(4)
    # ------------------------------------------------------------------
    def _parse_v9(self, data: bytes, client_ip, version: int) -> list[dict]:
        if len(data) < 20:
            raise ValueError("v9/IPFIX 包长度不足 20 字节")
        if version == _IPFIX_VERSION:
            _, length, epoch_secs, _, _ = struct.unpack_from("!HHIII", data, 0)
        else:
            _, _, _, epoch_secs, _, _ = struct.unpack_from("!HHIIII", data, 0)
            length = len(data)
        templates = self._templates.setdefault(client_ip or "unknown", {})
        flows: list[dict] = []
        offset = 20
        while offset + 4 <= length and offset + 4 <= len(data):
            set_id, set_len = struct.unpack_from("!HH", data, offset)
            if set_len < 4 or offset + set_len > len(data):
                break
            body = data[offset + 4: offset + set_len]
            if set_id in (0, 2):  # 模板集合（v9: 0；IPFIX: 2）
                self._parse_template_set(body, templates)
            elif set_id in (1, 3):
                pass  # 选项模板：忽略
            elif set_id >= 256:  # 数据集合（set_id = template_id）
                flows.extend(
                    self._parse_data_set(set_id, body, templates, version, epoch_secs)
                )
            offset += set_len
        return flows

    @staticmethod
    def _parse_template_set(body: bytes, templates: dict) -> None:
        """解析模板集合体：若干 (template_id, field_count, [(type, len), ...])。"""
        off = 0
        while off + 4 <= len(body):
            template_id, field_count = struct.unpack_from("!HH", body, off)
            off += 4
            fields = []
            ok = True
            for _ in range(field_count):
                if off + 4 > len(body):
                    ok = False
                    break
                ftype, flen = struct.unpack_from("!HH", body, off)
                fields.append((ftype, flen))
                off += 4
            if not ok:
                break
            templates[template_id] = fields

    def _parse_data_set(self, template_id: int, body: bytes, templates: dict,
                        version: int, epoch_secs: int) -> list[dict]:
        """按模板逐条解码数据记录。"""
        fields = templates.get(template_id)
        if not fields:
            logger.debug("netflow 未知模板 %s（等待模板包），丢弃数据包", template_id)
            return []
        field_map = _IPFIX_FIELD_TYPES if version == _IPFIX_VERSION else _FIELD_TYPES
        flows = []
        off = 0
        total = 0
        for _, flen in fields:
            total += flen
        if total <= 0:
            return []
        while off + total <= len(body):
            flow: dict = {"version": version, "timestamp": epoch_secs}
            cur = off
            for ftype, flen in fields:
                name_decoder = field_map.get(ftype)
                raw = body[cur: cur + flen]
                cur += flen
                if not name_decoder:
                    continue
                name, decoder = name_decoder
                if decoder == "u" and 0 < flen <= 8:
                    flow[name] = int.from_bytes(raw, "big")
                elif decoder == "ip4" and flen == 4:
                    flow[name] = _ip_from_uint(int.from_bytes(raw, "big"))
                elif decoder == "ip6" and flen == 16:
                    flow[name] = _ip6_from_bytes(raw)
            flows.append(flow)
            off += total
        return flows

    @staticmethod
    def _safe_close(server) -> None:
        if server is None:
            return
        try:
            server.server_close()
        except Exception:  # noqa: BLE001
            logger.exception("关闭 netflow server 异常（忽略）")

    def stop(self) -> None:
        """置位 stop_event 并主动 shutdown server。"""
        self.ctx.stop_event.set()
        server = self.ctx.runtime_ref.get("netflow_server")
        if server is not None:
            try:
                server.shutdown()
            except Exception:  # noqa: BLE001
                pass
            self._safe_close(server)
