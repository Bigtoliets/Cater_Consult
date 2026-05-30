"""系统配置 API — 含关键词权重管理 + 双库金标迁移"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Any

from app.models import get_db, SystemConfig, SOPEntry, Dish

router = APIRouter()


class PromoteRequest(BaseModel):
    decision_id: str
    modified_content: str | None = None


@router.post("/promote")
async def promote_to_gold(body: PromoteRequest):
    """将指定 decision_id 从 standard_collection 迁移到 gold_collection（点赞飞升）"""
    try:
        from app.agent.utils.milvus_client import promote_to_gold as do_promote
        result = await do_promote(body.decision_id, body.modified_content)
        return result
    except ImportError:
        raise HTTPException(status_code=500, detail="Milvus 客户端不可用")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"跨库迁移失败：{str(e)}")


class ConfigUpdate(BaseModel):
    config_value: Any
    description: str = ""


class KeywordWeightUpdate(BaseModel):
    weights: dict[str, float]
    description: str = "关键词维度权重配置"


@router.get("/keyword-weights")
async def get_keyword_weights(db: AsyncSession = Depends(get_db)):
    """获取关键词维度权重配置"""
    from app.services.review_processor import DEFAULT_DIMENSION_WEIGHTS
    result = await db.execute(
        select(SystemConfig).where(SystemConfig.config_key == "keyword_weights")
    )
    config = result.scalar_one_or_none()
    if config:
        return {"weights": config.config_value, "defaults": DEFAULT_DIMENSION_WEIGHTS}
    return {"weights": DEFAULT_DIMENSION_WEIGHTS, "defaults": DEFAULT_DIMENSION_WEIGHTS}


@router.put("/keyword-weights")
async def update_keyword_weights(
    body: KeywordWeightUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新关键词维度权重（合并到默认值之上）"""
    from app.services.review_processor import DEFAULT_DIMENSION_WEIGHTS
    merged = {**DEFAULT_DIMENSION_WEIGHTS, **body.weights}

    result = await db.execute(
        select(SystemConfig).where(SystemConfig.config_key == "keyword_weights")
    )
    config = result.scalar_one_or_none()
    if not config:
        config = SystemConfig(
            scope="global",
            config_key="keyword_weights",
            config_value=merged,
            description=body.description,
        )
        db.add(config)
    else:
        config.config_value = merged
        config.description = body.description
    await db.flush()
    return {"status": "ok", "weights": merged}


@router.get("/")
async def list_configs(
    scope: str = "global",
    scope_id: int = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(SystemConfig).where(SystemConfig.scope == scope)
    if scope_id is not None:
        query = query.where(SystemConfig.scope_id == scope_id)
    result = await db.execute(query)
    configs = result.scalars().all()
    return {
        "configs": [
            {
                "id": c.id, "scope": c.scope, "scope_id": c.scope_id,
                "config_key": c.config_key, "config_value": c.config_value,
                "description": c.description,
            }
            for c in configs
        ]
    }


@router.put("/{config_key}")
async def update_config(
    config_key: str,
    body: ConfigUpdate,
    scope: str = "global",
    scope_id: int = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(SystemConfig).where(
        SystemConfig.config_key == config_key,
        SystemConfig.scope == scope,
    )
    if scope_id is not None:
        query = query.where(SystemConfig.scope_id == scope_id)
    result = await db.execute(query)
    config = result.scalar_one_or_none()
    if not config:
        config = SystemConfig(
            scope=scope, scope_id=scope_id,
            config_key=config_key,
            config_value=body.config_value,
            description=body.description,
        )
        db.add(config)
    else:
        config.config_value = body.config_value
        config.description = body.description
    await db.flush()
    return {"status": "ok", "config_key": config_key}


class SOPCreate(BaseModel):
    dish_id: int
    dimension: str
    title: str
    content: str
    metadata_json: dict = {}


@router.get("/knowledge/dish/{dish_id}")
async def get_dish_knowledge(
    dish_id: int,
    dimension: str = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(SOPEntry).where(SOPEntry.dish_id == dish_id)
    if dimension:
        query = query.where(SOPEntry.dimension == dimension)
    result = await db.execute(query)
    entries = result.scalars().all()
    return {
        "dish_id": dish_id,
        "entries": [
            {"id": e.id, "dimension": e.dimension, "title": e.title,
             "content": e.content, "metadata_json": e.metadata_json, "created_at": str(e.created_at)}
            for e in entries
        ],
    }


@router.post("/knowledge")
async def create_sop_entry(body: SOPCreate, db: AsyncSession = Depends(get_db)):
    dish_result = await db.execute(select(Dish).where(Dish.id == body.dish_id))
    if not dish_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="菜品不存在")
    entry = SOPEntry(
        dish_id=body.dish_id, dimension=body.dimension,
        title=body.title, content=body.content, metadata_json=body.metadata_json,
    )
    db.add(entry)
    await db.flush()
    return {"status": "ok", "id": entry.id}


@router.delete("/knowledge/{entry_id}")
async def delete_sop_entry(entry_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SOPEntry).where(SOPEntry.id == entry_id))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="条目不存在")
    await db.delete(entry)
    await db.flush()
    return {"status": "ok"}
