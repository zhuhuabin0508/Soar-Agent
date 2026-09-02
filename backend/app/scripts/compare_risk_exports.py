"""compare_risk_exports 独立命令行脚本（供 Node 端 spawn 调用）。

对比两个由 expand_risk_detail 产出的展开表。前置校验两文件表头列集合一致
（顺序可不同）；记录身份 (IP, 用户名, 绑定端口) 按表头名称定位，列序变化、
模板字段增减不影响正确性。纯本地处理，不发起任何网络请求。

用法：::

    python3 compare_risk_exports.py --old <旧展开表路径> --new <新展开表路径>

成功时向 stdout 打印 JSON：``{"new_count", "gone_count", "common_count", "details"}``；
失败时打印 ``{"error": "..."}`` 并以退出码 1 结束。

依赖：Python 3.10+，openpyxl。
"""
import argparse
import json
import sys
from typing import List, Optional

import excel_common as ec


def _header_set(header: List[str]) -> set:
    """把表头行转为非空列名集合（用于一致性校验，忽略顺序）。"""
    return {h for h in header if h}


def run(old_file_path: str, new_file_path: str) -> dict:
    """按记录身份（IP+用户名+绑定端口，按表头名定位）对比两批展开结果。

    Args:
        old_file_path: 旧批次展开表路径。
        new_file_path: 新批次展开表路径。

    Returns:
        ``{"new_count", "gone_count", "common_count", "details": {added, gone, common}}``。

    Raises:
        ValueError: 表头不一致 / 记录身份字段缺失 / 格式识别失败。
        OSError: 文件读写失败。
    """
    old_wb = ec.load_workbook_safe(old_file_path)
    new_wb = ec.load_workbook_safe(new_file_path)

    def header_of(wb) -> List[str]:
        ws = wb.worksheets[0] if wb.worksheets else None
        return ec.read_header_row(ws) if ws is not None else []

    old_header = header_of(old_wb)
    new_header = header_of(new_wb)

    # 1) 表头一致性校验：列集合必须一致（顺序可不同）
    old_set = _header_set(old_header)
    new_set = _header_set(new_header)
    if old_set != new_set:
        parts = []
        added_cols = sorted(new_set - old_set)
        missing_cols = sorted(old_set - new_set)
        if added_cols:
            parts.append("新增列 " + "、".join(added_cols))
        if missing_cols:
            parts.append("缺少列 " + "、".join(missing_cols))
        raise ValueError("两文件表头不一致，无法对比：" + "；".join(parts))

    # 2) 按表头名称定位记录身份字段（任一缺失 → 明确报错）
    cols = ec.locate_identity_cols(old_header)
    missing = []
    if cols["ip"] < 0:
        missing.append("IP")
    if cols["user"] < 0:
        missing.append("用户名")
    if cols["port"] < 0:
        missing.append("绑定端口")
    if missing:
        raise ValueError("记录身份字段缺失：" + "、".join(missing))

    def rec_id(row: tuple, ip_i: int, user_i: int, port_i: int) -> str:
        """把一行归一到记录身份字符串；None/空统一归一为空字符串。"""
        def norm(v) -> str:
            return "" if v is None else str(v).strip()
        parts = [norm(row[i] if i < len(row) else None) for i in (ip_i, user_i, port_i)]
        return "|".join(parts)

    def collect(wb) -> set:
        """按记录身份去重收集全部数据行。

        每个文件按自身表头定位列（列序可不同，索引不得跨文件复用）。
        """
        ws = wb.worksheets[0] if wb.worksheets else None
        if ws is None:
            return set()
        s = set()
        first = True
        ip_i = user_i = port_i = -1
        for row in ws.iter_rows(values_only=True):
            if first:
                first = False
                if any(c is not None for c in row):
                    hdr = [str(c).strip() if c is not None else "" for c in row]
                    c2 = ec.locate_identity_cols(hdr)
                    ip_i, user_i, port_i = c2["ip"], c2["user"], c2["port"]
                continue
            if all(c is None or str(c).strip() == "" for c in row):
                continue
            s.add(rec_id(list(row), ip_i, user_i, port_i))
        return s

    old_ids = collect(old_wb)
    new_ids = collect(new_wb)
    common = old_ids & new_ids
    gone = old_ids - new_ids
    added = new_ids - old_ids
    return {
        "new_count": len(added),
        "gone_count": len(gone),
        "common_count": len(common),
        "details": {
            "added": sorted(added),
            "gone": sorted(gone),
            "common": sorted(common),
        },
    }


def main(argv: Optional[List[str]] = None) -> int:
    """命令行入口：解析参数并执行对比，结果以 JSON 打印到 stdout。"""
    parser = argparse.ArgumentParser(description="对比两批 expand_risk_detail 展开结果")
    parser.add_argument("--old", required=True, help="旧批次展开表路径")
    parser.add_argument("--new", required=True, help="新批次展开表路径")
    args = parser.parse_args(argv)
    try:
        result = run(args.old, args.new)
    except (ValueError, OSError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
