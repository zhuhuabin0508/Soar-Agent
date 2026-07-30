"""智能体文件 API：上传 / 列表 / 删除。

上传的文件原样存储（不做 RAG 切片/向量化），供智能体通过 ``read_document`` 工具按需读取。
支持类型：xlsx / xls / docx / pdf / csv / txt / json / md。
"""
import logging
import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.agent_file import AgentFile

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/agent-files",
    tags=["agent-files"],
    dependencies=[Depends(get_current_user)],
)

# 上传文件保存目录：backend/uploads/agent_files/
# __file__ = backend/app/api/v1/agent_files.py，上溯 4 级到 backend/
UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "uploads",
    "agent_files",
)

# 允许的文件扩展名（小写，不含点）
ALLOWED_EXTENSIONS = {
    "xlsx", "xls", "docx", "pdf", "csv", "txt", "json", "md",
}

# 文件大小上限：50MB
MAX_FILE_SIZE = 50 * 1024 * 1024


def _ensure_upload_dir() -> None:
    """确保上传目录存在。"""
    os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.post("/upload")
async def upload_agent_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """上传一个文件（不做 RAG，原样存储）。

    返回文件元数据（id / original_name / file_type / file_size）。
    前端拿到后可展示在文件列表中供用户勾选。
    """
    _ensure_upload_dir()

    original_name = file.filename or "unknown"
    # 取扩展名（小写）
    ext = ""
    if "." in original_name:
        ext = original_name.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: .{ext}，仅支持 {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    # 读取文件内容并检查大小
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="文件大小超过 50MB 限制")

    # 生成唯一存储文件名，避免冲突
    stored_name = f"{uuid.uuid4().hex}.{ext}"
    file_path = os.path.join(UPLOAD_DIR, stored_name)
    with open(file_path, "wb") as f:
        f.write(content)

    # 写入数据库
    record = AgentFile(
        original_name=original_name,
        stored_name=stored_name,
        file_path=file_path,
        file_type=ext,
        file_size=len(content),
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    logger.info("智能体文件上传成功: id=%s, name=%s, type=%s, size=%d",
                record.id, record.original_name, record.file_type, record.file_size)

    return {
        "id": record.id,
        "original_name": record.original_name,
        "stored_name": record.stored_name,
        "file_type": record.file_type,
        "file_size": record.file_size,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


@router.get("")
def list_agent_files(db: Session = Depends(get_db)):
    """列出所有已上传的智能体文件。"""
    records = db.query(AgentFile).order_by(AgentFile.created_at.desc()).all()
    return [
        {
            "id": r.id,
            "original_name": r.original_name,
            "stored_name": r.stored_name,
            "file_type": r.file_type,
            "file_size": r.file_size,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in records
    ]


@router.delete("/{file_id}")
def delete_agent_file(file_id: int, db: Session = Depends(get_db)):
    """删除一个已上传的文件（同时删除磁盘文件）。"""
    record = db.query(AgentFile).filter(AgentFile.id == file_id).first()
    if record is None:
        raise HTTPException(status_code=404, detail="文件不存在")

    # 删除磁盘文件
    try:
        if os.path.exists(record.file_path):
            os.remove(record.file_path)
    except OSError as exc:
        logger.warning("删除磁盘文件失败: %s, error=%s", record.file_path, exc)

    db.delete(record)
    db.commit()
    logger.info("智能体文件已删除: id=%s, name=%s", file_id, record.original_name)
    return {"ok": True, "deleted": file_id}
