"""安全工具集定义（已退役）。

原 16 个渗透测试类预置工具（nmap_scan / nuclei_scan / sqlmap_scan /
hydra_attack / crackmapexec_run 等，覆盖渗透侦察 / 漏洞扫描 / 利用与报告 /
内网渗透四个类别）已按用户要求彻底退役：

- 工具定义已从本模块移除，全部名称加入 ``definitions/legacy.py`` 的
  ``REMOVED_BUILTIN_TOOLS`` 退役名单，启动时由
  ``seed_service._cleanup_removed_and_legacy`` 从 tools 表物理删除；
- ``app/tools/security_tools.py`` 中的底层封装函数保留（不再作为预置工具暴露）；
- ``tool_runner`` 沙箱命名空间已同步移除 security_tools 函数注入
  （原先仅用于本模块工具代码的透传调用）。

如需恢复：在本模块重新添加工具定义，并从退役名单中移除对应名称。
"""
from typing import Any

# 已全部退役：见模块 docstring。保留空列表以维持 catalog / seed 导入链路稳定。
SECURITY_TOOLS: list[dict[str, Any]] = []
