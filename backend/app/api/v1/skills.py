"""技能（Skill）CRUD 路由。

技能是一段**纯文本指令**（处置流程/角色设定/领域规则/SOP），启用后由
``app/agent/prompt_assembler.py`` 注入到 Agent 的 system prompt，持续塑造
AI 行为。技能不是可调用函数，与 ``tools_manage.py``（code/http 工具）是两类不同实体。

权限：列表/详情需 ``skill:view``，创建/更新需 ``skill:edit``，删除需 ``skill:delete``。
删除技能后，引用它的 Agent（``enabled_skills``）在下次组装 prompt 时通过
``IN`` 查询自然 miss，无需显式清理悬挂引用（惰性清理）。
"""
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, require_permission
from app.models.skill import Skill
from app.models.user import User
from app.schemas.common import to_dict, to_dict_list

logger = logging.getLogger(__name__)

# router 级鉴权：所有技能接口强制登录
router = APIRouter(
    prefix="/skills",
    tags=["skills"],
    dependencies=[Depends(get_current_user)],
)


class SkillBase(BaseModel):
    """技能请求体。"""

    name: str = Field(..., description="技能名称，唯一")
    description: str = Field("", description="简短摘要（列表展示用）")
    content: str = Field(..., description="注入 system prompt 的正文，支持 {{key}} 引用智能体变量")
    category: str | None = Field(None, description="分类：处置流程/角色设定/领域规则/SOP/其他")
    tags: list[str] | None = Field(None, description="自由标签数组")
    enabled: bool = Field(True, description="是否启用（禁用后立即从 Agent prompt 移除）")
    priority: int = Field(0, description="注入顺序，越大越靠前（同优先级按 id 升序）")


@router.get("")
def list_skills(
    category: str | None = Query(None, description="按分类精确筛选"),
    enabled: bool | None = Query(None, description="按启用状态筛选"),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("skill", "view")),
) -> list[dict]:
    """列出所有技能，支持按分类/启用状态筛选。

    排序：``priority`` 降序（注入顺序），同优先级按 ``id`` 升序。
    """
    logger.info("查询技能列表: category=%s, enabled=%s", category, enabled)
    query = db.query(Skill)
    if category is not None:
        query = query.filter(Skill.category == category)
    if enabled is not None:
        query = query.filter(Skill.enabled.is_(enabled))
    skills = query.order_by(Skill.priority.desc(), Skill.id.asc()).all()
    return to_dict_list(skills)


@router.get("/{skill_id:int}")
def get_skill(
    skill_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("skill", "view")),
) -> dict:
    """获取单个技能详情。"""
    logger.info("查询技能详情: id=%s", skill_id)
    skill = db.query(Skill).filter(Skill.id == skill_id).first()
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return to_dict(skill)


@router.post("", status_code=201)
def create_skill(
    body: SkillBase,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("skill", "edit")),
) -> dict:
    """创建技能。

    名称唯一性校验：重名返回 400。
    """
    logger.info("创建技能: name=%s, category=%s", body.name, body.category)
    existing = db.query(Skill).filter(Skill.name == body.name).first()
    if existing is not None:
        raise HTTPException(status_code=400, detail=f"Skill name '{body.name}' already exists")
    skill = Skill(
        name=body.name,
        description=body.description,
        content=body.content,
        category=body.category,
        tags=body.tags or [],
        enabled=body.enabled,
        priority=body.priority,
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    logger.info("技能已创建: id=%s", skill.id)
    return to_dict(skill)


@router.put("/{skill_id:int}")
def update_skill(
    skill_id: int,
    body: SkillBase,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("skill", "edit")),
) -> dict:
    """更新技能。

    名称唯一性校验（排除自身）；启用状态变更即时生效——下次 Agent 组装
    prompt 时通过 ``enabled.is_(True)`` 过滤自动移除/纳入。
    """
    logger.info("更新技能: id=%s", skill_id)
    skill = db.query(Skill).filter(Skill.id == skill_id).first()
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    # 名称唯一性校验（排除自身）
    if body.name != skill.name:
        conflict = db.query(Skill).filter(Skill.name == body.name).first()
        if conflict is not None:
            raise HTTPException(status_code=400, detail=f"Skill name '{body.name}' already exists")
    skill.name = body.name
    skill.description = body.description
    skill.content = body.content
    skill.category = body.category
    skill.tags = body.tags or []
    skill.enabled = body.enabled
    skill.priority = body.priority
    db.commit()
    db.refresh(skill)
    logger.info("技能已更新: id=%s, enabled=%s", skill.id, skill.enabled)
    return to_dict(skill)


@router.delete("/{skill_id:int}")
def delete_skill(
    skill_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("skill", "delete")),
) -> dict:
    """删除技能。

    悬挂引用处理：引用该技能的 Agent（``enabled_skills`` 含此 id）不做显式清理，
    下次组装 prompt 时 ``IN`` 查询自然 miss（惰性清理）。
    """
    logger.info("删除技能: id=%s", skill_id)
    skill = db.query(Skill).filter(Skill.id == skill_id).first()
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    db.delete(skill)
    db.commit()
    logger.info("技能已删除: id=%s", skill_id)
    return {"ok": True}
