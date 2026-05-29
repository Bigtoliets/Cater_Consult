"""CSV/Excel 文件上传 API — 两段式：预览 → 确认导入"""
import traceback
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from io import BytesIO

from app.models import get_db
from app.services.etl import ETLService
from app.services.review_processor import process_new_reviews

router = APIRouter()


def _check_ext(filename: str) -> str:
    """校验文件类型，返回小写扩展名"""
    allowed = {".csv", ".xlsx", ".xls"}
    ext = f".{filename.rsplit('.', 1)[-1].lower()}" if "." in filename else ""
    if ext not in allowed:
        raise HTTPException(status_code=400, detail=f"不支持的文件格式：{ext}，仅支持 CSV / Excel")
    return ext[1:]  # 去掉点号


@router.post("/preview")
async def upload_preview(file: UploadFile = File(...)):
    """步骤 1：上传文件，返回解析后的全量数据预览（不写入数据库）"""
    ext = _check_ext(file.filename)
    try:
        content = await file.read()
        result = await ETLService.preview_file(BytesIO(content), ext)
        return {
            "status": "ok",
            "filename": file.filename,
            **result,
        }
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"文件解析失败：{str(e)}")


class ConfirmBody(BaseModel):
    filename: str
    ext: str
    selected: list[int]  # 用户勾选的行索引 (0-based, 对应数据行)


@router.post("/confirm")
async def upload_confirm(
    file: UploadFile = File(...),
    selected: str = "[]",      # JSON 数组，如 "[0,2,5]"
    db: AsyncSession = Depends(get_db),
):
    """步骤 2：用户勾选确认后，实际写入数据库"""
    import json
    ext = _check_ext(file.filename)
    try:
        indices = json.loads(selected)
        if not indices:
            raise HTTPException(status_code=400, detail="未选择任何行")

        content = await file.read()
        result = await ETLService.import_selected(BytesIO(content), ext, indices, db)

        # 写入后跑预处理（情感分析 + 维度提取 + 风险评分 + 菜品匹配）
        process_result = {"processed": 0}
        if result.get("review_ids"):
            process_result = await process_new_reviews(db, result["review_ids"])

        return {
            "status": "ok",
            "filename": file.filename,
            "imported": result["imported"],
            "processed": process_result.get("processed", 0),
            "errors": result.get("errors", []),
        }
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="selected 参数格式错误，应为 JSON 数组")
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"导入失败：{str(e)}")


@router.get("/template")
async def download_template():
    """下载评价导入模板"""
    return {
        "template_url": "/static/templates/review_import_template.csv",
        "columns": [
            {"name": "raw_text", "required": True, "description": "评价内容"},
            {"name": "stall_name", "required": True, "description": "档口名称"},
            {"name": "dish_name_raw", "required": False, "description": "菜品名称"},
            {"name": "source", "required": False, "description": "评价来源（微信/美团/饿了么/点餐机）"},
            {"name": "rating", "required": False, "description": "评分 1-5"},
            {"name": "meal_time", "required": False, "description": "用餐时段（breakfast/lunch/dinner）"},
            {"name": "reviewed_at", "required": False, "description": "评价时间，格式 YYYY-MM-DD HH:MM:SS"},
        ],
    }
