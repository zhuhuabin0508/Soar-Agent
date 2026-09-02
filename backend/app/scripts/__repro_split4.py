import asyncio, traceback, json, re, ipaddress
from datetime import datetime, timedelta
import openpyxl
from app.core.tool_runner import (
    load_excel_workbook, save_workbook_as_agent_file, read_uploaded_file,
    find_col, save_json_as_agent_file, DEFAULT_RISK_COLUMNS,
)
from app.core.tool_sandbox import build_safe_builtins
from app.database import SessionLocal
from app.models.tool import Tool

db = SessionLocal()
st = db.query(Tool).filter(Tool.id == 65).first()
code = st.code
# 让内部 except 抛出以暴露 traceback
code = code.replace(
    "    except Exception as e:\n        return {\"error\": f\"处理失败: {str(e)}\"}",
    "    except Exception as e:\n        raise",
)
ns = {
    "__builtins__": build_safe_builtins(),
    "asyncio": asyncio, "json": json, "re": re, "ipaddress": ipaddress,
    "datetime": datetime, "timedelta": timedelta, "openpyxl": openpyxl,
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
