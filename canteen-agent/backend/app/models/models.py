"""SQLAlchemy 数据模型"""
from sqlalchemy import Column, Integer, String, Float, Text, DateTime, JSON, ForeignKey, Boolean, Enum as SAEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

from app.models.base import Base


class Sentiment(str, enum.Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class RiskLevel(int, enum.Enum):
    NONE = 1
    LOW = 2
    MEDIUM = 3
    HIGH = 4
    CRITICAL = 5


class DiagnosisStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    DISPATCHED = "dispatched"
    REJECTED = "rejected"
    HUMAN_REVIEW = "human_review"


# ===== 食堂/档口/厨师 =====

class Canteen(Base):
    """食堂"""
    __tablename__ = "canteens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, comment="食堂名称")
    location = Column(String(200), comment="位置描述")
    created_at = Column(DateTime, server_default=func.now())

    stalls = relationship("Stall", back_populates="canteen")


class Stall(Base):
    """档口"""
    __tablename__ = "stalls"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, comment="档口名称")
    canteen_id = Column(Integer, ForeignKey("canteens.id"), nullable=False)
    chef_id = Column(Integer, ForeignKey("chefs.id"), comment="当班主厨")
    created_at = Column(DateTime, server_default=func.now())

    canteen = relationship("Canteen", back_populates="stalls")
    chef = relationship("Chef", back_populates="stalls", foreign_keys=[chef_id])
    dishes = relationship("Dish", back_populates="stall")


class Chef(Base):
    """厨师"""
    __tablename__ = "chefs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False, comment="厨师姓名")
    phone = Column(String(20), comment="联系电话")
    speciality = Column(String(200), comment="擅长菜系")
    created_at = Column(DateTime, server_default=func.now())

    stalls = relationship("Stall", back_populates="chef", foreign_keys="Stall.chef_id")


# ===== 菜品 =====

class Dish(Base):
    """菜品"""
    __tablename__ = "dishes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, comment="菜品名称")
    stall_id = Column(Integer, ForeignKey("stalls.id"), nullable=False)
    category = Column(String(50), comment="分类（热菜/凉菜/面食/汤品等）")
    unit_cost = Column(Float, default=0.0, comment="单份成本（元）")
    price = Column(Float, default=0.0, comment="售价（元）")
    is_active = Column(Boolean, default=True, comment="是否在售")
    created_at = Column(DateTime, server_default=func.now())

    stall = relationship("Stall", back_populates="dishes")
    sop_entries = relationship("SOPEntry", back_populates="dish")
    reviews = relationship("Review", back_populates="dish")
    diagnoses = relationship("Diagnosis", back_populates="dish")


# ===== 评价 =====

class Review(Base):
    """用户评价"""
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(50), comment="评价来源（wechat/meituan/eleme/kiosk/csv_upload）")
    raw_text = Column(Text, nullable=False, comment="原始评价文本")
    sentiment = Column(SAEnum(Sentiment), comment="情感倾向")
    rating = Column(Integer, comment="评分 1-5")
    meal_time = Column(String(10), comment="用餐时段（breakfast/lunch/dinner）")
    stall_name = Column(String(100), comment="档口名称（原始）")
    dish_id = Column(Integer, ForeignKey("dishes.id"), comment="消歧后的菜品ID")
    dish_name_raw = Column(String(200), comment="用户提及菜品名（原始）")
    risk_level = Column(Integer, default=1, comment="风险等级 1-5")
    dimensions = Column(JSON, comment="吐槽维度 JSON")
    is_valid = Column(Boolean, default=True, comment="是否有效评价")
    reviewed_at = Column(DateTime, comment="评价时间")
    created_at = Column(DateTime, server_default=func.now())

    dish = relationship("Dish", back_populates="reviews")


# ===== SOP 知识库 =====

class SOPEntry(Base):
    """SOP 标准卡"""
    __tablename__ = "sop_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dish_id = Column(Integer, ForeignKey("dishes.id"), nullable=False)
    dimension = Column(String(50), nullable=False, comment="维度：sop/cost/food_safety")
    title = Column(String(200), comment="条目标题")
    content = Column(Text, nullable=False, comment="条目内容（Markdown）")
    metadata_json = Column(JSON, comment="结构化字段（如投料比、温度、时长）")
    vector_id = Column(String(100), comment="Milvus 向量ID")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    dish = relationship("Dish", back_populates="sop_entries")


# ===== 诊断报告 =====

class Diagnosis(Base):
    """AI 诊断报告"""
    __tablename__ = "diagnoses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dish_id = Column(Integer, ForeignKey("dishes.id"), nullable=False)
    status = Column(SAEnum(DiagnosisStatus), default=DiagnosisStatus.PENDING)
    conflict_type = Column(String(50), comment="冲突类型：TASTE_PREFERENCE / QUALITY_FLUCTUATION / FOOD_SAFETY")
    confidence = Column(Float, default=0.0, comment="综合置信度 0-1")
    conflict_analysis = Column(JSON, comment="冲突分析 JSON")
    corrective_action = Column(Text, comment="整改单内容（Markdown）")
    human_review_required = Column(Boolean, default=False)
    human_review_result = Column(String(20), comment="人工复核结果：approved/rejected/modified")
    triggered_at = Column(DateTime, comment="触发时间")
    resolved_at = Column(DateTime, comment="处理完成时间")
    created_at = Column(DateTime, server_default=func.now())

    dish = relationship("Dish", back_populates="diagnoses")


# ===== 系统配置 =====

class SystemConfig(Base):
    """系统配置（三级继承模型：全局默认 → 食堂级 → 档口级）"""
    __tablename__ = "system_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scope = Column(String(20), nullable=False, default="global", comment="作用域：global/canteen/stall")
    scope_id = Column(Integer, comment="作用域实体ID（canteen时=canteen_id, stall时=stall_id）")
    config_key = Column(String(100), nullable=False, comment="配置键")
    config_value = Column(JSON, nullable=False, comment="配置值")
    description = Column(String(200), comment="配置说明")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    created_at = Column(DateTime, server_default=func.now())


# ===== 日报缓存 =====

class DailySummary(Base):
    """每日品控日报"""
    __tablename__ = "daily_summaries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(DateTime, nullable=False, comment="日报日期")
    total_reviews = Column(Integer, default=0)
    positive_rate = Column(Float, default=0.0)
    neutral_rate = Column(Float, default=0.0)
    negative_rate = Column(Float, default=0.0)
    top_good = Column(JSON, comment="零差评 TOP3")
    top_bad = Column(JSON, comment="红牌预警 TOP3")
    radar_data = Column(JSON, comment="槽点雷达图数据")
    ai_summary = Column(Text, comment="AI 执行摘要")
    created_at = Column(DateTime, server_default=func.now())
