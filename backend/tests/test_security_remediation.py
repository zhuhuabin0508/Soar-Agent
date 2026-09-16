"""渗透测试整改——安全修复的最小回归测试。

覆盖（对应《渗透测试整改提示词.md》中的漏洞项）：
- 漏洞2（Python 沙箱逃逸）：
  - ``safe_code_runner._safe_builtins()`` 不含 open/eval/exec/compile/getattr/
    setattr/globals/locals/vars/dir/__import__ 等危险内置名；
  - ``node_executors._check_code_forbidden()`` 拒绝渗透报告中的 dunder 逃逸链
    （``().__class__.__mro__[1].__subclasses__()``）与威胁内置名，放行正常业务代码。
- 漏洞4/5（越权查询）：analyst / viewer 角色的默认权限矩阵中不再包含
  ``strategy`` 与 ``ban_workflow`` 模块。

说明：本地开发环境无 DB / Redis / FastAPI TestClient 依赖，因此
漏洞1（OTP dev_code 不回显）与漏洞3（子资源端点所有权）依赖完整
HTTP 栈的用例不在本文件内运行（需在 Docker 环境执行），复测 curl 命令
见整改任务书"完成时输出"。
"""
import sys
import types


# ---- 让 node_executors 可独立导入（本地无 sqlalchemy 依赖） ----
def _install_device_stub():
    """预置 app.devices 及其 firewall 子模块桩，避免触发 sqlalchemy 等重依赖。

    node_executors 顶层 ``from app.devices.firewall import block_ip_on_firewall`` 会
    经 ``app.devices.__init__`` 拉入 device/action 模型（依赖 sqlalchemy），此处用
    桩替换，仅保留本测试需要的 ``block_ip_on_firewall`` 符号。
    """
    if "app.devices.firewall" in sys.modules:
        return

    firewall = types.ModuleType("app.devices.firewall")
    async def _block(*args, **kwargs):  # mock，测试不实际调用
        return {"status": "ok"}
    firewall.block_ip_on_firewall = _block

    devices_pkg = types.ModuleType("app.devices")
    devices_pkg.__path__ = []

    sys.modules["app.devices"] = devices_pkg
    sys.modules["app.devices.firewall"] = firewall


_install_device_stub()

from app.core import node_executors  # noqa: E402
from app.core.safe_code_runner import _safe_builtins  # noqa: E402


# ============ 漏洞2：受限内置函数子集 ============

class TestSafeBuiltins:
    def test_dangerous_builtins_excluded(self):
        blt = _safe_builtins()
        for name in (
            "open", "eval", "exec", "compile", "__import__", "globals",
            "locals", "vars", "dir", "getattr", "setattr", "delattr",
            "input", "breakpoint",
        ):
            assert name not in blt, f"危险内置 {name} 不应被暴露"

    def test_safe_builtins_present(self):
        blt = _safe_builtins()
        for name in ("len", "str", "int", "dict", "list", "range", "enumerate", "print"):
            assert name in blt, f"安全内置 {name} 应可用"


# ============ 漏洞2：AST 预检 ============

class TestCheckCodeForbidden:
    def test_rejects_dunder_escape_chain(self):
        poc = "x = ().__class__.__mro__[1].__subclasses__()"
        reason = node_executors._check_code_forbidden(poc)
        assert reason is not None
        assert "dunder" in reason or "禁止" in reason

    def test_rejects_subclasses_attribute(self):
        reason = node_executors._check_code_forbidden("y = [].__class__.__subclasses__()")
        assert reason is not None

    def test_rejects_dangerous_builtin_name(self):
        assert node_executors._check_code_forbidden("z = eval('1+1')") is not None
        assert node_executors._check_code_forbidden("w = getattr(x, '__dict__')") is not None
        assert node_executors._check_code_forbidden("v = globals()") is not None

    def test_allows_normal_code(self):
        assert node_executors._check_code_forbidden("result = {'len': len(input_data)}") is None
        assert node_executors._check_code_forbidden("result = sum(x for x in range(3))") is None

    def test_rejects_syntax_error_as_non_none(self):
        assert node_executors._check_code_forbidden("result = (") is not None


# ============ 漏洞4/5：角色权限矩阵收紧 ============

class TestRolePermissionMatrix:
    # DEFAULT_ROLES 是 list[dict]，每项含 name 与 permissions{module: [actions]}
    @staticmethod
    def _role_matrix(name: str) -> dict:
        from app.core.permissions import DEFAULT_ROLES

        for entry in DEFAULT_ROLES:
            if entry.get("name") == name:
                return entry.get("permissions", {})
        raise AssertionError(f"未找到默认角色 {name}")

    def test_analyst_and_viewer_no_strategy_or_ban_workflow(self):
        for role in ("analyst", "viewer"):
            matrix = self._role_matrix(role)
            assert isinstance(matrix, dict), f"{role} 权限矩阵应为 dict"
            assert "strategy" not in matrix, f"{role} 不应拥有 strategy 模块"
            assert "ban_workflow" not in matrix, f"{role} 不应拥有 ban_workflow 模块"

    def test_admin_still_has_modules(self):
        # admin 为超级管理员，权限矩阵覆盖全部 PERMISSION_MODULES 且包含这两个模块
        matrix = self._role_matrix("admin")
        assert isinstance(matrix, dict)
        assert set(matrix) >= {"strategy", "ban_workflow"}, (
            "admin 超级管理员应保留 strategy/ban_workflow 模块"
        )
