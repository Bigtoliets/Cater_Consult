"""推送基类与数据结构"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from typing import Optional


class AlertLevel(str, Enum):
    """告警级别"""
    CRITICAL = "critical"   # 食安事件, ≤3min 响应
    WARNING = "warning"     # 单菜品差评率超阈值, ≤15min
    INFO = "info"           # 日报/周报, 定时推送
    UPDATE = "update"       # 整改反馈状态更新


@dataclass
class Alert:
    """统一告警结构"""
    level: AlertLevel
    title: str
    content: str                            # Markdown 正文
    dish_name: Optional[str] = None
    dish_id: Optional[int] = None
    decision_id: Optional[str] = None
    triggered_at: datetime = field(default_factory=datetime.now)
    metadata: dict = field(default_factory=dict)


class BasePusher(ABC):
    """所有推送通道的抽象基类"""

    @property
    @abstractmethod
    def channel_name(self) -> str:
        """通道唯一标识"""
        ...

    @abstractmethod
    async def push(self, alert: Alert) -> bool:
        """推送告警, 返回是否成功"""
        ...

    async def health_check(self) -> bool:
        """通道是否可达"""
        return True
