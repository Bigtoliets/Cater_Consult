-- 完整数据库初始化脚本（建库 + 建全部表）
-- 用法：mysql -uroot -p < init_db.sql
-- 等价于 python init_db.py；推荐优先用 init_db.py（与 SQLAlchemy 模型零偏差）。
-- 说明：enum 列（sentiment/status）此处用 VARCHAR，避免与 SQLAlchemy SAEnum 的存储形式冲突。

CREATE DATABASE IF NOT EXISTS canteen_agent
    DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE canteen_agent;

-- 1. 店铺
CREATE TABLE IF NOT EXISTS shops (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL COMMENT '店铺/档口名称',
    address VARCHAR(200) NULL COMMENT '地址',
    is_active TINYINT(1) DEFAULT 1 COMMENT '是否营业',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 2. 菜品
CREATE TABLE IF NOT EXISTS dishes (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL COMMENT '菜品名称',
    category VARCHAR(50) NULL COMMENT '分类',
    unit_cost FLOAT DEFAULT 0.0 COMMENT '单份成本',
    price FLOAT DEFAULT 0.0 COMMENT '售价',
    is_active TINYINT(1) DEFAULT 1 COMMENT '是否在售',
    shop_id INT NULL COMMENT '所属店铺ID',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_dishes_shop FOREIGN KEY (shop_id) REFERENCES shops(id)
);

-- 3. 评论
CREATE TABLE IF NOT EXISTS reviews (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    source VARCHAR(50) NULL COMMENT '评价来源',
    external_id VARCHAR(100) NULL COMMENT '外部系统ID（去重键）',
    raw_text TEXT NOT NULL COMMENT '原始评价文本',
    sentiment VARCHAR(20) NULL COMMENT '情感倾向: positive/negative/neutral',
    rating INT NULL COMMENT '评分 1-5',
    meal_time VARCHAR(10) NULL COMMENT '用餐时段',
    stall_name VARCHAR(100) NULL COMMENT '档口名称（兼容旧数据）',
    dish_id INT NULL COMMENT '菜品ID',
    dish_name_raw VARCHAR(200) NULL COMMENT '用户提及菜品名（原始）',
    shop_id INT NULL COMMENT '所属店铺ID',
    synced_at DATETIME NULL COMMENT '同步分析时间（NULL=未同步）',
    risk_level INT DEFAULT 1 COMMENT '风险等级 1-5',
    dimensions JSON NULL COMMENT '吐槽维度 JSON',
    is_valid TINYINT(1) DEFAULT 1 COMMENT '是否有效评价',
    reviewed_at DATETIME NULL COMMENT '评价时间',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    KEY idx_source_ext_id (source, external_id),
    CONSTRAINT fk_reviews_dish FOREIGN KEY (dish_id) REFERENCES dishes(id),
    CONSTRAINT fk_reviews_shop FOREIGN KEY (shop_id) REFERENCES shops(id)
);

-- 4. AI 诊断报告
CREATE TABLE IF NOT EXISTS diagnoses (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    review_id INT NULL COMMENT '关联评价ID',
    dish_id INT NULL COMMENT '菜品ID',
    status VARCHAR(20) DEFAULT 'pending' COMMENT '状态: pending/completed/dispatched/rejected',
    conflict_type VARCHAR(50) NULL,
    confidence FLOAT DEFAULT 0.0,
    conflict_analysis JSON NULL,
    decision_id VARCHAR(50) NULL,
    dish_name VARCHAR(200) NULL COMMENT '菜品名称（冗余字段）',
    summary VARCHAR(200) NULL,
    corrective_action TEXT NULL,
    human_review_required TINYINT(1) DEFAULT 0,
    human_review_result VARCHAR(20) NULL,
    triggered_at DATETIME NULL,
    resolved_at DATETIME NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_diagnoses_dish FOREIGN KEY (dish_id) REFERENCES dishes(id)
);

-- 5. SOP 知识库
CREATE TABLE IF NOT EXISTS sop_entries (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    dish_id INT NOT NULL COMMENT '菜品ID',
    dimension VARCHAR(50) NOT NULL,
    title VARCHAR(200) NULL,
    content TEXT NOT NULL,
    metadata_json JSON NULL,
    vector_id VARCHAR(100) NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_sop_entries_dish FOREIGN KEY (dish_id) REFERENCES dishes(id)
);

-- 6. 系统配置
CREATE TABLE IF NOT EXISTS system_configs (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    scope VARCHAR(20) NOT NULL DEFAULT 'global',
    scope_id INT NULL,
    config_key VARCHAR(100) NOT NULL,
    config_value JSON NOT NULL,
    description VARCHAR(200) NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 7. 日报缓存
CREATE TABLE IF NOT EXISTS daily_summaries (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    date DATETIME NOT NULL,
    total_reviews INT DEFAULT 0,
    positive_rate FLOAT DEFAULT 0.0,
    neutral_rate FLOAT DEFAULT 0.0,
    negative_rate FLOAT DEFAULT 0.0,
    top_good JSON NULL,
    top_bad JSON NULL,
    radar_labels JSON NULL,
    radar_values JSON NULL,
    ai_summary TEXT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 8. 整改效果追踪
CREATE TABLE IF NOT EXISTS feedback_records (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    decision_id VARCHAR(50) NULL COMMENT '关联 Diagnosis.decision_id',
    dish_id INT NULL COMMENT '关联菜品',
    status VARCHAR(20) DEFAULT 'executed' COMMENT '状态: executed/ignored/effective/ineffective',
    pre_negative_rate FLOAT DEFAULT 0.0 COMMENT '整改前7天差评率',
    post_negative_rate_3d FLOAT DEFAULT 0.0 COMMENT '整改后3天差评率',
    post_negative_rate_7d FLOAT DEFAULT 0.0 COMMENT '整改后7天差评率',
    post_negative_rate_14d FLOAT DEFAULT 0.0 COMMENT '整改后14天差评率',
    improvement_pct FLOAT DEFAULT 0.0 COMMENT '改善百分比（负值=改善）',
    auto_promoted TINYINT(1) DEFAULT 0 COMMENT '是否自动飞升金标',
    auto_demoted TINYINT(1) DEFAULT 0 COMMENT '是否自动降级为失效',
    executed_at DATETIME NULL COMMENT '整改执行时间',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_feedback_decision_id (decision_id),
    CONSTRAINT fk_feedback_records_dish FOREIGN KEY (dish_id) REFERENCES dishes(id)
);

-- 9. 厨师画像
CREATE TABLE IF NOT EXISTS chef_profiles (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    chef_name VARCHAR(50) NOT NULL COMMENT '厨师姓名',
    total_dishes_handled INT DEFAULT 0 COMMENT '累计处理菜品数',
    avg_positive_rate FLOAT DEFAULT 0.0 COMMENT '平均好评率',
    avg_negative_rate FLOAT DEFAULT 0.0 COMMENT '平均差评率',
    improvement_rate FLOAT DEFAULT 0.0 COMMENT '整改后改善率',
    known_weak_dimensions JSON NULL COMMENT '已知薄弱维度',
    strong_dimensions JSON NULL COMMENT '优势维度',
    last_evaluated_at DATETIME NULL COMMENT '最近一次评估时间',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
