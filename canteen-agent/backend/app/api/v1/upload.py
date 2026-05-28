"""CSV/Excel 文件上传 API"""
import traceback
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from io import BytesIO

from app.models import get_db
from app.services.etl import ETLService
from app.services.review_processor import process_new_reviews

router = APIRouter()


@router.post("/csv")
async def upload_csv(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """上传 CSV/Excel 评价文件"""
    # 校验文件类型
    allowed_ext = {".csv", ".xlsx", ".xls"}
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if f".{ext}" not in allowed_ext:
        raise HTTPException(status_code=400, detail=f"不支持的文件格式：{ext}，仅支持 CSV / Excel")

    try:
        content = await file.read()
        preview, total_rows, imported, errors, review_ids = await ETLService.process_file(
            BytesIO(content), ext, db
        )

        # 自动触发情感分析和菜品匹配
        process_result = {"processed": 0}
        if review_ids:
            process_result = await process_new_reviews(db, review_ids)

        return {
            "status": "ok",
            "filename": file.filename,
            "total_rows": total_rows,
            "imported": imported,
            "processed": process_result.get("processed", 0),
            "errors": errors,
            "preview": preview[:10],
        }
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"文件处理失败：{str(e)}")


@router.get("/template")
async def download_template():
    """下载评价导入模板"""
    return {
        "template_url": "/static/templates/review_import_template.csv",
        "columns": [
            {"name": "review_time", "required": True, "description": "评价时间，格式 YYYY-MM-DD HH:MM:SS"},
            {"name": "source", "required": False, "description": "评价来源（微信/美团/饿了么/点餐机）"},
            {"name": "stall_name", "required": True, "description": "档口名称"},
            {"name": "dish_name", "required": False, "description": "菜品名称"},
            {"name": "review_text", "required": True, "description": "评价内容"},
            {"name": "rating", "required": False, "description": "评分 1-5"},
            {"name": "meal_time", "required": False, "description": "用餐时段（breakfast/lunch/dinner）"},
        ],
    }
