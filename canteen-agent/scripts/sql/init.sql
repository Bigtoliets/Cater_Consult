-- ============================================================
-- 食堂品控智能Agent系统 — MySQL 初始化脚本
-- 该脚本由 docker-compose 在 MySQL 容器首次启动时自动执行
-- ============================================================

-- -----------------------------------------------------------
-- 1. 食堂表
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS canteens (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(100) NOT NULL COMMENT '食堂名称',
    location    VARCHAR(200) COMMENT '位置描述',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='食堂';

INSERT INTO canteens (id, name, location) VALUES
(1, '一食堂', '一楼东侧'),
(2, '二食堂', '二楼西侧')
ON DUPLICATE KEY UPDATE name=VALUES(name);

-- -----------------------------------------------------------
-- 2. 厨师表
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS chefs (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(50)  NOT NULL COMMENT '厨师姓名',
    phone       VARCHAR(20)  COMMENT '联系电话',
    speciality  VARCHAR(200) COMMENT '擅长菜系',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='厨师';

INSERT INTO chefs (id, name, phone, speciality) VALUES
(1, '张师傅', '13800001001', '川湘菜'),
(2, '李师傅', '13800001002', '面食'),
(3, '王师傅', '13800001003', '粤菜'),
(4, '赵师傅', '13800001004', '鲁菜'),
(5, '刘师傅', '13800001005', '家常菜')
ON DUPLICATE KEY UPDATE name=VALUES(name);

-- -----------------------------------------------------------
-- 3. 档口表
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS stalls (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(100) NOT NULL COMMENT '档口名称',
    canteen_id  INT NOT NULL COMMENT '所属食堂',
    chef_id     INT COMMENT '当班主厨',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (canteen_id) REFERENCES canteens(id),
    FOREIGN KEY (chef_id)    REFERENCES chefs(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='档口';

INSERT INTO stalls (id, name, canteen_id, chef_id) VALUES
(1,  '二楼川湘档口', 1, 1),
(2,  '面食档口',     1, 2),
(3,  '粤菜档口',     1, 3),
(4,  '鲁菜档口',     2, 4),
(5,  '家常菜档口',   2, 5),
(6,  '小吃档口',     2, NULL)
ON DUPLICATE KEY UPDATE name=VALUES(name);

-- -----------------------------------------------------------
-- 4. 菜品表
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS dishes (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(100) NOT NULL COMMENT '菜品名称',
    stall_id    INT NOT NULL COMMENT '所属档口',
    category    VARCHAR(50)  COMMENT '分类',
    unit_cost   DOUBLE DEFAULT 0.0 COMMENT '单份成本',
    price       DOUBLE DEFAULT 0.0 COMMENT '售价',
    is_active   TINYINT(1) DEFAULT 1 COMMENT '是否在售',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (stall_id) REFERENCES stalls(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='菜品';

INSERT INTO dishes (id, name, stall_id, category, unit_cost, price) VALUES
(1,  '红烧肉',     1, '热菜', 4.20, 12.00),
(2,  '麻婆豆腐',   1, '热菜', 2.50, 8.00),
(3,  '宫保鸡丁',   1, '热菜', 3.80, 10.00),
(4,  '兰州拉面',   2, '面食', 2.00, 8.00),
(5,  '炸酱面',     2, '面食', 2.50, 9.00),
(6,  '白切鸡',     3, '热菜', 5.00, 15.00),
(7,  '清炒时蔬',   3, '热菜', 1.50, 6.00),
(8,  '糖醋里脊',   4, '热菜', 4.50, 12.00),
(9,  '番茄炒蛋',   5, '热菜', 1.80, 6.00),
(10, '土豆肉丝',   5, '热菜', 2.80, 8.00)
ON DUPLICATE KEY UPDATE name=VALUES(name);

-- -----------------------------------------------------------
-- 5. 评价表
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS reviews (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    source        VARCHAR(50)  COMMENT '评价来源',
    raw_text      TEXT         NOT NULL COMMENT '原始评价文本',
    sentiment     VARCHAR(20)  COMMENT '情感倾向 positive/negative/neutral',
    rating        INT          COMMENT '评分 1-5',
    meal_time     VARCHAR(10)  COMMENT '用餐时段',
    stall_name    VARCHAR(100) COMMENT '档口名称',
    dish_id       INT          COMMENT '消歧后菜品ID',
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
-- 6. SOP 知识库表
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS sop_entries (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    dish_id       INT          NOT NULL COMMENT '菜品ID',
    dimension     VARCHAR(50)  NOT NULL COMMENT '维度 sop/cost/food_safety',
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
-- 7. 诊断报告表
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS diagnoses (
    id                    INT AUTO_INCREMENT PRIMARY KEY,
    dish_id               INT NOT NULL COMMENT '菜品ID',
    status                VARCHAR(20) DEFAULT 'pending' COMMENT '状态',
    conflict_type         VARCHAR(50) COMMENT '冲突类型',
    confidence            DOUBLE DEFAULT 0.0 COMMENT '置信度',
    conflict_analysis     JSON        COMMENT '冲突分析',
    corrective_action     TEXT        COMMENT '整改单内容',
    human_review_required TINYINT(1) DEFAULT 0,
    human_review_result   VARCHAR(20) COMMENT '人工复核结果',
    triggered_at          DATETIME    COMMENT '触发时间',
    resolved_at           DATETIME    COMMENT '处理完成时间',
    created_at            DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (dish_id) REFERENCES dishes(id),
    INDEX idx_dish_status (dish_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI诊断报告';

-- -----------------------------------------------------------
-- 8. 系统配置表
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
('global', 'system_initialized',   '{"version":"1.0.0"}', '系统初始化标记')
ON DUPLICATE KEY UPDATE config_value=VALUES(config_value);

-- -----------------------------------------------------------
-- 9. 日报缓存表
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
    radar_data     JSON    COMMENT '槽点雷达图',
    ai_summary     TEXT    COMMENT 'AI执行摘要',
    created_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_date (date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='每日品控日报';
