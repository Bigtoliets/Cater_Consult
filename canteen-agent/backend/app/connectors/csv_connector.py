"""CSV/Excel 连接器 — 保留现有手动上传逻辑的批量导入能力"""
import csv
import io
from datetime import datetime
from typing import IO

import chardet

from app.connectors.base import BaseConnector, RawReview

_FIELD_MAP = {
    "raw_text": "raw_text",
    "dish_name_raw": "dish_name_raw",
    "reviewed_at": "reviewed_at",
    "source": "source",
    "rating": "rating",
    "meal_time": "meal_time",
}

_CN_ALIASES = {
    "评价内容": "raw_text", "评论内容": "raw_text", "评价文本": "raw_text",
    "菜品名称": "dish_name_raw", "菜品名": "dish_name_raw",
    "评价来源": "source", "来源": "source",
    "评分": "rating",
    "用餐时段": "meal_time", "时段": "meal_time",
    "评价时间": "reviewed_at", "时间": "reviewed_at",
}


class CSVConnector(BaseConnector):
    """CSV/Excel 批量导入连接器 (兜底方案)"""
    source_name = "csv_manual"

    def __init__(self, file_path: str = ""):
        self.file_path = file_path

    async def fetch(self, start_date: datetime, end_date: datetime) -> list[RawReview]:
        # CSV 连接器不用于定时拉取，仅手动上传时用
        return []

    @classmethod
    def load_rows(cls, file_io: IO, ext: str) -> list:
        """编码检测 → 解析 CSV/Excel → 返回二维列表"""
        raw_data = file_io.read()

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
            reader = csv.reader(io.StringIO(text))
            best_rows = [row for row in reader if any(cell.strip() for cell in row)]
        return best_rows

    @classmethod
    def _parse_excel(cls, raw_data: bytes, ext: str) -> list:
        if ext == "xlsx":
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(raw_data))
            ws = wb.active
            rows = []
            for row in ws.iter_rows(values_only=True):
                rows.append([str(c) if c is not None else "" for c in row])
            return rows
        else:
            import xlrd
            wb = xlrd.open_workbook(file_contents=raw_data)
            ws = wb.sheet_by_index(0)
            rows = []
            for r in range(ws.nrows):
                rows.append([str(ws.cell_value(r, c)) for c in range(ws.ncols)])
            return rows

    @classmethod
    def build_col_map(cls, header: list) -> dict:
        col_map = {}
        for i, name in enumerate(header):
            key = name.strip()
            while key and ord(key[0]) == 0xFEFF:
                key = key[1:]
            if key in _FIELD_MAP:
                col_map[_FIELD_MAP[key]] = i
            elif key in _CN_ALIASES:
                col_map[_CN_ALIASES[key]] = i
        return col_map

    @classmethod
    def parse_row(cls, row: list, col_map: dict) -> dict:
        data = {}
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
