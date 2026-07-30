"""智能体文件模型。

用于存储用户上传给智能体对话用的原始文件（不做 RAG 切片/向量化）。
智能体通过 ``read_document`` 工具按需读取文件内容。

与知识库文档（KnowledgeDocument）的区别：
- 知识库文档：切片 + 向量索引，走 RAG 检索
- 智能体文件：原样存储，智能体主动调用工具读取全部内容
"""
from sqlalchemy import Column, DateTime, Integer, String, func

from app.database import Base


class AgentFile(Base):
    """智能体对话文件（不做 RAG，原样存储供工具读取）。"""

    __tablename__ = "agent_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 原始文件名（用户上传时的名字，可能含中文/空格）
    original_name = Column(String(512), nullable=False)
    # 存储文件名（唯一，避免冲突；通常是 uuid + 原扩展名）
    stored_name = Column(String(512), nullable=False, unique=True)
    # 服务器上的相对路径（相对于 uploads 目录）
    file_path = Column(String(1024), nullable=False)
    # 文件类型（扩展名，小写）：xlsx / docx / pdf / csv / txt / json / md
    file_type = Column(String(32), nullable=False)
    # 文件大小（字节）
    file_size = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, server_default=func.now())

    def __repr__(self) -> str:
        return f"<AgentFile id={self.id} name={self.original_name!r} type={self.file_type!r}>"
