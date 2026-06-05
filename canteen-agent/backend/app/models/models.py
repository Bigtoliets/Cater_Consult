"""SQLAlchemy 模型（菜品为单位，无档口/食堂/厨师）"""
from sqlalchemy import (
    Column, Integer, String, Text, Float, Boolean, DateTime, JSON, ForeignKey,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy import Enum as SAEnum
import enum

from app.models.base import Base


class Sentiment(str, enum.Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class DiagnosisStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    DISPATCHED = "dispatched"
    REJECTED = "rejected"


class Dish(Base):
    """菜品"""
    __tablename__ = "dishes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, comment="菜品名称")
    category = Column(String(50), comment="分类")
    unit_cost = Column(Float, default=0.0, comment="单份成本")
    price = Column(Float, default=0.0, comment="售价")
    is_active = Column(Boolean, default=True, comment="是否在售")
    created_at = Column(DateTime, server_default=func.now())

    reviews = relationship("Review", back_populates="dish")
    diagnoses = relationship("Diagnosis", back_populates="dish")
    sop_entries = relationship("SOPEntry", back_populates="dish")


class Review(Base):
    """用户评价"""
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(50), comment="评价来源")
    raw_text = Column(Text, nullable=False, comment="原始评价文本")
    sentiment = Column(SAEnum(Sentiment), comment="情感倾向")
    rating = Column(Integer, comment="评分 1-5")
    meal_time = Column(String(10), comment="用餐时段")
    stall_name = Column(String(100), comment="档口名称（兼容旧数据）")
    dish_id = Column(Integer, ForeignKey("dishes.id"), comment="菜品ID")
    dish_name_raw = Column(String(200), comment="用户提及菜品名（原始）")
    risk_level = Column(Integer, default=1, comment="风险等级 1-5")
    dimensions = Column(JSON, comment="吐槽维度 JSON")
    is_valid = Column(Boolean, default=True, comment="是否有效评价")
    reviewed_at = Column(DateTime, comment="评价时间")
    created_at = Column(DateTime, server_default=func.now())

    dish = relationship("Dish", back_populates="reviews")


class Diagnosis(Base):
    """AI 诊断报告"""
    __tablename__ = "diagnoses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    review_id = Column(Integer, comment="关联评价ID")
    dish_id = Column(Integer, ForeignKey("dishes.id"), comment="菜品ID")
    status = Column(SAEnum(DiagnosisStatus), default=DiagnosisStatus.PENDING)
    conflict_type = Column(String(50))
    confidence = Column(Float, default=0.0)
    conflict_analysis = Column(JSON)
    decision_id = Column(String(50))
    dish_name = Column(String(200), comment="菜品名称（冗余字段，避免 join 失败丢名字）")
    summary = Column(String(200))
    corrective_action = Column(Text)
    human_review_required = Column(Boolean, default=False)
    human_review_result = Column(String(20))
    triggered_at = Column(DateTime)
    resolved_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())

    dish = relationship("Dish", back_populates="diagnoses")


class SOPEntry(Base):
    """SOP 知识库"""
    __tablename__ = "sop_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dish_id = Column(Integer, ForeignKey("dishes.id"), nullable=False)
    dimension = Column(String(50), nullable=False)
    title = Column(String(200))
    content = Column(Text, nullable=False)
    metadata_json = Column(JSON)
    vector_id = Column(String(100))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    dish = relationship("Dish", back_populates="sop_entries")


class SystemConfig(Base):
    """系统配置"""
    __tablename__ = "system_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scope = Column(String(20), nullable=False, default="global")
    scope_id = Column(Integer)
    config_key = Column(String(100), nullable=False)
    config_value = Column(JSON, nullable=False)
    description = Column(String(200))
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    created_at = Column(DateTime, server_default=func.now())


class DailySummary(Base):
    """日报缓存"""
    __tablename__ = "daily_summaries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(DateTime, nullable=False)
    total_reviews = Column(Integer, default=0)
    positive_rate = Column(Float, default=0.0)
    neutral_rate = Column(Float, default=0.0)
    negative_rate = Column(Float, default=0.0)
    top_good = Column(JSON)
    top_bad = Column(JSON)
    radar_labels = Column(JSON)
    radar_values = Column(JSON)
    ai_summary = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
