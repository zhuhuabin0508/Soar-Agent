import asyncio, traceback
from app.core.tool_runner import load_tool_function
from app.models.tool import Tool
from app.database import SessionLocal

db = SessionLocal()
et = db.query(Tool).filter(Tool.name == 'expand_risk_detail').first()
erun = load_tool_function(et, agent_id=None, user_id=None)
res = asyncio.get_event_loop().run_until_complete(erun(source_file_path='风险列表 (12)(1).xls'))
print('expand:', res.get('output_file'), res.get('rows'))

st = db.query(Tool).filter(Tool.id == 65).first()
srun = load_tool_function(st, agent_id=None, user_id=None)
try:
    r2 = asyncio.get_event_loop().run_until_complete(srun(file_name='风险列表 (12)(1)_展开.xlsx'))
    print('split:', str(r2)[:400])
except Exception:
    traceback.print_exc()
db.close()
