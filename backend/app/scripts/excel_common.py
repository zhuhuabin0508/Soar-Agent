"""expand_risk_detail / compare_risk_exports 脚本的公共模块。

提供两个脚本共享的函数：真实格式识别（不依赖扩展名）、安全加载工作簿（字节流）、
按表头名称定位列、读取表头行、定位记录身份三列。
所有函数均为纯本地处理，不发起任何网络请求。

依赖：Python 3.10+，openpyxl。
"""
import io
from typing import List

import openpyxl

# OLE2 复合文档魔数（真老式二进制 .xls/.doc）
_OLE2_MAGIC = b"\xd0\xcf\x11\xe0"
# OOXML 是 zip 容器，文件头两个字节为 "PK"
_PK_MAGIC = b"PK"

# 弱密码风险清单技能的标准 22 列白名单（expand_risk_detail 未传模板时的默认输出列）。
# 与技能文档「导出字段白名单」一致；传入模板文件时以模板表头为准（覆盖此默认值）。
DEFAULT_RISK_COLUMNS: list[str] = [
    "业务组名", "IP", "内网IP", "外网IP", "主机名",
    "弱密码应用(仅linux)", "弱密码类型", "用户名", "密码", "账号状态",
    "应用版本号(仅linux)", "应用路径(仅linux)", "ssh账号登录方式(仅linux,ssh)",
    "密码状态(仅linux,ssh)", "第一次发现该弱密码的时间(仅linux)",
    "绑定ip(仅linux)", "绑定端口(仅linux)", "进程id(仅linux)",
    "是否root权限运行", "是否对外访问", "shell登录性",
    "mysql帐号允许访问的主机(仅linux mysql)",
]


def detect_real_format(head8: bytes) -> str:
    """按文件头 8 字节判断真实格式（不依赖扩展名）。

    Args:
        head8: 文件开头 8 个字节。

    Returns:
        ``"ole2"``（真老式二进制 .xls/.doc）、``"ooxml"``（OOXML xlsx）、
        ``"unknown"``（无法识别）。
    """
    if head8[:4] == _OLE2_MAGIC:
        return "ole2"
    if head8[:2] == _PK_MAGIC:
        return "ooxml"
    return "unknown"


def _xls_rows_via_xlrd(path: str) -> dict:
    """用 xlrd 读取真 OLE2 老式 .xls，返回 {sheet_name: [[str,...],...]}。

    xlrd 2.x 仅支持旧版 .xls（OLE2），不支持 xlsx。单元格统一转为字符串：
    日期格式化为 ``YYYY-MM-DD``（带时分秒时 ``YYYY-MM-DD HH:MM:SS``）、
    布尔转为 "true"/"false"、空值为 ""。
    """
    import xlrd

    book = xlrd.open_workbook(path, formatting_info=False)
    sheets: dict = {}
    for sh in book.sheets():
        rows = []
        for r in range(sh.nrows):
            row = []
            for c in range(sh.ncols):
                cell = sh.cell(r, c)
                v = cell.value
                if cell.ctype == xlrd.XL_CELL_DATE:
                    try:
                        dt = xlrd.xldate.xldate_as_datetime(v, book.datemode)
                        v = (
                            dt.strftime("%Y-%m-%d %H:%M:%S")
                            if (dt.hour or dt.minute or dt.second)
                            else dt.strftime("%Y-%m-%d")
                        )
                    except Exception:  # noqa: BLE001
                        v = str(v)
                elif cell.ctype == xlrd.XL_CELL_BOOLEAN:
                    v = "true" if v else "false"
                elif v is None:
                    v = ""
                row.append(str(v))
            rows.append(row)
        sheets[sh.name or "Sheet"] = rows
    return sheets


def _xls_to_workbook(path: str):
    """把真 OLE2 老式 .xls 读取为 openpyxl Workbook（仅数据，无样式）。"""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in _xls_rows_via_xlrd(path).items():
        ws = wb.create_sheet(title=name[:31] or "Sheet")
        for row in rows:
            ws.append(row)
    return wb


def load_workbook_safe(path: str):
    """按真实格式识别后从字节流加载 Excel 工作簿（data_only=True）。

    Args:
        path: Excel 文件的服务器路径（后缀不限，按文件头识别真实格式；
            .xls 后缀但 OOXML 内容可正常加载；真 OLE2 旧版 .xls 由 xlrd 读取）。

    Returns:
        已加载的 openpyxl Workbook。

    Raises:
        FileNotFoundError: 文件不存在。
        ValueError: 无法识别的格式、加载失败。
    """
    with open(path, "rb") as f:
        head = f.read(8)
    fmt = detect_real_format(head)
    if fmt == "ole2":
        # 真 OLE2 老式 .xls：xlrd 读取 → openpyxl 工作簿（数据，无样式）
        return _xls_to_workbook(path)
    if fmt != "ooxml":
        raise ValueError("无法识别的文件格式（非 OOXML/OLE2），请确认文件为 Excel")
    with open(path, "rb") as f:
        payload = f.read()
    try:
        return openpyxl.load_workbook(io.BytesIO(payload), data_only=True)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"读取 Excel 失败: {exc}") from exc


def find_col(header: list, name: str, fuzzy: bool = False) -> int:
    """按表头名称定位列，返回列索引；找不到返回 -1。

    Args:
        header: 表头行（字符串列表，可能含 None）。
        name: 目标列名。
        fuzzy: True 时在精确匹配失败后做包含匹配（用于「绑定端口(仅linux)」
            容忍「绑定端口」等变体列名）。

    Returns:
        列索引（0 起），找不到返回 -1。
    """
    if not header:
        return -1
    norm = [str(h).strip() if h is not None else "" for h in header]
    for i, h in enumerate(norm):
        if h == name:
            return i
    if fuzzy:
        for i, h in enumerate(norm):
            if h and name in h:
                return i
    return -1


def read_header_row(ws) -> List[str]:
    """读取工作表第一个非空行作为表头。

    Args:
        ws: openpyxl 工作表对象。

    Returns:
        去除首尾空白后的列名列表；工作表无数据时返回空列表。
    """
    for row in ws.iter_rows(values_only=True):
        if any(c is not None for c in row):
            return [str(c).strip() if c is not None else "" for c in row]
    return []


def locate_identity_cols(header: List[str]) -> dict:
    """按表头名称定位记录身份三列（IP / 用户名 / 绑定端口）。

    绑定端口列名精确匹配「绑定端口(仅linux)」，失败后用「绑定端口」模糊匹配
    （容忍变体列名）。

    Args:
        header: 表头列名列表。

    Returns:
        ``{"ip": int, "user": int, "port": int}``；缺失列索引为 -1。
    """
    ip_i = find_col(header, "IP")
    user_i = find_col(header, "用户名")
    port_i = find_col(header, "绑定端口(仅linux)")
    if port_i < 0:
        port_i = find_col(header, "绑定端口", fuzzy=True)
    return {"ip": ip_i, "user": user_i, "port": port_i}
