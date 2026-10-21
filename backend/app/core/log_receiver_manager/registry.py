"""插件注册表：适配器 / 流水线组件 / 预处理器 均按 name 注册、可插拔扩展。

用法（适配器自注册）::

    @adapter_registry.register
    class SyslogAdapter(BaseAdapter):
        source_type = "syslog"
        ...

新增一种输入源 = 新增一个适配器模块并在 adapters/__init__.py 导入触发注册，
运行时（start_receiver_sync）按 protocol 查注册表启动，无需修改引擎代码。
"""
import threading
from typing import Any, Callable, Optional


class _BaseRegistry:
    """按 name 键注册/查找插件类的通用容器（线程安全）。"""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self._items: dict[str, type] = {}
        self._lock = threading.Lock()

    def register(self, cls: type) -> type:
        """类装饰器注册；重复注册（模块重载）时后者覆盖前者。"""
        name = self._key_of(cls)
        if not name:
            raise ValueError(f"{self.kind} 插件缺少注册键: {cls!r}")
        with self._lock:
            self._items[name] = cls
        return cls

    def get(self, name: Optional[str]) -> Optional[type]:
        if not name:
            return None
        with self._lock:
            return self._items.get(name)

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._items.keys())

    def _key_of(self, cls: type) -> str:
        raise NotImplementedError


class AdapterRegistry(_BaseRegistry):
    """输入适配器注册表（键 = source_type = LogReceiver.protocol）。"""

    def __init__(self) -> None:
        super().__init__("adapter")

    def _key_of(self, cls: type) -> str:
        return getattr(cls, "source_type", "") or ""

    def source_types(self) -> list[dict]:
        """全部已注册源类型元数据（供 API 校验与前端下拉）。"""
        with self._lock:
            return [
                {
                    "value": name,
                    "label": getattr(cls, "display_name", name),
                    "required_config_keys": list(getattr(cls, "required_config_keys", []) or []),
                }
                for name, cls in self._items.items()
            ]

    def validate_config(self, source_type: str, cfg: dict) -> list[str]:
        """按适配器声明的 required_config_keys 校验配置，返回中文错误列表。

        required_config_keys 元素格式: [(键, 中文说明), ...] 或 ["键", ...]。
        """
        cls = self.get(source_type)
        if cls is None:
            return [f"不支持的接收协议: {source_type}"]
        errors: list[str] = []
        cfg = cfg or {}
        for item in getattr(cls, "required_config_keys", []) or []:
            if isinstance(item, (tuple, list)) and len(item) == 2:
                key, label = item[0], item[1]
                msg = f"{label}（{key}）未配置"
            else:
                key = item
                msg = f"{key} 未配置"
            val = cfg.get(key)
            if val is None or (isinstance(val, str) and not val.strip()):
                errors.append(msg)
        return errors


class StageRegistry(_BaseRegistry):
    """流水线组件注册表（键 = BaseStage.name）。"""

    def __init__(self) -> None:
        super().__init__("stage")

    def _key_of(self, cls: type) -> str:
        return getattr(cls, "name", "") or ""


class PreprocessorRegistry(_BaseRegistry):
    """原始报文预处理器注册表（键 = 预处理器 name，函数或类均可）。"""

    def __init__(self) -> None:
        super().__init__("preprocessor")
        self._funcs: dict[str, Callable[[str], Any]] = {}

    def register(self, obj) -> object:
        """注册预处理器：函数（有 .name 或 __name__）或含 name/process 的类。"""
        if isinstance(obj, type):
            name = getattr(obj, "name", "") or obj.__name__
            with self._lock:
                self._items[name] = obj
            return obj
        # 函数：优先取 .name 属性，否则函数名
        name = getattr(obj, "name", "") or getattr(obj, "__name__", "")
        if not name:
            raise ValueError("预处理器缺少名称")
        with self._lock:
            self._funcs[name] = obj
        return obj

    def get_callable(self, name: Optional[str]) -> Optional[Callable[[str], Any]]:
        """取预处理器可调用对象（函数直接返回；类则实例化取 process）。"""
        if not name:
            return None
        with self._lock:
            if name in self._funcs:
                return self._funcs[name]
            cls = self._items.get(name)
        if cls is not None:
            try:
                inst = cls()
                return getattr(inst, "process", None) or inst
            except Exception:  # noqa: BLE001
                return None
        return None


# 模块级单例
adapter_registry = AdapterRegistry()
stage_registry = StageRegistry()
preprocessor_registry = PreprocessorRegistry()
