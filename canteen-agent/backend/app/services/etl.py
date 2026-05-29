"""ETL 服务：CSV/Excel 解析与导入

CSV 列名直接对应 Review 表字段：
    必填 — raw_text, stall_name
    可选 — reviewed_at, source, dish_name_raw, rating, meal_time
"""
import csv
import io
from datetime import datetime
from typing import IO
import chardet

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Review

# CSV 列名 → Review 表字段名（直连，不绕弯）
_FIELD_MAP = {
    "raw_text":      "raw_text",
    "stall_name":    "stall_name",
    "reviewed_at":   "reviewed_at",
    "source":        "source",
    "dish_name_raw": "dish_name_raw",
    "rating":        "rating",
    "meal_time":     "meal_time",
}

REQUIRED_FIELDS = ["raw_text", "stall_name"]


class ETLService:
    """评价数据 ETL 服务"""

    # ── 公开入口 ──────────────────────────────────────────────

    @classmethod
    async def preview_file(cls, file_io: IO, ext: str) -> dict:
        """仅解析不写入 — 返回全量行数据供前端预览"""
        rows = cls._load_rows(file_io, ext)
        if not rows:
            return {"header": [], "rows": [], "total": 0, "errors": ["文件为空或无法解析"]}

        header = [h.strip() for h in rows[0]]
        col_map = cls._build_col_map(header)
        missing = [f for f in REQUIRED_FIELDS if f not in col_map]
        if missing:
            raise ValueError(f"缺少必填列：{missing}。CSV 表头请使用字段名：raw_text, stall_name 等。")

        parsed = []
        errors = []
        for idx, row in enumerate(rows[1:], start=2):
            try:
                parsed.append(cls._parse_row(row, col_map))
            except ValueError as e:
                errors.append(f"第 {idx} 行：{e}")

        return {
            "header": header,
            "rows": parsed,
            "total": len(parsed),
            "errors": errors,
        }

    @classmethod
    async def import_selected(
        cls, file_io: IO, ext: str, selected_indices: list[int], db: AsyncSession
    ) -> dict:
        """根据用户勾选的行号写入数据库"""
        rows = cls._load_rows(file_io, ext)
        if not rows:
            return {"imported": 0, "errors": ["文件为空"]}

        header = [h.strip() for h in rows[0]]
        col_map = cls._build_col_map(header)
        missing = [f for f in REQUIRED_FIELDS if f not in col_map]
        if missing:
            raise ValueError(f"缺少必填列：{missing}")

        data_rows = rows[1:]
        imported = 0
        errors = []
        new_reviews = []

        for idx in selected_indices:
            if idx < 0 or idx >= len(data_rows):
                errors.append(f"行号 {idx + 2} 超出范围，已跳过")
                continue
            try:
                review_data = cls._parse_row(data_rows[idx], col_map)
                db.add(Review(**review_data))
                new_reviews.append(review_data)
                imported += 1
            except ValueError as e:
                errors.append(f"第 {idx + 2} 行：{e}")

        await db.flush()
        review_ids = [r.id for r in new_reviews if isinstance(r, Review) and r.id is not None]

        return {
            "imported": imported,
            "errors": errors,
            "review_ids": review_ids,
        }

    # ── 文件读取 ───────────────────────────────────────────────

    @classmethod
    def _load_rows(cls, file_io: IO, ext: str) -> list:
        """编码检测 → 解析 CSV/Excel → 返回二维列表"""
        raw_data = file_io.read()
        detected = chardet.detect(raw_data)
        encoding = detected.get("encoding", "utf-8") or "utf-8"

        try:
            text = raw_data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            text = raw_data.decode("utf-8", errors="replace")

        if ext == "csv":
            return cls._parse_csv(text)
        if ext in ("xlsx", "xls"):
            return cls._parse_excel(raw_data, ext)
        raise ValueError(f"不支持的文件格式：{ext}")

    @classmethod
    def _parse_csv(cls, text: str) -> list:
        reader = csv.reader(io.StringIO(text))
        return [row for row in reader if any(cell.strip() for cell in row)]

    @classmethod
    def _parse_excel(cls, raw_data: bytes, ext: str) -> list:
        if ext == "xlsx":
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(raw_data))
        else:
            import xlrd
            wb = xlrd.open_workbook(file_contents=raw_data)

        ws = wb.active if ext == "xlsx" else wb.sheet_by_index(0)
        rows = []
        if ext == "xlsx":
            for row in ws.iter_rows(values_only=True):
                rows.append([str(c) if c is not None else "" for c in row])
        else:
            for r in range(ws.nrows):
                rows.append([str(ws.cell_value(r, c)) for c in range(ws.ncols)])
        return rows

    # ── 内部工具 ───────────────────────────────────────────────

    @classmethod
    def _build_col_map(cls, header: list) -> dict:
        """表头列名 → 列索引。列名必须与 Review 表字段名一致。"""
        col_map = {}
        for i, name in enumerate(header):
            key = name.strip()
            if key in _FIELD_MAP:
                col_map[_FIELD_MAP[key]] = i
        return col_map

    @classmethod
    def _parse_row(cls, row: list, col_map: dict) -> dict:
        """从 CSV 行直接提取 Review 表字段，只做必填校验。"""
        data = {}

        # 必填
        if "raw_text" not in col_map:
            raise ValueError("缺少 raw_text 列")
        data["raw_text"] = row[col_map["raw_text"]].strip()
        if not data["raw_text"]:
            raise ValueError("评价内容为空")

        if "stall_name" not in col_map:
            raise ValueError("缺少 stall_name 列")
        data["stall_name"] = row[col_map["stall_name"]].strip()

        # 可选字段 — 有就取，没有就跳过
        if "dish_name_raw" in col_map:
            data["dish_name_raw"] = row[col_map["dish_name_raw"]].strip()
        if "source" in col_map:
            data["source"] = row[col_map["source"]].strip() or "csv_upload"
        if "rating" in col_map:
            data["rating"] = row[col_map["rating"]].strip()
        if "meal_time" in col_map:
            data["meal_time"] = row[col_map["meal_time"]].strip()
        if "reviewed_at" in col_map:
            data["reviewed_at"] = row[col_map["reviewed_at"]].strip()

        data["is_valid"] = True
        return data
