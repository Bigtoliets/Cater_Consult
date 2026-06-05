"""CSV/Excel 文件上传 API — 预览 → 确认 → Redis 队列异步分发 Agent"""
import json
import traceback
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from io import BytesIO

from app.models import get_db
from app.services.etl import ETLService
from app.services.review_processor import process_new_reviews, get_dish_review_groups, get_keyword_weights

router = APIRouter()


def _check_ext(filename: str) -> str:
    allowed = {".csv", ".xlsx", ".xls"}
    ext = f".{filename.rsplit('.', 1)[-1].lower()}" if "." in filename else ""
    if ext not in allowed:
        raise HTTPException(status_code=400, detail=f"不支持的文件格式：{ext}，仅支持 CSV / Excel")
    return ext[1:]


@router.post("/preview")
async def upload_preview(file: UploadFile = File(...)):
    ext = _check_ext(file.filename)
    try:
        content = await file.read()
        result = await ETLService.preview_file(BytesIO(content), ext)
        return {"status": "ok", "filename": file.filename, **result}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"文件解析失败：{str(e)}")


class ConfirmBody(BaseModel):
    filename: str
    ext: str
    selected: list[int]


@router.post("/confirm")
async def upload_confirm(
    file: UploadFile = File(...),
    selected: str = "[]",
    db: AsyncSession = Depends(get_db),
):
    ext = _check_ext(file.filename)
    try:
        indices = json.loads(selected)
        if not indices:
            raise HTTPException(status_code=400, detail="未选择任何行")

        content = await file.read()
        result = await ETLService.import_selected(BytesIO(content), ext, indices, db)

        review_ids = result.get("review_ids", [])
        process_result = {"processed": 0, "batch_id": None, "dish_count": 0}

        if review_ids:
            process_result = await process_new_reviews(db, review_ids)

            dish_groups = await get_dish_review_groups(db, review_ids)
            keyword_weights = await get_keyword_weights(db)

            for g in dish_groups.values():
                g["keyword_weights"] = keyword_weights

            if dish_groups:
                from app.tasks.redis_queue import push_dish_batch
                from app.tasks.consumer import process_dish_batch

                groups_list = list(dish_groups.values())
                batch_id = await push_dish_batch(groups_list)

                process_dish_batch.delay(batch_id)

                process_result["batch_id"] = batch_id
                process_result["dish_count"] = len(groups_list)

        return {
            "status": "ok",
            "filename": file.filename,
            "imported": result["imported"],
            "processed": process_result.get("processed", 0),
            "batch_id": process_result.get("batch_id"),
            "dish_count": process_result.get("dish_count", 0),
            "message": f"已下发 {process_result.get('dish_count', 0)} 个菜品到分析队列，Agent 将异步逐条处理",
            "errors": result.get("errors", []),
        }
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="selected 参数格式错误，应为 JSON 数组")
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"导入失败：{str(e)}")


@router.get("/template")
async def download_template():
    return {
        "template_url": "/static/templates/review_import_template.csv",
        "columns": [
            {"name": "raw_text", "required": True, "description": "评价内容"},
            {"name": "dish_name_raw", "required": False, "description": "菜品名称"},
            {"name": "source", "required": False, "description": "评价来源"},
            {"name": "rating", "required": False, "description": "评分 1-5"},
            {"name": "meal_time", "required": False, "description": "用餐时段"},
            {"name": "reviewed_at", "required": False, "description": "评价时间"},
        ],
    }
