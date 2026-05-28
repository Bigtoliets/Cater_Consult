"""ETL 服务：CSV/Excel 解析与导入"""
import csv
import io
from datetime import datetime
from typing import IO
import chardet

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Review


class ETLService:
    """评价数据 ETL 服务"""

    # 列名映射（支持中英文列名）
    COLUMN_MAP = {
        "评价时间": "review_time", "review_time": "review_time",
        "来源": "source", "source": "source",
        "档口名称": "stall_name", "stall_name": "stall_name",
        "菜品名称": "dish_name", "dish_name": "dish_name",
        "评价内容": "review_text", "review_text": "review_text",
        "评分": "rating", "rating": "rating",
        "用餐时段": "meal_time", "meal_time": "meal_time",
    }

    @classmethod
    async def process_file(
        cls, file_io: IO, ext: str, db: AsyncSession
    ) -> tuple:
        """
        处理上传文件
        返回: (preview, total_rows, imported, errors, review_ids)
        """
        # 检测编码
        raw_data = file_io.read()
        detected = chardet.detect(raw_data)
        encoding = detected.get("encoding", "utf-8") or "utf-8"

        try:
            text = raw_data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            text = raw_data.decode("utf-8", errors="replace")

        if ext == "csv":
            rows = cls._parse_csv(text)
        elif ext in ("xlsx", "xls"):
            rows = cls._parse_excel(raw_data, ext)
        else:
            raise ValueError(f"不支持的文件格式：{ext}")

        if not rows:
            return [], 0, 0, ["文件为空或无法解析"], []

        # 解析表头
        header = rows[0]
        col_map = {}
        for i, col_name in enumerate(header):
            mapped = cls.COLUMN_MAP.get(col_name.strip(), col_name.strip())
            col_map[mapped] = i

        # 校验必填字段
        required_fields = ["review_text", "stall_name"]
        missing = [f for f in required_fields if f not in col_map]
        if missing:
            raise ValueError(f"缺少必填列：{missing}。请使用模板文件。")

        # 导入数据
        data_rows = rows[1:]
        imported = 0
        errors = []
        preview = []
        new_reviews = []

        for idx, row in enumerate(data_rows):
            try:
                review_data = cls._parse_row(row, col_map, idx + 2)
                review = Review(**review_data)
                db.add(review)
                new_reviews.append(review)
                imported += 1

                if idx < 10:
                    preview.append(review_data)
            except Exception as e:
                errors.append(f"第 {idx + 2} 行：{str(e)}")

        await db.flush()

        # flush 后 ID 已生成，收集 IDs
        review_ids = [r.id for r in new_reviews if r.id is not None]

        return preview, len(data_rows), imported, errors, review_ids

    @classmethod
    def _parse_csv(cls, text: str) -> list:
        """解析 CSV 文本"""
        reader = csv.reader(io.StringIO(text))
        return [row for row in reader if any(cell.strip() for cell in row)]

    @classmethod
    def _parse_excel(cls, raw_data: bytes, ext: str) -> list:
        """解析 Excel"""
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

    @classmethod
    def _parse_row(cls, row: list, col_map: dict, line_no: int) -> dict:
        """解析单行数据"""
        data = {}

        if "review_text" in col_map:
            data["raw_text"] = row[col_map["review_text"]].strip()
        if "stall_name" in col_map:
            data["stall_name"] = row[col_map["stall_name"]].strip()
        if "dish_name" in col_map:
            data["dish_name_raw"] = row[col_map["dish_name"]].strip()
        if "source" in col_map:
            data["source"] = row[col_map["source"]].strip() or "csv_upload"
        else:
            data["source"] = "csv_upload"

        if "rating" in col_map:
            try:
                data["rating"] = int(float(row[col_map["rating"]]))
            except (ValueError, IndexError):
                data["rating"] = 3

        if "meal_time" in col_map:
            mt = row[col_map["meal_time"]].strip().lower()
            valid_times = {"breakfast", "lunch", "dinner", "早", "中", "晚"}
            time_map = {"早": "breakfast", "中": "lunch", "晚": "dinner"}
            data["meal_time"] = time_map.get(mt, mt if mt in valid_times else "lunch")

        if "review_time" in col_map:
            try:
                data["reviewed_at"] = datetime.strptime(
                    row[col_map["review_time"]].strip(), "%Y-%m-%d %H:%M:%S"
                )
            except ValueError:
                data["reviewed_at"] = datetime.now()
        else:
            data["reviewed_at"] = datetime.now()

        if not data.get("raw_text"):
            raise ValueError("评价内容为空")

        data["is_valid"] = True
        return data
