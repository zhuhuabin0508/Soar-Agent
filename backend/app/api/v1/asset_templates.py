"""资产类型模板 API。

提供资产类型模板的 CRUD 端点，支持：
- 列出所有模板（按 sort_order 排序）
- 获取单个模板详情
- 创建自定义模板
- 更新模板（预设模板可改 name/fields/icon/color/identifier_field/description，不可改 code）
- 删除模板（预设模板不可删除）

模板定义了某一类资产的数据模型（字段 schema + 元信息），
资产管理页面的表单、列表列、导入/导出均按模板动态适配。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.dependencies import require_role
from app.database import get_db
from app.models.asset import AssetTypeTemplate
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/asset-templates", tags=["asset-templates"])


# ============================================================================
# 请求/响应模型
# ============================================================================

class TemplateFieldDef(BaseModel):
    """模板字段定义。"""
    key: str = Field(..., description="字段键名（英文）")
    label: str = Field(..., description="显示标签（中文）")
    type: str = Field("text", description="字段类型：text/number/date/select/textarea/ip/cidr")
    mapped_to: str = Field("extra", description="映射目标：extra 或 standard:<col>")
    required: bool = Field(False, description="是否必填")
    unique: bool = Field(False, description="是否参与唯一性校验（标识字段为 true）")
    options: list[str] | None = Field(None, description="select 类型的选项列表")
    placeholder: str = Field("", description="输入框占位提示")
    default: str = Field("", description="默认值")
    width: str = Field("half", description="表单布局宽度：half/full")
    sort_order: int = Field(0, description="排序权重")
    show_in_list: bool = Field(True, description="是否在列表中显示为列")
    show_in_detail: bool = Field(True, description="是否在详情中显示")


class TemplateCreateRequest(BaseModel):
    """创建模板请求体。"""
    code: str = Field(..., min_length=2, max_length=64, description="模板代码（唯一）")
    name: str = Field(..., min_length=1, max_length=64, description="模板名称")
    description: str = Field("", description="模板描述")
    icon: str = Field("server", description="lucide 图标名")
    color: str = Field("chart-1", description="主题色令牌")
    identifier_field: str = Field("ip", description="用作唯一标识的字段 key")
    fields: list[TemplateFieldDef] = Field(..., description="字段定义列表")
    allow_aggregate: bool = Field(
        False,
        description="是否允许标识聚合：开启后同一标识（如网段）允许不同使用单位共存，"
        "列表中按标识分组展开显示；关闭时标识全局唯一",
    )


class TemplateUpdateRequest(BaseModel):
    """更新模板请求体。所有字段可选。"""
    name: str | None = None
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    identifier_field: str | None = None
    fields: list[TemplateFieldDef] | None = None
    allow_aggregate: bool | None = None


# ============================================================================
# 辅助函数
# ============================================================================

def _template_to_dict(tpl: AssetTypeTemplate) -> dict:
    """序列化模板为字典。"""
    return {
        "id": tpl.id,
        "code": tpl.code,
        "name": tpl.name,
        "description": tpl.description or "",
        "icon": tpl.icon,
        "color": tpl.color,
        "identifier_field": tpl.identifier_field,
        "fields": tpl.fields or [],
        "is_preset": tpl.is_preset,
        "allow_aggregate": bool(tpl.allow_aggregate) if tpl.allow_aggregate is not None else False,
        "sort_order": tpl.sort_order,
        "created_at": tpl.created_at.isoformat() if tpl.created_at else None,
        "updated_at": tpl.updated_at.isoformat() if tpl.updated_at else None,
    }


# ============================================================================
# 端点
# ============================================================================

@router.get("")
def list_templates(
    db: Session = Depends(get_db),
) -> list[dict]:
    """列出所有资产类型模板（按 sort_order 排序）。"""
    templates = db.query(AssetTypeTemplate).order_by(
        AssetTypeTemplate.sort_order.asc(),
        AssetTypeTemplate.id.asc(),
    ).all()
    return [_template_to_dict(t) for t in templates]


@router.get("/{code}")
def get_template(
    code: str,
    db: Session = Depends(get_db),
) -> dict:
    """获取单个模板详情。"""
    tpl = db.query(AssetTypeTemplate).filter_by(code=code).first()
    if tpl is None:
        raise HTTPException(status_code=404, detail=f"模板不存在: {code}")
    return _template_to_dict(tpl)


@router.post("", status_code=201)
def create_template(
    body: TemplateCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin", "analyst")),
) -> dict:
    """创建自定义资产类型模板。

    - code 必须唯一，且不能与预设模板冲突
    - fields 中必须有至少一个字段
    - identifier_field 必须在 fields 中存在
    """
    # 查重
    existing = db.query(AssetTypeTemplate).filter_by(code=body.code).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"模板代码已存在: {body.code}")

    # 校验 identifier_field 在 fields 中
    field_keys = {f.key for f in body.fields}
    if body.identifier_field not in field_keys:
        raise HTTPException(
            status_code=422,
            detail=f"identifier_field '{body.identifier_field}' 不在 fields 中",
        )

    tpl = AssetTypeTemplate(
        code=body.code,
        name=body.name,
        description=body.description,
        icon=body.icon,
        color=body.color,
        identifier_field=body.identifier_field,
        fields=[f.model_dump() for f in body.fields],
        is_preset=False,
        allow_aggregate=bool(body.allow_aggregate),
        sort_order=db.query(AssetTypeTemplate).count() + 10,  # 自定义排预设后面
    )
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    logger.info("创建资产类型模板: code=%s, name=%s, user=%s", tpl.code, tpl.name, user.username)
    return _template_to_dict(tpl)


@router.put("/{code}")
def update_template(
    code: str,
    body: TemplateUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin", "analyst")),
) -> dict:
    """更新模板。

    预设模板（is_preset=True）：
    - 可修改 name/fields/icon/color/identifier_field/description
    - 不可修改 code
    自定义模板：所有字段均可修改（除 code）。
    """
    tpl = db.query(AssetTypeTemplate).filter_by(code=code).first()
    if tpl is None:
        raise HTTPException(status_code=404, detail=f"模板不存在: {code}")

    if tpl.is_preset:
        # 预设模板：code 不可改，其余字段均可改
        if body.name is not None:
            tpl.name = body.name
        if body.description is not None:
            tpl.description = body.description
        if body.icon is not None:
            tpl.icon = body.icon
        if body.color is not None:
            tpl.color = body.color
        if body.identifier_field is not None:
            # 校验 identifier_field 在 fields 中
            if body.fields is not None:
                field_keys = {f.key for f in body.fields}
            else:
                field_keys = {f["key"] for f in (tpl.fields or [])}
            if body.identifier_field not in field_keys:
                raise HTTPException(
                    status_code=422,
                    detail=f"identifier_field '{body.identifier_field}' 不在 fields 中",
                )
            tpl.identifier_field = body.identifier_field
        if body.fields is not None:
            tpl.fields = [f.model_dump() for f in body.fields]
    else:
        # 自定义模板：可修改除 code 外的所有字段
        if body.name is not None:
            tpl.name = body.name
        if body.description is not None:
            tpl.description = body.description
        if body.icon is not None:
            tpl.icon = body.icon
        if body.color is not None:
            tpl.color = body.color
        if body.identifier_field is not None:
            if body.fields is not None:
                field_keys = {f.key for f in body.fields}
            else:
                field_keys = {f["key"] for f in (tpl.fields or [])}
            if body.identifier_field not in field_keys:
                raise HTTPException(
                    status_code=422,
                    detail=f"identifier_field '{body.identifier_field}' 不在 fields 中",
                )
            tpl.identifier_field = body.identifier_field
        if body.fields is not None:
            tpl.fields = [f.model_dump() for f in body.fields]

    # allow_aggregate 开关：预设和自定义模板均可修改
    if body.allow_aggregate is not None:
        new_val = bool(body.allow_aggregate)
        if tpl.allow_aggregate != new_val:
            tpl.allow_aggregate = new_val
            logger.info(
                "模板 %s allow_aggregate 切换为 %s（注意：从聚合切回唯一时，"
                "已有同标识不同部门的记录不会被自动合并，需手动处理）",
                code, new_val,
            )

    db.commit()
    db.refresh(tpl)
    logger.info("更新资产类型模板: code=%s, user=%s", code, user.username)
    return _template_to_dict(tpl)


@router.delete("/{code}")
def delete_template(
    code: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin", "analyst")),
) -> dict:
    """删除模板。

    预设模板（is_preset=True）不可删除，返回 403。
    删除模板不影响已关联的资产数据（资产的 type_code 保留，只是不再有模板定义）。
    """
    tpl = db.query(AssetTypeTemplate).filter_by(code=code).first()
    if tpl is None:
        raise HTTPException(status_code=404, detail=f"模板不存在: {code}")
    if tpl.is_preset:
        raise HTTPException(status_code=403, detail="预设模板不可删除")

    db.delete(tpl)
    db.commit()
    logger.info("删除资产类型模板: code=%s, user=%s", code, user.username)
    return {"ok": True, "deleted": code}
