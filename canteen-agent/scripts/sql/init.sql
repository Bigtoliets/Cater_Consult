-- ============================================================
-- 食堂品控智能Agent系统 — MySQL 初始化脚本 (菜品为单位)
-- ============================================================

-- -----------------------------------------------------------
-- 1. 菜品表
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS dishes (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(100) NOT NULL COMMENT '菜品名称',
    category    VARCHAR(50)  COMMENT '分类',
    unit_cost   DOUBLE DEFAULT 0.0 COMMENT '单份成本',
    price       DOUBLE DEFAULT 0.0 COMMENT '售价',
    is_active   TINYINT(1) DEFAULT 1 COMMENT '是否在售',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='菜品';

INSERT INTO dishes (id, name, category, unit_cost, price) VALUES
(1,  '红烧肉',     '热菜', 4.20, 12.00),
(2,  '麻婆豆腐',   '热菜', 2.50, 8.00),
(3,  '宫保鸡丁',   '热菜', 3.80, 10.00),
(4,  '兰州拉面',   '面食', 2.00, 8.00),
(5,  '炸酱面',     '面食', 2.50, 9.00),
(6,  '白切鸡',     '热菜', 5.00, 15.00),
(7,  '清炒时蔬',   '热菜', 1.50, 6.00),
(8,  '糖醋里脊',   '热菜', 4.50, 12.00),
(9,  '番茄炒蛋',   '热菜', 1.80, 6.00),
(10, '土豆肉丝',   '热菜', 2.80, 8.00)
ON DUPLICATE KEY UPDATE name=VALUES(name);

-- -----------------------------------------------------------
-- 2. 评价表
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS reviews (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    source        VARCHAR(50)  COMMENT '评价来源',
    raw_text      TEXT         NOT NULL COMMENT '原始评价文本',
    sentiment     VARCHAR(20)  COMMENT '情感倾向 positive/negative/neutral',
    rating        INT          COMMENT '评分 1-5',
    meal_time     VARCHAR(10)  COMMENT '用餐时段',
    stall_name    VARCHAR(100) COMMENT '档口名称（兼容旧数据）',
    dish_id       INT          COMMENT '菜品ID',
    dish_name_raw VARCHAR(200) COMMENT '用户提及菜品名',
    risk_level    INT DEFAULT 1 COMMENT '风险等级 1-5',
    dimensions    JSON         COMMENT '吐槽维度',
    is_valid      TINYINT(1) DEFAULT 1 COMMENT '是否有效评价',
    reviewed_at   DATETIME     COMMENT '评价时间',
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (dish_id) REFERENCES dishes(id),
    INDEX idx_dish_id (dish_id),
    INDEX idx_sentiment (sentiment),
    INDEX idx_reviewed_at (reviewed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户评价';

-- -----------------------------------------------------------
-- 3. SOP 知识库表
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS sop_entries (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    dish_id       INT          NOT NULL COMMENT '菜品ID',
    dimension     VARCHAR(50)  NOT NULL COMMENT '维度',
    title         VARCHAR(200) COMMENT '条目标题',
    content       TEXT         NOT NULL COMMENT '条目内容(Markdown)',
    metadata_json JSON         COMMENT '结构化字段',
    vector_id     VARCHAR(100) COMMENT 'Milvus向量ID',
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (dish_id) REFERENCES dishes(id),
    INDEX idx_dish_dim (dish_id, dimension)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='SOP知识库';

INSERT INTO sop_entries (dish_id, dimension, title, content, metadata_json) VALUES
(1, 'sop', '红烧肉标准工艺',
 '【红烧肉标准工艺】\n- 五花肉切 3cm 方块，焯水去血沫\n- 炒糖色：冰糖 30g，小火熬至枣红色\n- 炖煮：高压锅上汽后压制 20 分钟\n- 调味：生抽 15ml、老抽 5ml、盐 5g、料酒 10ml\n- 收汁：大火收至汤汁浓稠\n- 出餐温度：≥ 75°C',
 '{"cook_time_min":20,"salt_g":5,"temp_c":75}'),
(1, 'cost', '红烧肉成本卡',
 '【红烧肉单份成本 ¥4.20】\n- 五花肉 150g: ¥3.00\n- 调料: ¥0.60\n- 辅料: ¥0.30\n- 能耗分摊: ¥0.30',
 '{"unit_cost":4.20,"meat_g":150}'),
(1, 'food_safety', '红烧肉食安规范',
 '【红烧肉食安要点】\n- 猪肉中心温度 ≥ 75°C\n- 炖煮时间 ≥ 20 分钟\n- 成品常温存放 ≤ 2 小时\n- 回锅加热需达 75°C 以上',
 '{"min_cook_temp":75,"max_room_temp_hours":2}')
ON DUPLICATE KEY UPDATE content=VALUES(content);

-- -----------------------------------------------------------
-- 4. 诊断报告表
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS diagnoses (
    id                    INT AUTO_INCREMENT PRIMARY KEY,
    review_id             INT          COMMENT '关联的原始评价ID',
    dish_id               INT          COMMENT '菜品ID',
    status                VARCHAR(20) DEFAULT 'pending' COMMENT '状态',
    conflict_type         VARCHAR(50) COMMENT '冲突类型',
    confidence            DOUBLE DEFAULT 0.0 COMMENT '置信度',
    conflict_analysis     JSON        COMMENT '冲突分析',
    decision_id           VARCHAR(50) COMMENT '决策唯一ID(Milvus关联)',
    summary               VARCHAR(200) COMMENT '一句话改进摘要',
    corrective_action     TEXT        COMMENT '整改单详细内容',
    human_review_required TINYINT(1) DEFAULT 0,
    human_review_result   VARCHAR(20) COMMENT '人工复核结果',
    triggered_at          DATETIME    COMMENT '触发时间',
    resolved_at           DATETIME    COMMENT '处理完成时间',
    created_at            DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (dish_id) REFERENCES dishes(id),
    INDEX idx_dish_status (dish_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI诊断报告';

-- -----------------------------------------------------------
-- 5. 系统配置表
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS system_configs (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    scope        VARCHAR(20)  NOT NULL DEFAULT 'global' COMMENT '作用域',
    scope_id     INT          COMMENT '作用域实体ID',
    config_key   VARCHAR(100) NOT NULL COMMENT '配置键',
    config_value JSON         NOT NULL COMMENT '配置值',
    description  VARCHAR(200) COMMENT '配置说明',
    updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_scope_key (scope, scope_id, config_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='系统配置';

INSERT INTO system_configs (scope, config_key, config_value, description) VALUES
('global', 'sensitive_words',      '{"words":["拉肚子","食物中毒","钢丝球","变质","异味","头发","虫子"]}', '敏感词订阅'),
('global', 'warning_thresholds',   '{"food_safety":3,"negative_rate":0.10,"batch_size":50}', '预警阈值'),
('global', 'rag_params',           '{"top_k":3,"similarity_threshold":0.6,"pool_size":20}', 'RAG检索参数'),
('global', 'ai_inference',         '{"confidence_threshold":0.75,"weight_sample_density":0.3,"weight_sop_mapping":0.4,"weight_history_similarity":0.3}', 'AI推理权重'),
('global', 'system_initialized',   '{"version":"2.0.0"}', '系统初始化标记')
ON DUPLICATE KEY UPDATE config_value=VALUES(config_value);

-- -----------------------------------------------------------
-- 6. 日报缓存表
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS daily_summaries (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    date           DATE    NOT NULL COMMENT '日报日期',
    total_reviews  INT     DEFAULT 0,
    positive_rate  DOUBLE  DEFAULT 0.0,
    neutral_rate   DOUBLE  DEFAULT 0.0,
    negative_rate  DOUBLE  DEFAULT 0.0,
    top_good       JSON    COMMENT '零差评TOP3',
    top_bad        JSON    COMMENT '红牌预警TOP3',
    radar_labels   JSON    COMMENT '雷达图标签',
    radar_values   JSON    COMMENT '雷达图数值',
    ai_summary     TEXT    COMMENT 'AI生成的日报摘要',
    created_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_date (date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='日报缓存';

-- -----------------------------------------------------------
-- v3.0 新增表
-- -----------------------------------------------------------

-- 2.1 Reviews 表升级: 新增 external_id 字段 (用于多源去重)
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS external_id VARCHAR(100) COMMENT '外部系统ID（去重键）' AFTER source;
ALTER TABLE reviews ADD INDEX IF NOT EXISTS idx_source_ext_id (source, external_id);
ALTER TABLE reviews ADD INDEX IF NOT EXISTS idx_source (source);

-- 7. 整改效果追踪表 (v3.0 新增)
CREATE TABLE IF NOT EXISTS feedback_records (
    id                    INT AUTO_INCREMENT PRIMARY KEY,
    decision_id           VARCHAR(50)  COMMENT '关联 Diagnosis.decision_id',
    dish_id               INT          COMMENT '关联菜品',
    status                VARCHAR(20) DEFAULT 'executed' COMMENT 'executed/ignored/effective/ineffective',
    pre_negative_rate     DOUBLE DEFAULT 0.0 COMMENT '整改前7天差评率',
    post_negative_rate_3d DOUBLE DEFAULT 0.0 COMMENT '整改后3天差评率',
    post_negative_rate_7d DOUBLE DEFAULT 0.0 COMMENT '整改后7天差评率',
    post_negative_rate_14d DOUBLE DEFAULT 0.0 COMMENT '整改后14天差评率',
    improvement_pct       DOUBLE DEFAULT 0.0 COMMENT '改善百分比(负值=改善)',
    auto_promoted         TINYINT(1) DEFAULT 0 COMMENT '是否自动飞升金标',
    auto_demoted          TINYINT(1) DEFAULT 0 COMMENT '是否自动降级失效',
    executed_at           DATETIME COMMENT '整改执行时间',
    created_at            DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at            DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (dish_id) REFERENCES dishes(id),
    INDEX idx_decision_id (decision_id),
    INDEX idx_dish_id (dish_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='整改效果追踪';

-- 8. 厨师画像表 (v3.0 新增)
CREATE TABLE IF NOT EXISTS chef_profiles (
    id                    INT AUTO_INCREMENT PRIMARY KEY,
    chef_name             VARCHAR(50) NOT NULL COMMENT '厨师姓名',
    total_dishes_handled  INT DEFAULT 0 COMMENT '累计处理菜品数',
    avg_positive_rate     DOUBLE DEFAULT 0.0 COMMENT '平均好评率',
    avg_negative_rate     DOUBLE DEFAULT 0.0 COMMENT '平均差评率',
    improvement_rate      DOUBLE DEFAULT 0.0 COMMENT '整改后改善率',
    known_weak_dimensions JSON COMMENT '已知薄弱维度',
    strong_dimensions     JSON COMMENT '优势维度',
    last_evaluated_at     DATETIME COMMENT '最近评估时间',
    created_at            DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at            DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_chef_name (chef_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='厨师画像';

-- 9. 推送规则默认配置 (v3.0 新增)
INSERT INTO system_configs (scope, config_key, config_value, description) VALUES
('global', 'push_rules', '{"critical":["wechat_work","dingtalk"],"warning":["wechat_work"],"info":["wechat_work"]}', '推送路由规则')
ON DUPLICATE KEY UPDATE config_value=VALUES(config_value);
