import asyncio, traceback, json, re, ipaddress, datetime, openpyxl
from app.core.tool_runner import (
    load_excel_workbook, save_workbook_as_agent_file, read_uploaded_file,
    find_col, save_json_as_agent_file, DEFAULT_RISK_COLUMNS,
)
from app.database import SessionLocal
from app.models.tool import Tool

db = SessionLocal()
st = db.query(Tool).filter(Tool.id == 65).first()
code = st.code
ns = {
    "asyncio": asyncio, "json": json, "re": re, "ipaddress": ipaddress,
    "datetime": datetime, "openpyxl": openpyxl,
    "read_uploaded_file": read_uploaded_file,
    "load_excel_workbook": load_excel_workbook,
    "save_workbook_as_agent_file": save_workbook_as_agent_file,
    "save_json_as_agent_file": save_json_as_agent_file,
    "find_col": find_col,
    "DEFAULT_RISK_COLUMNS": DEFAULT_RISK_COLUMNS,
    "current_agent_id": None, "current_user_id": None,
}
exec(compile(code, "<split>", "exec"), ns)
run = ns["run"]

try:
    r = asyncio.get_event_loop().run_until_complete(
        run(file_name="风险列表 (12)(1)_展开.xlsx"))
    print("RESULT:", str(r)[:500])
except Exception:
    traceback.print_exc()
db.close()
