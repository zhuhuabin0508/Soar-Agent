"""expand_risk_detail 独立命令行脚本（供 Node 端 spawn 调用）。

模板驱动地解析主机风险 Excel（青藤/盾立方导出）中「风险详情」列的 JSON 内容，
输出表的列定义完全取自模板 Excel 首个 Sheet 第 1 行的表头（不内置字段清单）。
纯本地处理，不发起任何网络请求。

用法：:

    python3 expand_risk_detail.py --source <源xlsx路径> --template <模板xlsx路径> \\
        [--output <输出路径>] [--save-template <JSON路径>]

成功时向 stdout 打印 JSON：``{"output_file", "rows", "columns", "template_columns"}``；
失败时打印 ``{"error": "..."}`` 并以退出码 1 结束。

依赖：Python 3.10+，openpyxl。
"""
import argparse
import json
import os
import sys
from typing import List, Optional

import openpyxl
from openpyxl.styles import Alignment, Border, Font, Side

import excel_common as ec


def run(
    source_file_path: str,
    template_file_path: str,
    output_file_path: Optional[str] = None,
    save_template: Optional[str] = None,
) -> dict:
    """模板驱动展开：把源文件按模板表头展开为精简表并另存为 xlsx。

    Args:
        source_file_path: 源 Excel 文件路径。
        template_file_path: 模板 Excel 文件路径（首个 Sheet 第 1 行 = 输出列定义）。
        output_file_path: 输出路径，省略时默认 <源文件名>_展开.xlsx 同目录。
        save_template: 可选，传入 JSON 路径时把输出列定义持久化写入该文件。

    Returns:
        ``{"output_file", "rows", "columns", "template_columns"}``。

    Raises:
        ValueError: 模板无效 / 源文件表头不匹配 / 格式识别失败。
        OSError: 文件读写失败。
    """
    # 1) 确定输出列定义：传模板则取模板首个 Sheet 第 1 行；未传则用标准 22 列白名单
    header = None
    if template_file_path:
        try:
            tpl_wb = ec.load_workbook_safe(template_file_path)
        except FileNotFoundError:
            raise ValueError(f"模板无效：模板文件不存在: {template_file_path}")
        except ValueError as exc:
            raise ValueError(f"模板无效：{exc}")
        header = [h for h in ec.read_header_row(tpl_wb.worksheets[0]) if h]
        if not header:
            raise ValueError("模板无效：表头为空")
    else:
        header = list(ec.DEFAULT_RISK_COLUMNS)

    # 2) 加载源文件并定位「风险详情」与「IP」列
    src_wb = ec.load_workbook_safe(source_file_path)
    target_ws = None
    src_ip_col = src_risk_col = -1
    for ws in src_wb.worksheets:
        hdr = ec.read_header_row(ws)
        if not hdr:
            continue
        ip_i = ec.find_col(hdr, "IP")
        risk_i = ec.find_col(hdr, "风险详情")
        if ip_i >= 0 and risk_i >= 0:
            target_ws = ws
            src_ip_col = ip_i
            src_risk_col = risk_i
            break
    if target_ws is None:
        raise ValueError("表头不匹配：源文件未找到「风险详情」或「IP」列")

    # 3) 逐行映射：IP 列取源 IP 值；其余列名作为键从风险详情 JSON dict 取值
    out_rows: List[List[str]] = []
    first = True
    for row in target_ws.iter_rows(values_only=True):
        if first:
            first = False
            continue
        ip_val = str(row[src_ip_col]).strip() if src_ip_col < len(row) and row[src_ip_col] is not None else ""
        raw = row[src_risk_col] if src_risk_col < len(row) else None
        # 「风险详情」与「IP」均为空的行跳过
        if not ip_val and (raw is None or str(raw).strip() == ""):
            continue
        detail = {}
        if raw:
            try:
                parsed = json.loads(raw) if isinstance(raw, str) else raw
            except Exception:  # noqa: BLE001 —— JSON 解析失败行：JSON 列留空，IP 仍填充
                parsed = None
            if isinstance(parsed, list):
                detail = parsed[0] if parsed and isinstance(parsed[0], dict) else {}
            elif isinstance(parsed, dict):
                detail = parsed
        row_out = []
        for col_name in header:
            if col_name == "IP":
                row_out.append(ip_val)
            else:
                v = detail.get(col_name)
                row_out.append("" if v is None else str(v))
        out_rows.append(row_out)

    # 4) 生成输出：全边框、表头加粗居中、行高表头20/数据15、自适应列宽（中文按 2 宽）
    nwb = openpyxl.Workbook()
    ws = nwb.active
    ws.title = "sheet1"
    ws.append(header)
    for r in out_rows:
        ws.append(r)
    thin = Side(style="thin", color="000000")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal="center", vertical="center")
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=len(header)):
        for cell in row:
            cell.border = border
            if cell.row == 1:
                cell.font = Font(bold=True)
                cell.alignment = center
    ws.row_dimensions[1].height = 20
    for r in range(2, ws.max_row + 1):
        ws.row_dimensions[r].height = 15
    for col_cells in ws.columns:
        width = 8
        for c in col_cells:
            if c.value is None:
                continue
            s = str(c.value)
            w = sum(2 if ord(ch) > 0x2E7F else 1 for ch in s)
            if w + 2 > width:
                width = w + 2
        ws.column_dimensions[openpyxl.utils.get_column_letter(col_cells[0].column)].width = width

    if not output_file_path:
        base, _ = os.path.splitext(source_file_path)
        output_file_path = f"{base}_展开.xlsx"
    nwb.save(output_file_path)

    result = {
        "output_file": output_file_path,
        "rows": len(out_rows),
        "columns": len(header),
        "template_columns": header,
    }
    if save_template:
        with open(save_template, "w", encoding="utf-8") as f:
            json.dump({"template_columns": header}, f, ensure_ascii=False, indent=2)
        result["template_file"] = save_template
    return result


def main(argv: Optional[List[str]] = None) -> int:
    """命令行入口：解析参数并执行展开，结果以 JSON 打印到 stdout。"""
    parser = argparse.ArgumentParser(description="模板驱动解析主机风险 Excel 并导出精简表")
    parser.add_argument("--source", required=True, help="源 Excel 文件路径")
    parser.add_argument("--template", default=None, help="可选：模板 Excel 文件路径（省略时使用标准 22 列白名单）")
    parser.add_argument("--output", default=None, help="输出 xlsx 路径（默认 <源文件名>_展开.xlsx）")
    parser.add_argument("--save-template", default=None, help="可选：把输出列定义持久化为 JSON 文件路径")
    args = parser.parse_args(argv)
    try:
        result = run(args.source, args.template, args.output, getattr(args, "save_template"))
    except (ValueError, OSError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
