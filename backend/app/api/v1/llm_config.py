"""LLM 配置 CRUD 路由 + 模型监控统计。"""
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_role
from app.models.llm_config import LLMConfig
from app.models.model_call_log import ModelCallLog
from app.schemas.common import to_dict, to_dict_list
from app.core.llm_helper import clean_base_url

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/llm-configs",
    tags=["llm-configs"],
    dependencies=[Depends(require_role("admin"))],
)


class LLMConfigBase(BaseModel):
    """LLM 配置请求体。"""

    name: str = Field(..., description="配置名称")
    provider: str = Field("anthropic", description="供应商，如 anthropic/openai")
    api_key: str = Field("", description="API Key")
    base_url: str = Field("", description="自定义 Base URL，可空")
    model_name: str = Field("", description="模型名，如 claude-3-5-sonnet-20241022")
    model_type: str = Field("chat", description="模型类型：chat（对话）/ embedding（向量化）")
    is_default: bool = Field(False, description="是否设为默认模型")


def _set_default(db: Session, config_id: int) -> None:
    """将指定配置设为默认，其余取消默认。"""
    db.query(LLMConfig).filter(LLMConfig.is_default.is_(True)).update({LLMConfig.is_default: False})
    db.query(LLMConfig).filter(LLMConfig.id == config_id).update({LLMConfig.is_default: True})


@router.get("")
def list_llm_configs(db: Session = Depends(get_db)) -> list[dict]:
    """列出所有 LLM 配置。"""
    logger.info("查询 LLM 配置列表")
    configs = db.query(LLMConfig).order_by(LLMConfig.created_at.desc()).all()
    return to_dict_list(configs)


@router.post("", status_code=201)
def create_llm_config(body: LLMConfigBase, db: Session = Depends(get_db)) -> dict:
    """创建 LLM 配置。"""
    logger.info("创建 LLM 配置: name=%s, provider=%s", body.name, body.provider)
    config = LLMConfig(
        name=body.name,
        provider=body.provider,
        api_key=body.api_key,
        base_url=body.base_url,
        model_name=body.model_name,
        model_type=body.model_type,
        is_default=body.is_default,
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    if body.is_default:
        _set_default(db, config.id)
        db.commit()
        db.refresh(config)
    logger.info("LLM 配置已创建: id=%s", config.id)
    return to_dict(config)


@router.put("/{config_id}")
def update_llm_config(
    config_id: int, body: LLMConfigBase, db: Session = Depends(get_db)
) -> dict:
    """更新 LLM 配置。"""
    logger.info("更新 LLM 配置: id=%s", config_id)
    config = db.query(LLMConfig).filter(LLMConfig.id == config_id).first()
    if config is None:
        raise HTTPException(status_code=404, detail="LLMConfig not found")
    config.name = body.name
    config.provider = body.provider
    config.api_key = body.api_key
    config.base_url = body.base_url
    config.model_name = body.model_name
    config.model_type = body.model_type
    config.is_default = body.is_default
    db.commit()
    if body.is_default:
        _set_default(db, config.id)
        db.commit()
    db.refresh(config)
    logger.info("LLM 配置已更新: id=%s", config.id)
    return to_dict(config)


@router.delete("/{config_id}")
def delete_llm_config(config_id: int, db: Session = Depends(get_db)) -> dict:
    """删除 LLM 配置。"""
    logger.info("删除 LLM 配置: id=%s", config_id)
    config = db.query(LLMConfig).filter(LLMConfig.id == config_id).first()
    if config is None:
        raise HTTPException(status_code=404, detail="LLMConfig not found")
    db.delete(config)
    db.commit()
    logger.info("LLM 配置已删除: id=%s", config_id)
    return {"ok": True}


@router.post("/{config_id}/test", summary="测试 LLM 配置连通性")
def test_llm_config(config_id: int, db: Session = Depends(get_db)) -> dict:
    """发送一条简单消息测试 LLM 配置是否可用。

    支持 Anthropic 原生 API 和 OpenAI 兼容接口（含国内厂商如火山引擎、Deepseek、Moonshot 等）。
    测试结果同步记录到 ``model_call_logs``（trigger_type=manual_test），供监控页统计。
    """
    logger.info("测试 LLM 配置连通性: id=%s", config_id)
    cfg = db.query(LLMConfig).filter(LLMConfig.id == config_id).first()
    if cfg is None:
        raise HTTPException(status_code=404, detail="配置不存在")
    try:
        provider = (cfg.provider or "anthropic").lower()
        # 清理 api_key：去除首尾空白与换行（常见于复制粘贴引入）
        api_key = (cfg.api_key or "").strip()
        if not api_key:
            return {"success": False,
                    "error": "API Key 为空，请在配置中填写有效的 API Key",
                    "model": cfg.model_name}

        # ===== Embedding 模型测试：走 /embeddings 端点（非 chat completions）=====
        if (cfg.model_type or "chat").lower() == "embedding":
            import httpx
            import re
            import time
            from app.core.model_call_monitor import record_model_call

            base = clean_base_url(cfg.base_url or "https://api.openai.com/v1")
            if base.endswith("/embeddings/multimodal"):
                regular_url = base[: -len("/multimodal")]
            elif base.endswith("/embeddings"):
                regular_url = base
            elif re.search(r"/v\d+$", base):
                regular_url = f"{base}/embeddings"
            else:
                regular_url = f"{base}/v1/embeddings"
            multimodal_url = regular_url + "/multimodal"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            model_name = cfg.model_name or "text-embedding-ada-002"
            t0 = time.monotonic()
            try:
                with httpx.Client(timeout=30) as client:
                    # 先尝试常规 /embeddings（支持批量）
                    payload = {"model": model_name, "input": ["连通性测试"]}
                    r = client.post(regular_url, json=payload, headers=headers)

                    if r.status_code == 400 and "does not support this api" in r.text:
                        # 多模态 embedding 模型 → 切换到 /embeddings/multimodal
                        logger.info("检测到多模态 embedding 模型，切换到 /embeddings/multimodal")
                        mm_payload = {
                            "model": model_name,
                            "input": [{"type": "text", "text": "连通性测试"}],
                            "encoding_format": "float",
                        }
                        r = client.post(multimodal_url, json=mm_payload, headers=headers)

                    latency_ms = int((time.monotonic() - t0) * 1000)
                    if r.status_code != 200:
                        record_model_call(
                            model_config_id=cfg.id, model_name=cfg.model_name, provider=provider,
                            status="failed", latency_ms=latency_ms,
                            error_message=f"HTTP {r.status_code}: {r.text[:400]}",
                            trigger_type="manual_test",
                        )
                        return {"success": False,
                                "error": f"HTTP {r.status_code}: {r.text[:400]}",
                                "model": cfg.model_name}
                    data = r.json()
                    # 兼容两种响应格式：
                    # 常规：{"data": [{"embedding": [...]}], "usage": {...}}
                    # 多模态：{"data": {"embedding": [...]}}
                    raw_data = data.get("data", [])
                    if isinstance(raw_data, list) and raw_data:
                        emb = raw_data[0].get("embedding") or []
                    elif isinstance(raw_data, dict):
                        emb = raw_data.get("embedding") or []
                    else:
                        emb = []
                    usage = data.get("usage", {}) or {}
                    record_model_call(
                        model_config_id=cfg.id, model_name=cfg.model_name, provider=provider,
                        status="success", latency_ms=latency_ms,
                        input_tokens=usage.get("prompt_tokens"),
                        output_tokens=usage.get("completion_tokens"),
                        trigger_type="manual_test",
                    )
                    logger.info("Embedding 配置测试成功: id=%s, dim=%s", config_id, len(emb))
                    return {"success": True,
                            "response": f"向量维度: {len(emb)}",
                            "model": cfg.model_name}
            except Exception as http_exc:  # noqa: BLE001
                latency_ms = int((time.monotonic() - t0) * 1000)
                record_model_call(
                    model_config_id=cfg.id, model_name=cfg.model_name, provider=provider,
                    status="failed", latency_ms=latency_ms,
                    error_message=str(http_exc)[:500],
                    trigger_type="manual_test",
                )
                return {"success": False, "error": str(http_exc)[:500], "model": cfg.model_name}

        if provider == "anthropic":
            # Anthropic 原生 API
            from langchain_anthropic import ChatAnthropic
            from langchain_core.messages import HumanMessage

            llm_kwargs = {
                "model": cfg.model_name or "claude-3-5-sonnet-20241022",
                "api_key": api_key,
                "max_tokens": 50,
            }
            if cfg.base_url:
                llm_kwargs["anthropic_api_url"] = cfg.base_url
            llm = ChatAnthropic(**llm_kwargs)
            from app.core.model_call_monitor import ModelCallTimer

            with ModelCallTimer(
                model_config_id=cfg.id, model_name=cfg.model_name, provider=provider,
                trigger_type="manual_test",
            ) as timer:
                resp = llm.invoke([HumanMessage(content="回复OK两个字")])
                timer.set_response(resp)
            logger.info("LLM 配置测试成功(anthropic): id=%s", config_id)
            return {"success": True, "response": str(resp.content)[:200], "model": cfg.model_name}

        # OpenAI 兼容接口（openai / 火山引擎 / Deepseek / Moonshot / Zhipu 等）
        import httpx
        import re

        # 构造请求 URL：兼容多种 base_url 写法
        base = clean_base_url(cfg.base_url or "https://api.openai.com/v1")
        if base.endswith("/chat/completions"):
            url = base
        elif re.search(r"/v\d+$", base):
            url = f"{base}/chat/completions"
        else:
            url = f"{base}/v1/chat/completions"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": cfg.model_name or "gpt-3.5-turbo",
            "messages": [{"role": "user", "content": "回复OK两个字"}],
            "max_tokens": 50,
        }
        import time

        from app.core.model_call_monitor import record_model_call

        t0 = time.monotonic()
        try:
            with httpx.Client(timeout=30) as client:
                r = client.post(url, json=payload, headers=headers)
            latency_ms = int((time.monotonic() - t0) * 1000)
            if r.status_code != 200:
                logger.warning("LLM 配置测试失败(openai-compat): id=%s, status=%s, body=%s",
                               config_id, r.status_code, r.text[:300])
                record_model_call(
                    model_config_id=cfg.id, model_name=cfg.model_name, provider=provider,
                    status="failed", latency_ms=latency_ms,
                    error_message=f"HTTP {r.status_code}: {r.text[:400]}",
                    trigger_type="manual_test",
                )
                return {"success": False,
                        "error": f"HTTP {r.status_code}: {r.text[:400]}",
                        "model": cfg.model_name}
            data = r.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            # 提取 token 用量
            usage = data.get("usage", {}) or {}
            record_model_call(
                model_config_id=cfg.id, model_name=cfg.model_name, provider=provider,
                status="success", latency_ms=latency_ms,
                input_tokens=usage.get("prompt_tokens"),
                output_tokens=usage.get("completion_tokens"),
                trigger_type="manual_test",
            )
            logger.info("LLM 配置测试成功(openai-compat): id=%s", config_id)
            return {"success": True, "response": content[:200], "model": cfg.model_name}
        except Exception as http_exc:  # noqa: BLE001
            latency_ms = int((time.monotonic() - t0) * 1000)
            record_model_call(
                model_config_id=cfg.id, model_name=cfg.model_name, provider=provider,
                status="failed", latency_ms=latency_ms,
                error_message=str(http_exc)[:500],
                trigger_type="manual_test",
            )
            raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM 配置测试失败: id=%s, error=%s", config_id, exc)
        return {"success": False, "error": str(exc)[:500]}


# ============ 模型监控统计 ============

@router.get("/monitor/stats", summary="模型调用监控统计")
def get_model_call_stats(
    days: int = Query(7, ge=1, le=90, description="统计最近 N 天"),
    db: Session = Depends(get_db),
) -> dict:
    """模型调用监控统计：按模型配置聚合调用次数、成功率、平均耗时、Token 用量。

    返回每个 LLMConfig 的汇总统计 + 未关联配置的调用（孤儿记录）。
    """
    since = datetime.now() - timedelta(days=days)
    logger.info("查询模型调用统计: days=%s", days)

    # 按model_config_id聚合统计
    rows = (
        db.query(
            ModelCallLog.model_config_id,
            func.count(ModelCallLog.id).label("total"),
            func.sum(case((ModelCallLog.status == "success", 1), else_=0)).label("success"),
            func.sum(case((ModelCallLog.status == "failed", 1), else_=0)).label("failed"),
            func.avg(ModelCallLog.latency_ms).label("avg_latency_ms"),
            func.max(ModelCallLog.latency_ms).label("max_latency_ms"),
            func.sum(ModelCallLog.input_tokens).label("total_input_tokens"),
            func.sum(ModelCallLog.output_tokens).label("total_output_tokens"),
            func.sum(ModelCallLog.total_tokens).label("total_tokens"),
        )
        .filter(ModelCallLog.created_at >= since)
        .group_by(ModelCallLog.model_config_id)
        .all()
    )

    # 加载所有配置（含名称，便于前端展示）
    configs = {c.id: c for c in db.query(LLMConfig).all()}
    # 获取最近调用时间
    last_call_rows = (
        db.query(
            ModelCallLog.model_config_id,
            func.max(ModelCallLog.created_at).label("last_call_at"),
        )
        .filter(ModelCallLog.created_at >= since)
        .group_by(ModelCallLog.model_config_id)
        .all()
    )
    last_call_map = {r.model_config_id: r.last_call_at for r in last_call_rows}

    stats = []
    for r in rows:
        cfg = configs.get(r.model_config_id) if r.model_config_id else None
        total = int(r.total or 0)
        success = int(r.success or 0)
        stats.append({
            "model_config_id": r.model_config_id,
            "config_name": cfg.name if cfg else "(已删除配置)",
            "model_name": cfg.model_name if cfg else "",
            "provider": cfg.provider if cfg else "",
            "total_calls": total,
            "success": success,
            "failed": int(r.failed or 0),
            "success_rate": round(success / total, 4) if total > 0 else 0.0,
            "avg_latency_ms": round(float(r.avg_latency_ms or 0), 1),
            "max_latency_ms": int(r.max_latency_ms or 0),
            "total_input_tokens": int(r.total_input_tokens or 0),
            "total_output_tokens": int(r.total_output_tokens or 0),
            "total_tokens": int(r.total_tokens or 0),
            "last_call_at": last_call_map.get(r.model_config_id).isoformat()
            if last_call_map.get(r.model_config_id)
            else None,
        })

    # 按总调用数降序
    stats.sort(key=lambda s: s["total_calls"], reverse=True)
    return {"days": days, "stats": stats}


@router.get("/{config_id}/monitor/calls", summary="模型最近调用明细")
def get_model_call_logs(
    config_id: int,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    """查询单个模型配置的最近调用明细。"""
    logger.info("查询模型调用明细: config_id=%s, limit=%s, offset=%s", config_id, limit, offset)
    q = (
        db.query(ModelCallLog)
        .filter(ModelCallLog.model_config_id == config_id)
        .order_by(ModelCallLog.created_at.desc())
    )
    total = q.count()
    rows = q.offset(offset).limit(limit).all()
    return {
        "total": total,
        "calls": [
            {
                "id": r.id,
                "status": r.status,
                "latency_ms": r.latency_ms,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "total_tokens": r.total_tokens,
                "trigger_type": r.trigger_type,
                "agent_id": r.agent_id,
                "error_message": r.error_message,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }
