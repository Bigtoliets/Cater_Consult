"""店铺 API —— 店铺列表 / 新增 / 店铺下菜品"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import get_db, Shop, Dish

router = APIRouter()


class ShopCreate(BaseModel):
    name: str
    address: str = ""


@router.get("")
async def list_shops(db: AsyncSession = Depends(get_db)):
    """店铺列表"""
    result = await db.execute(select(Shop).order_by(Shop.id))
    shops = result.scalars().all()
    return {
        "shops": [
            {
                "id": s.id,
                "name": s.name,
                "address": s.address,
                "is_active": s.is_active,
            }
            for s in shops
        ]
    }


@router.post("")
async def create_shop(body: ShopCreate, db: AsyncSession = Depends(get_db)):
    """新增店铺"""
    shop = Shop(name=body.name, address=body.address)
    db.add(shop)
    await db.flush()
    return {"status": "ok", "id": shop.id, "name": shop.name}


@router.get("/{shop_id}/dishes")
async def list_shop_dishes(shop_id: int, db: AsyncSession = Depends(get_db)):
    """某店铺下的菜品"""
    shop_result = await db.execute(select(Shop).where(Shop.id == shop_id))
    if not shop_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="店铺不存在")

    result = await db.execute(select(Dish).where(Dish.shop_id == shop_id))
    dishes = result.scalars().all()
    return {
        "shop_id": shop_id,
        "dishes": [
            {"id": d.id, "name": d.name, "category": d.category, "price": d.price}
            for d in dishes
        ],
    }
