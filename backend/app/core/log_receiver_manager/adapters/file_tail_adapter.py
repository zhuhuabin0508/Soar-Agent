"""日志文件跟踪输入适配器（tail -F 语义，零第三方依赖）。

跟踪指定文件（或 glob 多文件）：读至 EOF 记录 offset，轮询增量读取；
文件 truncate/轮转（offset 超过文件大小）时从头重读。每行 publish 一条
事件（jsonl/raw 行格式一致，行内容原样进入流水线）。

状态机：connecting → running；publish 失败（总线满）不推进 offset，
下一轮重读该行（文件采集不丢数据）。
"""
import glob
import logging
import os

from ..base_adapter import BaseAdapter
from ..registry import adapter_registry
from ._polling import CursorStore

logger = logging.getLogger(__name__)


@adapter_registry.register
class FileTailAdapter(BaseAdapter):
    """日志文件跟踪适配器（tail -F）。"""

    source_type = "file_tail"
    display_name = "日志文件跟踪"
    default_ready_timeout_s = 3.0
    required_config_keys = [("path", "文件路径")]

    def run(self) -> None:
        receiver = self.ctx.receiver or {}
        cfg = receiver.get("adapter_config") or {}
        path = (cfg.get("path") or "").strip()
        if not path:
            self.ctx.mark_start_failed("未配置跟踪文件路径（adapter_config.path）")
            self.ctx.signal_ready(False, "未配置跟踪文件路径")
            return
        encoding = cfg.get("encoding") or "utf-8"
        from_beginning = bool(cfg.get("from_beginning"))
        line_format = (cfg.get("line_format") or "raw").lower()
        interval = max(0.2, float(cfg.get("poll_interval_seconds") or 2))
        is_glob = any(ch in path for ch in "*?[")

        # 水位：{文件绝对路径: offset}（glob 多文件各自独立）
        self._cursor = CursorStore(self.ctx)
        offsets: dict = dict(self._cursor.load() or {}) or {}

        self.ctx.signal_ready(True)
        self.ctx.set_status("running", None)
        logger.info(
            "file_tail 跟踪已启动: path=%s format=%s (receiver=%s gen=%s)",
            path, line_format, self.ctx.receiver_id, self.ctx.generation,
        )

        while not self.ctx.stop_event.is_set():
            try:
                files = sorted(glob.glob(path)) if is_glob else [path]
                cur_names = set()
                for fpath in files:
                    cur_names.add(fpath)
                    try:
                        size = os.path.getsize(fpath)
                    except OSError:
                        # 文件暂不存在（轮转窗口 / 尚未生成）：跳过
                        continue
                    offset = offsets.get(fpath)
                    if offset is None:
                        if from_beginning:
                            offset = 0
                        else:
                            # 首次发现该文件：从末尾开始（只采增量）
                            offsets[fpath] = size
                            continue
                    elif offset > size:
                        # truncate/轮转：从头重读
                        offset = 0
                    try:
                        self._tail_file(fpath, offset, encoding, offsets)
                    except FileNotFoundError:
                        continue
                    except Exception as exc:  # noqa: BLE001
                        logger.exception("file_tail 读取异常（忽略本轮）: %s", exc)
                # 轮转后消失的文件：清理水位
                for name in list(offsets.keys()):
                    if name not in cur_names and not os.path.exists(name):
                        offsets.pop(name, None)
                # 节流回写水位（内存已即时更新）
                self._cursor.save(dict(offsets))
            except Exception as exc:  # noqa: BLE001
                logger.exception("file_tail 轮询异常（忽略本轮）: %s", exc)
            self.ctx.stop_event.wait(interval)

    def _tail_file(self, fpath: str, offset: int, encoding: str, offsets: dict) -> None:
        """从 offset 增量读取到 EOF；逐行 publish，失败不推进 offset。

        注意：文本文件迭代（for line in f）会禁用 f.tell()，故用 readline()。
        """
        with open(fpath, "r", encoding=encoding, errors="replace") as f:
            f.seek(offset)
            pos = offset
            while True:
                line = f.readline()
                if not line:
                    break  # EOF
                text = line.rstrip("\r\n")
                if not text:
                    pos = f.tell()
                    offsets[fpath] = pos
                    continue
                # 行内容原样透传给流水线（jsonl/raw 由解析策略处理）
                ok = self.ctx.publish(text, source_ip=None)
                if not ok:
                    # 总线满：不推进 offset，下轮从当前行重读
                    offsets[fpath] = pos
                    return
                pos = f.tell()
                offsets[fpath] = pos

    def stop(self) -> None:
        """停止前把水位落库（避免 30s 节流窗口丢最近进度）。"""
        self.ctx.stop_event.set()
        cursor = getattr(self, "_cursor", None)
        if cursor is not None:
            try:
                cursor.flush_now()
            except Exception:  # noqa: BLE001
                pass
