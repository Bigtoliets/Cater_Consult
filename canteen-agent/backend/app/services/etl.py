"""ETL 服务：CSV/Excel 解析与导入

CSV 列名直接对应 Review 表字段：
    必填 — raw_text
    可选 — dish_name_raw, reviewed_at, source, rating, meal_time
"""
import csv
import io
from datetime import datetime
from typing import IO
import chardet

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Review

_FIELD_MAP = {
    "raw_text":      "raw_text",
    "dish_name_raw": "dish_name_raw",
    "reviewed_at":   "reviewed_at",
    "source":        "source",
    "rating":        "rating",
    "meal_time":     "meal_time",
}

# 中文列名别名（兼容中文 Excel 导出的表头）
_CN_ALIASES = {
    "评价内容": "raw_text",
    "评论内容": "raw_text",
    "评价文本": "raw_text",
    "菜品名称": "dish_name_raw",
    "菜品名":   "dish_name_raw",
    "评价来源": "source",
    "来源":     "source",
    "评分":     "rating",
    "用餐时段": "meal_time",
    "时段":     "meal_time",
    "评价时间": "reviewed_at",
    "时间":     "reviewed_at",
}

REQUIRED_FIELDS = ["raw_text"]


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
            raise ValueError(
                f"缺少必填列：{missing}。当前表头为：{header}。"
                f"请使用英文列名 raw_text / dish_name_raw，或中文列名 评价内容 / 菜品名称 等。"
            )

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
            raise ValueError(
                f"缺少必填列：{missing}。当前表头为：{header}。"
                f"请使用英文列名 raw_text / dish_name_raw，或中文列名 评价内容 / 菜品名称 等。"
            )

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
                review = Review(**review_data)
                db.add(review)
                new_reviews.append(review)
                imported += 1
            except ValueError as e:
                errors.append(f"第 {idx + 2} 行：{e}")

        await db.flush()
        review_ids = [r.id for r in new_reviews if r.id is not None]

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

        # \u4f18\u5148\u5c1d\u8bd5\u5e38\u89c1\u4e2d\u6587\u7f16\u7801\uff08chardet \u5bf9\u77ed\u6587\u672c/\u6df7\u5408\u5185\u5bb9\u5bb9\u6613\u8bef\u5224\uff09
        text = None
        for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk", "gb2312"):
            try:
                text = raw_data.decode(enc)
                break
            except (UnicodeDecodeError, LookupError):
                continue

        if text is None:
            detected = chardet.detect(raw_data)
            encoding = detected.get("encoding", "utf-8") or "utf-8"
            try:
                text = raw_data.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                text = raw_data.decode("utf-8", errors="replace")

        # \u53bb\u6389 BOM\uff08utf-8-sig \u5df2\u81ea\u52a8\u53bb\u9664\uff0c\u6b64\u5904\u515c\u5e95\uff09
        if text and ord(text[0]) == 0xFEFF:
            text = text[1:]

        if ext == "csv":
            return cls._parse_csv(text)
        if ext in ("xlsx", "xls"):
            return cls._parse_excel(raw_data, ext)
        raise ValueError(f"不支持的文件格式：{ext}")

    @classmethod
    def _parse_csv(cls, text: str) -> list:
        delimiters = ["\t", ",", "|", ";"]
        best_rows = []
        best_cols = 0

        for delim in delimiters:
            try:
                reader = csv.reader(io.StringIO(text), delimiter=delim)
                rows = [row for row in reader if any(cell.strip() for cell in row)]
                if not rows:
                    continue
                col_count = len(rows[0])
                if col_count > best_cols:
                    best_cols = col_count
                    best_rows = rows
            except Exception:
                continue

        if not best_rows:
            try:
                dialect = csv.Sniffer().sniff(text[:4096])
                reader = csv.reader(io.StringIO(text), dialect)
                best_rows = [row for row in reader if any(cell.strip() for cell in row)]
            except Exception:
                reader = csv.reader(io.StringIO(text))
                best_rows = [row for row in reader if any(cell.strip() for cell in row)]

        return best_rows

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
        """表头列名 → 列索引。支持英文列名和中文别名。"""
        col_map = {}
        for i, name in enumerate(header):
            key = name.strip()
            # 去掉 BOM 字符
            while key and ord(key[0]) == 0xFEFF:
                key = key[1:]
            if key in _FIELD_MAP:
                col_map[_FIELD_MAP[key]] = i
            elif key in _CN_ALIASES:
                col_map[_CN_ALIASES[key]] = i
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

        if "stall_name" in col_map:
            data["stall_name"] = row[col_map["stall_name"]].strip()

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
        if not data.get("reviewed_at"):
            data["reviewed_at"] = datetime.now()
        return data
