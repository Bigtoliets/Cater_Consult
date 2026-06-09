"""数据连接器抽象基类 + 统一数据结构"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class RawReview:
    """统一中间格式 — 所有 Connector 输出此结构"""
    raw_text: str
    source: str = "unknown"
    dish_name_raw: Optional[str] = None
    rating: Optional[int] = None
    meal_time: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    external_id: Optional[str] = None
    stall_name: Optional[str] = None
    metadata: dict = field(default_factory=dict)


class BaseConnector(ABC):
    """所有数据连接器的抽象基类"""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """连接器唯一标识 (如 'meituan', 'wechat', 'pos')"""
        ...

    @abstractmethod
    async def fetch(self, start_date: datetime, end_date: datetime) -> list[RawReview]:
        """拉取指定时间范围的评价数据"""
        ...

    async def health_check(self) -> bool:
        """健康检查：数据源是否可达"""
        return True

    def normalize(self, raw: RawReview) -> dict:
        """将 RawReview 转为 Review 表字段 dict"""
        return {
            "raw_text": raw.raw_text,
            "source": raw.source,
            "external_id": raw.external_id,
            "dish_name_raw": raw.dish_name_raw,
            "rating": raw.rating,
            "meal_time": raw.meal_time,
            "reviewed_at": raw.reviewed_at or datetime.now(),
            "stall_name": raw.stall_name,
            "is_valid": True,
        }
