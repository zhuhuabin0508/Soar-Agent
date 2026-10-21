"""Syslog 输入适配器（UDP/TCP socketserver，自原 _run_syslog_listener 等价迁移）。

绑定状态机：binding → listening（成功）/ failed（异常）；启动结果经
ctx.signal_ready 同步反馈给保存接口（端口占用等实时报错）。
"""
import logging
import socketserver
from typing import Any, Optional

from ..adapter_context import AdapterContext
from ..base_adapter import BaseAdapter
from ..registry import adapter_registry

logger = logging.getLogger(__name__)


def _recv_encoding(ctx: AdapterContext) -> str:
    """从接收器 adapter_config 读取日志编码（默认 UTF-8，接入指引可选 gbk/gb18030）。"""
    try:
        cfg = (ctx.receiver or {}).get("adapter_config") or {}
        enc = cfg.get("encoding")
        return enc if isinstance(enc, str) and enc else "utf-8"
    except Exception:  # noqa: BLE001
        return "utf-8"


class _SyslogUDPHandler(socketserver.BaseRequestHandler):
    """UDP syslog 处理器：报文为 (data, socket)。"""

    def handle(self) -> None:
        try:
            raw_data = self.request[0].strip().decode(_recv_encoding(self.server.ctx), errors="replace")
        except Exception:  # noqa: BLE001
            return
        client_ip = self.client_address[0] if self.client_address else None
        if raw_data:
            self.server.ctx.publish(raw_data, source_ip=client_ip)


class _SyslogTCPHandler(socketserver.StreamRequestHandler):
    """TCP syslog 处理器：按行读取（换行分隔的简单 syslog 格式）。"""

    def handle(self) -> None:
        try:
            enc = _recv_encoding(self.server.ctx)
            for line in self.rfile:
                raw_data = line.decode(enc, errors="replace").strip()
                if not raw_data:
                    continue
                client_ip = self.client_address[0] if self.client_address else None
                self.server.ctx.publish(raw_data, source_ip=client_ip)
        except (ConnectionResetError, BrokenPipeError):
            pass
        except Exception:  # noqa: BLE001
            logger.exception("TCP syslog 处理异常（忽略）")


class _SyslogUDPServer(socketserver.ThreadingUDPServer):
    allow_reuse_address = True


class _SyslogTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


def _safe_close_server(server: Any) -> None:
    """安全关闭 socketserver（不抛异常）。"""
    if server is None:
        return
    try:
        server.server_close()
    except Exception:  # noqa: BLE001
        logger.exception("关闭 socketserver 异常（忽略）")


@adapter_registry.register
class SyslogAdapter(BaseAdapter):
    """Syslog UDP/TCP 监听适配器。"""

    source_type = "syslog"
    display_name = "Syslog 监听"
    default_ready_timeout_s = 3.0  # = BIND_WAIT_TIMEOUT_S

    def run(self) -> None:
        receiver = self.ctx.receiver or {}
        port = receiver.get("syslog_port")
        proto = (receiver.get("syslog_proto") or "udp").lower()
        bind = receiver.get("syslog_bind") or "0.0.0.0"
        if not port:
            self.ctx.mark_start_failed("未配置 syslog 监听端口")
            self.ctx.signal_ready(False, "未配置 syslog 监听端口")
            return

        self.ctx.set_status("binding", None)
        server = None
        try:
            if proto == "tcp":
                server = _SyslogTCPServer((bind, port), _SyslogTCPHandler)
            else:
                server = _SyslogUDPServer((bind, port), _SyslogUDPHandler)
            server.receiver_key = self.ctx.receiver_id
            server.ctx = self.ctx
            self.ctx.runtime_ref["server"] = server
            self.ctx.signal_ready(True)
            self.ctx.set_status("listening", None)
            logger.info(
                "syslog %s 监听已启动: %s:%s (receiver=%s gen=%s)",
                proto, bind, port, self.ctx.receiver_id, self.ctx.generation,
            )
            # serve_forever 阻塞直至 server.shutdown()（由 stop_receiver_thread 调用）；
            # 停止/重启时旧代经 join 排空后自然结束。
            server.serve_forever()
        except Exception as exc:  # noqa: BLE001
            logger.exception("syslog 监听启动失败: %s", exc)
            if not self.ctx.stop_event.is_set():
                self.ctx.set_status("failed", f"{type(exc).__name__}: {exc}")
                self.ctx.signal_ready(False, f"{type(exc).__name__}: {exc}")
        finally:
            _safe_close_server(server)
            # 仅在本代仍占用 server 槽位时才清空，避免误删新一代的 server
            if self.ctx.runtime_ref.get("server") is server:
                self.ctx.runtime_ref.pop("server", None)

    def stop(self) -> None:
        """置位 stop_event 并主动 shutdown socketserver。"""
        self.ctx.stop_event.set()
        server = self.ctx.runtime_ref.get("server")
        if server is not None:
            try:
                server.shutdown()
            except Exception:  # noqa: BLE001
                pass
            _safe_close_server(server)
