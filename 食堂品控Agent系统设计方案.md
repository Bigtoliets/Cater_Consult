# 食堂品控智能Agent系统——技术设计方案

## 1. 项目概述

### 1.1 项目背景

食堂是典型的「众口难调」场景。目前，食堂管理方依赖以下方式收集就餐反馈：

- 微信小程序/意见箱收集评价
- 外卖平台（美团/饿了么）的用户打分
- 点餐机后台的评分数据

然而，这些评价数据的处理方式仍然停留在**人工抽查 + 月末汇总**的阶段，存在三个核心痛点：

| 痛点 | 现状 | 影响 |
|---|---|---|
| **信息断层** | 知道有差评，但后厨不知道具体哪一步出了问题（火候？调料？食材批次？） | 改了也没效果，反复被投诉 |
| **响应滞后** | 月末开会才总结，食安隐患（如吃出异物）可能在事发后几小时甚至几天才被发现 | 极易演变成严重的公关危机 |
| **经验流失** | 老师傅的经验存在于脑子里，人走了工艺就断了，新厨师缺乏标准化的操作指导 | 菜品质量随人员流动剧烈波动 |

### 1.2 解决方案

**食堂品控智能 Agent 系统** 是一套将 AI Agent 技术降维应用到餐饮后厨品控的数字化工具。其核心思路来源于金融领域的「多源数据→信号提取→冲突分析→决策生成」闭环：

```
评价数据上传 → Agent 自动分析 → 识别品控问题 → 生成整改单 → 后厨执行 → 效果追踪
```

系统不是简单地给评价打正面/负面标签，而是能够：
- **自动定位**差评对应的是哪道菜、哪个档口、哪班厨师
- **区分**「口味偏好差异」（有人觉得辣、有人觉得不辣）和「生产品控波动」（今天太咸明天太淡）
- **给出可执行的整改指令**（如「高压锅上汽后压制满 20 分钟」），而非模糊的「提高菜品质量」
- **沉淀知识**：每道菜积累动态优化的数字 SOP，形成食堂自己的品控知识库

### 1.3 适用范围

| 维度 | 说明 |
|---|---|
| **食堂规模** | 2 个食堂、15 个档口、约 120 道常驻菜品（可弹性扩展） |
| **评价来源** | CSV/Excel 文件手工上传（无爬虫，合规安全），支持微信小程序、外卖平台、点餐机导出格式 |
| **日均处理量** | 300-500 条评价（可扩展至 1000 条/日） |
| **部署方式** | 本地服务器/可控云主机，Docker 一键部署，数据不出内网 |
| **目标用户** | 食堂承包商老板、后勤主管（管理层看板）、后厨主管/当班主厨（执行端）、系统管理员（配置端） |

### 1.4 核心价值与 KPI

| KPI | 目标值 | 衡量方式 |
|---|---|---|
| **响应时效** | 重大食安异常从发生到推送给当班主厨 ≤ 5 分钟 | 系统告警时间戳 - 评价时间戳 |
| **差评转化** | 同一菜品的复发性差评率下降 30%+ | 系统上线前后同期对比 |
| **知识沉淀** | 每道菜积累一套动态优化的数字 SOP | 知识库条目覆盖率（已录入菜品数 / 总菜品数） |
| **运营提效** | 品控分析工作量减少 70%+ | 人工抽查耗时对比 |

### 1.5 文档结构

本文档为系统的**完整技术设计方案**，面向开发团队、技术评审和项目决策者。各章节安排如下：

| 章节 | 内容 | 目标读者 |
|---|---|---|
| **第 2 章** 系统架构总览 | 五层逻辑架构、物理部署拓扑、三层架构、消息队列、多租户隔离 | 后端/AI/DevOps 工程师 |
| **第 3 章** Agent 推理引擎设计 | LangGraph 工作流、6 节点详解、冲突检测算法、置信度评估、人机协同闭环 | AI 工程师 |
| **第 4 章** Agent 配置与参数化 | 三级继承模型、四大配置维度、Prompt 版本控制、配置生效链路 | 全栈工程师 |
| **第 5 章** 数据采集与 ETL | CSV/Excel 上传、编码检测、两阶段导入、整批回滚、数据标准化 | 后端工程师 |
| **第 6 章** 知识库层 | 四大知识维度、Milvus 向量化、多租户 Partition、持续学习入库 | AI/后端工程师 |
| **第 7 章** 核心业务页面 | 日报看板、单品诊断、配置管理、智能问答四页布局与交互 | 前端工程师 |
| **第 8 章** 技术选型与部署 | 全栈技术栈、硬件要求、一键部署 6 步流程、常见问题 | DevOps/运维 |
| **第 9 章** 实施计划与风险 | 三阶段交付路线图（14 周）、风险矩阵、团队配置 | 项目经理/决策者 |

## 2. 系统架构总览

> **一句话定位**：食堂品控智能 Agent 是一个「评价数据采集 → Agent 推理诊断 → 后厨整改闭环」的一体化品控中枢，通过三层架构（Controller-Service-DAO）承载业务逻辑，通过 LangGraph 微服务承载 AI 推理，两者经 RabbitMQ 异步解耦协作。

---

### 2.1 逻辑分层架构

系统按职责划分为五层。实线箭头为数据流（评价进入 → 推理流转 → 结果分发），虚线箭头为控制流（配置下发、定时调度、健康检查）。

```mermaid
graph TD
    subgraph 接入层
        A1[📤 CSV/Excel 上传]
        A2[💬 微信小程序评价]
        A3[📊 点餐机打分]
    end

    subgraph 业务服务层 - FastAPI 主后端
        B1[Controller 层: REST API 接口]
        B2[Service 层: 业务逻辑 + 定时调度]
        B3[DAO 层: MySQL / Milvus / Redis 访问]
    end

    subgraph 消息中间件
        MQ[[🐰 RabbitMQ]]
    end

    subgraph Agent 引擎层 - LangGraph 微服务
        C1[Review Cleansing]
        C2[Dish Routing]
        C3[RAG Retrieval]
        C4[Conflict Detection]
        C5[Confidence Evaluation]
        C6[Action Report]
    end

    subgraph 数据持久层
        D1[(MySQL: 业务数据)]
        D2[(Milvus: 向量知识库)]
        D3[(Redis: 缓存 / 热配置)]
    end

    subgraph 基础设施层
        E1[🐳 Docker Compose]
        E2[🤖 Ollama - Qwen2.5]
    end

    A1 --> B1
    A2 --> B1
    A3 --> B1
    B1 --> B2
    B2 --> B3
    B2 -->|实时推送| MQ
    MQ -->|异步消费| C1
    C1 --> C2 --> C3 --> C4 --> C5 --> C6
    C6 -->|回调 REST API| B1
    B3 --> D1
    B3 --> D2
    B3 --> D3
    C3 --> D2
    C3 --> D3

    B2 -.-|Celery Beat 定时调度| B2
    B2 -.-|健康检查| C1
```

**五层职责概要**：

| 层 | 核心组件 | 职责 |
|---|---|---|
| **接入层** | CSV 上传、小程序 API、点餐机接口 | 评价数据入口，支持多源汇聚 |
| **业务服务层** | FastAPI（Controller / Service / DAO） | 业务逻辑编排、REST API、定时任务 |
| **消息中间件** | RabbitMQ | 评价任务异步解耦，削峰填谷，支持死信重试 |
| **Agent 引擎层** | LangGraph 微服务 | 评价清洗 → 消歧 → 检索 → 冲突检测 → 置信评估 → 整改生成 |
| **数据持久层** | MySQL + Milvus + Redis | 业务数据、向量知识库、热配置缓存 |
| **基础设施层** | Docker Compose / Ollama | 容器化部署、本地 LLM 推理 |

---

### 2.2 物理部署拓扑

所有服务通过 Docker Compose 统一编排，部署于单台服务器或云主机。核心容器关系与端口分配如下：

```
                          ┌─────────────────────────────────────────────┐
                          │            Nginx :80（可选反向代理）           │
                          └──────┬────────────────────────────┬─────────┘
                                 │                            │
                    ┌────────────▼──────────┐    ┌───────────▼───────────┐
                    │  Vue3 前端 :3000       │    │  FastAPI 主后端 :8000  │
                    │  (静态资源服务)         │    │  Controller/Service/   │
                    │                        │    │  DAO + Celery Worker   │
                    └────────────────────────┘    └──────┬──────┬────────┘
                                                         │      │
                              ┌──────────────────────────┘      └──────────────┐
                              │                                                │
                 ┌────────────▼──────────┐                          ┌──────────▼──────────┐
                 │  LangGraph 微服务       │                          │  RabbitMQ            │
                 │  :8001 (内部 REST)      │◄─────────────────────────│  :5672 (管理 :15672)  │
                 │  Agent 推理引擎         │  消费评价任务              │                      │
                 └──────┬──────┬──────────┘                          └──────────────────────┘
                        │      │
           ┌────────────┘      └────────────┐
           │                                │
  ┌────────▼──────┐   ┌────────────┐   ┌───▼──────────┐
  │  Milvus        │   │  MySQL      │   │  Redis        │
  │  :19530        │   │  :3306      │   │  :6379        │
  │  (向量检索)     │   │  (业务数据)  │   │  (缓存/热配置)  │
  └───────────────┘   └────────────┘   └──────────────┘

  ┌────────────────┐
  │  Ollama         │
  │  :11434         │
  │  Qwen2.5 +      │
  │  nomic-embed-text│
  └────────────────┘
```

---

### 2.3 三层架构：Controller-Service-DAO

主业务后端基于 FastAPI，严格遵循三层解耦架构。LangGraph Agent 引擎作为**独立的微服务**，由 Service 层通过 REST API 异步调用，不共享内存、不直连数据库。

```mermaid
graph LR
    subgraph "FastAPI 主后端 :8000"
        direction TB
        CTRL[Controller 层<br/>路由 / 参数校验 / 响应封装]
        SVC[Service 层<br/>业务编排 / 定时调度 / 异步任务]
        DAO[DAO 层<br/>MySQL / Milvus / Redis 数据访问]

        CTRL --> SVC
        SVC --> DAO
    end

    subgraph "外部"
        VUE[Vue3 前端]
        AGENT[LangGraph 微服务 :8001]
        MQ[RabbitMQ]
    end

    VUE -->|REST /api/v1/*| CTRL
    SVC -->|POST 触发推理| MQ
    MQ --> AGENT
    AGENT -->|回调结果| CTRL
```

| 层 | 职责边界 | 不做什么 |
|---|---|---|
| **Controller** | 接收 HTTP 请求、参数校验（Pydantic）、调用 Service、封装 JSON 响应 | 不包含业务逻辑，不直接访问数据库 |
| **Service** | 业务编排（评价入库 → 触发 Agent → 回调处理）、Celery 定时任务调度、配置变更通知 | 不直接拼接 SQL，不直接操作 Milvus Connection |
| **DAO** | 封装 MySQL CRUD（SQLAlchemy）、封装 Milvus 检索（langchain_milvus）、封装 Redis 读写（redis-py） | 不包含业务判断，不做流程编排 |

---

### 2.4 LangGraph 微服务边界

Agent 推理引擎作为独立微服务运行，通过 REST API 暴露推理接口：

```python
# LangGraph 微服务暴露的 REST 接口（简化）
POST /agent/analyze          # 接收单条评价，触发完整推理工作流
POST /agent/analyze_batch    # 批量评价推理
GET  /agent/health           # 健康检查（含 Milvus / Ollama 连通性）
```

**边界约束**：

| 约束 | 说明 |
|---|---|
| **不直连 MySQL** | Agent 不直接读写业务数据库，所需数据（菜单列表、SOP 原文）由主后端在调用时随请求体传入，或由 Agent 自行从 Milvus / Redis 读取 |
| **无状态运行** | 每个推理请求独立，不依赖 Session 或本地内存缓存；状态通过 AgentState TypedDict 在工作流内部传递 |
| **同步 + 异步双通道** | 实时推送走 RabbitMQ 消费；定时兜底走 Celery 批量调用 `/agent/analyze_batch` |
| **独立扩缩容** | LangGraph 微服务可水平扩展（多 Worker 实例），通过 RabbitMQ 的 Prefetch Count 控制并发 |

---

### 2.5 混合通信策略

系统采用 **两种通信模式互补**，确保零漏单：

```
┌──────────────────────────────────────────────────────────────┐
│                      实时路径（主要）                           │
│                                                              │
│  评价入库 → Service 发布消息到 RabbitMQ                       │
│           → LangGraph Worker 消费 → 推理完成                   │
│           → 回调 FastAPI /api/v1/callback → 结果入库           │
│                                                              │
│  适用：用户提交评价、小程序实时评价流入                          │
│  延迟：秒级（取决于 LLM 推理耗时 3-30s）                        │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│                      定时兜底（兜底）                           │
│                                                              │
│  Celery Beat 每 5 分钟扫描 MySQL 中 status='pending' 的评价   │
│           → 批量调用 LangGraph /agent/analyze_batch           │
│           → 处理消息队列积压或回调失败的补偿场景                   │
│                                                              │
│  适用：消息队列异常恢复、首次全量导入历史评价数据                 │
│  延迟：分钟级（定时周期 5min）                                  │
└──────────────────────────────────────────────────────────────┘
```

---

### 2.6 RabbitMQ 异步流转时序

```mermaid
sequenceDiagram
    participant User as 评价来源
    participant API as FastAPI Controller
    participant Svc as FastAPI Service
    participant DB as MySQL
    participant MQ as RabbitMQ
    participant Agent as LangGraph Worker

    User->>API: POST /api/v1/reviews (评价数据)
    API->>Svc: create_review(review_data)
    Svc->>DB: INSERT review (status='pending')
    DB-->>Svc: review_id
    Svc->>MQ: publish(review_id, review_payload)
    Svc-->>API: 200 OK {review_id, status:'processing'}
    API-->>User: 评价提交成功

    Note over MQ,Agent: 异步推理（秒级延迟）

    MQ-->>Agent: consume(review_payload)
    Agent->>Agent: LangGraph 工作流执行
    Agent->>API: POST /api/v1/callback {review_id, result}
    API->>Svc: handle_callback(review_id, result)
    Svc->>DB: UPDATE review (status='done', result)
```

**时序要点**：

1. 评价入库后 **立即返回 200**，用户无需等待 Agent 推理完成
2. RabbitMQ 采用 **消息确认机制（ACK）**，Worker 崩溃后消息自动重新入队
3. 推理结果通过 HTTP 回调写入 MySQL，回调失败由定时兜底扫描补偿

---

### 2.7 消息队列设计

**Exchange 与 Queue 拓扑**：

```
Exchange: canteen.review.topic  (Topic 类型)
    │
    ├── Queue: review.analysis.high_priority
    │    Routing Key: review.priority.high
    │    用途: 食安敏感评价（含"异物""变质"等），优先消费
    │
    ├── Queue: review.analysis.normal
    │    Routing Key: review.priority.normal
    │    用途: 常规负面评价，标准优先级
    │
    └── Queue: review.analysis.dlq (死信队列)
         Routing Key: review.priority.dead
         用途: 重试 3 次仍失败的推理任务，人工排查
```

**消息体 JSON Schema**：

```json
{
  "review_id": "R20240601-00125",
  "canteen_id": "CANTEEN_01",
  "priority": "high",
  "payload": {
    "meal_time": "lunch",
    "stall_name": "二楼川湘档口",
    "review_text": "红烧肉咬不动，跟昨天完全不一样",
    "rating": 2,
    "user_id": "U00821"
  },
  "timestamp": "2024-06-01T12:35:00Z",
  "retry_count": 0
}
```

**消费策略**：

- Prefetch Count = 2（每个 Worker 同时只处理 2 条消息，防止 LLM 推理过载）
- 重试上限 = 3 次，超限后进入 DLQ
- TTL = 30 分钟（超时未消费的消息过期，由定时兜底扫描接盘）

---

### 2.8 前端—后端通信

Vue3 前端直连 FastAPI 后端，内部系统无需鉴权：

| 通信方式 | 协议 | 用途 |
|---|---|---|
| **REST API** | HTTP/1.1 | 所有 CRUD 操作：评价管理、日报查询、配置修改、整改单下发 |
| **WebSocket** | WS `/ws/dashboard` | 日报页面实时推送：新评价数增量、告警弹窗、全局情绪指数刷新 |

API 前缀统一为 `/api/v1/`，主要端点：

```
GET    /api/v1/dashboard/summary           # 日报看板数据
GET    /api/v1/dishes/{id}/diagnosis       # 菜品单项诊断报告
GET    /api/v1/config                      # 获取当前配置
PUT    /api/v1/config                      # 更新配置（含 Prompt 版本）
POST   /api/v1/reviews                     # 提交评价（用户端）
POST   /api/v1/reviews/upload              # CSV/Excel 批量上传
POST   /api/v1/callback                    # LangGraph 推理结果回调（内部）
GET    /api/v1/chat                        # 智能问答 SSE 流式响应
```

---

### 2.9 定时任务体系

基于 **Celery Beat + Celery Worker** 实现，与主后端共进程部署：

| 定时任务 | 调度周期 | 说明 |
|---|---|---|
| `fetch_external_reviews` | 每 15 分钟 | 拉取配置中已接入的外部数据源增量评价 |
| `generate_daily_report` | 每日 20:00 | 汇总当日所有评价，生成全局日报（情绪指数、红黑榜、槽点雷达、AI 摘要） |
| `sync_pending_reviews` | 每 5 分钟 | 扫描 MySQL 中 `status='pending'` 超 10 分钟的评价，批量重推 Agent |
| `clean_expired_cache` | 每日 03:00 | 清理 Redis 中过期的临时缓存，保留热配置 |
| `health_check_services` | 每 30 秒 | 检查 Milvus / Ollama / RabbitMQ 连通性，异常时记录告警日志 |

---

### 2.10 Redis 缓存分层

```
Redis（:6379）
├── DB 0: 热配置缓存
│   ├── config:sensitive_words     # 敏感词黑名单（高频读取，从 MySQL 加载）
│   ├── config:warning_thresholds  # 预警阈值（如熔断线、分数刻度）
│   └── config:rag_params          # RAG 检索参数（Top-K、相似度阈值）
│
├── DB 1: 临时状态
│   ├── session:{user_id}          # 智能问答会话上下文（TTL 30min）
│   └── lock:report:{date}         # 日报生成分布式锁（防重生成）
│
└── DB 2: Celery 结果后端
    └── celery-task-*              # 异步任务结果（TTL 1h）
```

热配置加载流程：

```
Service 启动 → 从 MySQL 加载配置 → 写入 Redis DB 0
运行时读取 → Redis GET（命中率 > 99%）
管理员修改配置 → PUT /api/v1/config → Service 写 MySQL + 刷新 Redis 缓存
```

---

### 2.11 数据库职责矩阵

| 存储引擎 | 存储内容 | 典型表 / Collection | 选型理由 |
|---|---|---|---|
| **MySQL** | 业务数据、配置、日志 | `reviews` / `dishes` / `chefs` / `stalls` / `config` / `corrective_actions` / `prompt_versions` / `audit_log` | 事务一致性（配置变更、整改单下发需 ACID）、成熟运维生态 |
| **Milvus** | 向量化知识库 | `sop_collection` / `history_complaints` / `cost_card` / `food_safety` | 高维向量相似检索，毫秒级 ANN，支持 Metadata 过滤 + Partition 隔离 |
| **Redis** | 热配置缓存、会话、Celery 后端 | DB 0/1/2 分库 | 微秒级读写，支撑高频配置读取和实时看板数据刷新 |

---

### 2.12 多租户数据隔离架构

系统支持多食堂独立运营，通过 **MySQL tenant_id + Milvus Partition** 实现物理级数据隔离：

```
MySQL 层:
  reviews 表: tenant_id='CANTEEN_01'  ← 一食堂的评价
  reviews 表: tenant_id='CANTEEN_02'  ← 二食堂的评价
  config 表:  tenant_id + stall_id    ← 按食堂/档口独立配置

Milvus 层:
  sop_collection
    ├── Partition: canteen_01  ← 一食堂的 SOP 向量
    └── Partition: canteen_02  ← 二食堂的 SOP 向量

  history_complaints
    ├── Partition: canteen_01
    └── Partition: canteen_02
```

**检索时的隔离机制**：

```python
# 查询时通过 partition_name 限定范围，结合 Metadata filter 精准过滤
retrieved_docs = vector_store.similarity_search(
    query=query_text,
    k=3,
    partition_name=f"canteen_{tenant_id}",
    filter={
        "dish_id": dish_id,
        "stall_id": stall_id
    }
)
```

> 这种设计确保一食堂（口味清淡）的 SOP 和客诉记录不会被二食堂（口味重口）的检索结果污染，实现真正的差异化品控。

---

### 2.13 安全与合规

| 维度 | 措施 |
|---|---|
| **数据采集合规** | 不使用爬虫抓取外部平台数据；所有评价数据由食堂管理员通过 CSV/Excel 上传或通过自有小程序 API 收集 |
| **数据隐私** | 核心数据（评价、SOP、成本卡）部署在本地服务器或可控云主机，不出食堂内网 |
| **审计追踪** | `audit_log` 表记录所有整改单的下发、修改、驳回操作，可追溯至操作人、时间、IP |
| **Prompt 版本控制** | `prompt_versions` 表存储每次修改的快照，支持一键回滚，防止误改导致 AI 输出质量下降 |
| **LLM 本地推理** | 使用 Ollama 部署 Qwen2.5 本地模型，评价数据不发送至外部 API（如 OpenAI） |
| **访问控制** | 系统部署于食堂内网，通过 Nginx 反向代理统一入口；管理员账号密码登录，支持角色分级（管理员/店长/主厨），非管理员无法查看成本卡和配置页 |
| **传输安全** | 前端至 Nginx 走 HTTPS（需配置 SSL 证书）；内网服务间通信走 HTTP（Docker 内部网络隔离，不暴露至宿主机外） |

---

### 2.14 可观测性

| 维度 | 工具 / 方式 | 监控内容 |
|---|---|---|
| **结构化日志** | Python `logging` JSON 格式 | 每个 LangGraph 节点的入口/出口/耗时/异常；每条评价的完整流转链路 |
| **节点耗时打点** | LangGraph Callback | `review_cleansing_ms` / `dish_routing_ms` / `rag_retrieval_ms` 等指标 |
| **RabbitMQ 积压监控** | RabbitMQ Management API | `queue depth` 超过阈值（200条）时告警 |
| **Milvus 健康检查** | `/agent/health` 端点 | 连接池状态、Collection 可用性、检索延迟 P99 |
| **Celery 监控** | Flower（:5555） | Worker 状态、任务成功率、失败任务详情 |

---

### 2.15 容器化部署清单

```yaml
# docker-compose.yml 核心服务定义
services:
  nginx:
    image: nginx:1.25-alpine
    ports: ["80:80"]
    volumes: ["./nginx.conf:/etc/nginx/nginx.conf"]

  frontend:
    build: ./frontend
    ports: ["3000:3000"]
    depends_on: [backend]

  backend:
    build: ./backend
    ports: ["8000:8000"]
    depends_on: [mysql, redis, rabbitmq]
    environment:
      - MILVUS_HOST=milvus
      - MILVUS_PORT=19530
      - RABBITMQ_URL=amqp://guest:guest@rabbitmq:5672/

  agent:
    build: ./agent
    ports: ["8001:8001"]
    depends_on: [milvus, redis, rabbitmq]
    deploy:
      replicas: 1  # 可扩展至 N 个 Worker

  rabbitmq:
    image: rabbitmq:3.12-management-alpine
    ports: ["5672:5672", "15672:15672"]

  mysql:
    image: mysql:8.0
    ports: ["3306:3306"]
    environment:
      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD}
      MYSQL_DATABASE: canteen_agent
    volumes: ["./data/mysql:/var/lib/mysql"]

  milvus:
    image: milvusdb/milvus:v2.4.0
    ports: ["19530:19530"]
    depends_on: [etcd, minio]
    volumes: ["./data/milvus:/var/lib/milvus"]

  etcd:
    image: quay.io/coreos/etcd:v3.5.5

  minio:
    image: minio/minio:latest

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]

  ollama:
    image: ollama/ollama:latest
    ports: ["11434:11434"]
    volumes: ["./data/ollama:/root/.ollama"]
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

  celery_worker:
    build: ./backend
    command: celery -A app.celery worker -Q default -c 4
    depends_on: [rabbitmq, redis]

  celery_beat:
    build: ./backend
    command: celery -A app.celery beat
    depends_on: [rabbitmq, redis]
```

---

### 2.16 架构决策记录（ADR）

| 决策 ID | 决策内容 | 备选方案 | 选择理由 |
|---|---|---|---|
| **ADR-001** | 选用 RabbitMQ 而非 Redis Streams | Redis Streams | RabbitMQ 提供成熟的死信队列（DLQ）、消息确认（ACK）、Topic Exchange 路由等企业级特性，更适合生产环境的高可靠消息流转 |
| **ADR-002** | LangGraph 作为独立微服务而非嵌入式调用 | 在 FastAPI 进程中直接 import LangGraph | 独立部署可实现 LLM 推理资源隔离（GPU）、独立扩缩容、故障隔离（Agent 崩溃不影响主业务 API） |
| **ADR-003** | Milvus Partition 实现多租户隔离 | 每个食堂创建独立 Collection | Partition 方案在管理复杂度（统一索引参数）和隔离强度之间取得平衡；Collection 方案虽隔离更强但运维成本随食堂数线性增长 |
| **ADR-004** | Ollama 本地部署 Qwen2.5 而非调用云端 API | OpenAI API / 通义千问 API | 评价数据涉及用户隐私和经营数据，本地部署满足合规要求；Qwen2.5 7B 在单卡环境下可流畅运行 |
| **ADR-005** | 固定模板 + LLM 填充整改单 | LLM 自由生成 | 后厨人员需要结构化、可执行的指令而非散文；固定模板保证所有整改单的字段完整性，便于后续统计分析 |

## 3. Agent 推理引擎设计

> **核心定位**：Agent 不是一个简单的文本情感分类器，而是一个**"评价采集 → 菜品消歧 → 知识检索 → 冲突检测 → 置信评估 → 整改生成 → 人机复核"**的完整决策闭环引擎。其架构来源于铜贸易智能 Agent v2.0 的成熟范式，降维复用到食堂品控场景。

### 3.1 设计原则

| 原则 | 说明 |
|---|---|
| **结构化状态驱动** | 所有中间结果通过 `AgentState` TypedDict 传递，节点间解耦、状态可追溯 |
| **按需检索，节省资源** | RAG 检索仅在负面评价出现时触发，正面评价直接归档，避免无效 LLM 调用和向量库连接消耗 |
| **多级消歧，拒绝瞎编** | 菜品归属采用三级匹配 + 兜底人工队列，匹配置信度不足时不向下游生成虚假诊断 |
| **量化置信 + LLM 判定** | 置信度由样本密度、SOP 映射度、历史相似度三维加权计算，不依赖 LLM 主观判断 |
| **固定模板输出** | 整改单采用固定结构化模板，确保后厨一线人员可读、可执行，避免大段散文 |
| **人机协同闭环** | 低置信度或食安敏感场景自动推人工复核，复核结果回写知识库驱动持续学习 |

---

### 3.2 Agent 状态定义（AgentState）

所有工作流节点通过统一的 `TypedDict` 进行状态传递，确保类型安全和字段可追溯：

```python
from typing import TypedDict, List, Dict, Optional

class AgentState(TypedDict):
    # === 原始数据 ===
    raw_reviews: List[Dict]            # 批量流入的原始评价
    filtered_reviews: List[Dict]       # 清洗后的有效评价

    # === 菜品消歧结果 ===
    dish_info: Dict                    # {"dish_id": "D102", "dish_name": "土豆肉丝",
                                       #  "chef_id": "C005", "stall_name": "二楼川湘档口",
                                       #  "meal_time": "lunch", "match_confidence": 0.92}

    # === 风险与知识 ===
    risk_level: int                    # 风险等级 1-5（5=食安异物/变质，3=口味问题，1=无风险）
    knowledge_context: str             # 从 Milvus 检索到的 SOP标准 + 历史客诉 + 成本约束

    # === 分析与决策 ===
    conflict_analysis: Dict            # 冲突检测结构（含 conflict_type / evidence / summary）
    confidence: float                  # 系统综合置信度 0.0-1.0

    # === 输出 ===
    corrective_action: Optional[str]   # 最终生成的整改单文本
    human_review_required: bool        # 是否需要人工复核
```

---

### 3.3 工作流全景

```mermaid
graph TD
    A[📥 接入层: 定时/上传获取评价] --> B(🧹 Review Cleansing 评价清洗与过滤)
    B --> C{是否涉及具体菜品?}
    C -- 纯好评/无关内容 --> END((📦 直接归档))
    C -- 包含负面槽点 --> D(🔍 Dish Routing 菜品实体消歧)

    D --> E{消歧置信度 > 0.6?}
    E -- 否 --> F[🏷️ 人工标注队列] --> END
    E -- 是 --> G(📚 RAG Knowledge Retrieval 知识检索)

    G --> H(⚔️ Conflict Detection 冲突检测)
    H --> I(📊 Confidence Evaluation 置信度评估)

    I --> J{系统置信度 >= 0.75?}
    J -- 否 --> K[👤 Human Review 人工复核]
    K -- 修改/通过 --> L
    K -- 驳回 --> END

    J -- 是 --> L(📋 Action Report 整改单生成)
    L --> M[📤 分发层: 推送给当班主厨]
    M --> END
```

---

### 3.4 节点间数据流契约

每个节点明确定义输入/输出字段，确保独立开发、独立测试：

| 节点 | 输入字段 | 输出字段 | 触发条件 |
|---|---|---|---|
| Review Cleansing | `raw_reviews` | `filtered_reviews` | 无条件（入口节点） |
| Dish Routing | `filtered_reviews` | `dish_info`, `risk_level` | 评价包含负面槽点 |
| RAG Retrieval | `dish_info`, `filtered_reviews` | `knowledge_context` | `dish_info.dish_id != "UNKNOWN"` |
| Conflict Detection | `filtered_reviews`, `dish_info`, `knowledge_context` | `conflict_analysis` | 无条件（RAG 之后） |
| Confidence Evaluation | `conflict_analysis`, `filtered_reviews`, `knowledge_context` | `confidence`, `human_review_required` | 无条件 |
| Action Report | `conflict_analysis`, `knowledge_context`, `dish_info` | `corrective_action` | 置信度 ≥ 0.75 或人工通过 |
| Human Review | 全部上游状态 | 人工确认/驳回标记 | `confidence < 0.75` 或食安触发 |

---

### 3.5 节点详解

#### 3.5.1 Review Cleansing（评价清洗）

**目标**：过滤无意义内容，提取结构化字段，为下游节点提供干净输入。

**处理逻辑**：

```
原始评价 → 格式校验 → 去重 → 无意义过滤 → 结构化提取 → 有效评价队列
```

- **格式校验**：检查必填字段完整性（时间戳、档口名、评论文本）
- **去重**：相同用户短时间内重复提交的相同内容去重
- **无意义过滤**：纯表情、单字灌水（"好" / "嗯" / "."）、广告和无关内容
- **结构化提取**：解析用餐时段（早/中/晚）、档口名称、提及菜品名

**核心代码片段**：

```python
REVIEW_FILTER_PROMPT = """
你是一个餐饮数据预处理专家。判断以下评价是否为有效评价：
1. 纯表情、无意义字符（如 "..."、"👍"）→ 无效
2. 与菜品无关的灌水内容（如闲聊、广告）→ 无效
3. 包含对菜品口味、分量、卫生、服务的具体描述 → 有效

评价内容：{review_text}
仅输出一个单词：VALID 或 INVALID
"""
```

---

#### 3.5.2 Dish Routing（菜品实体消歧）

**目标**：将用户口语化的菜品描述（"二楼那个肉太咸"）精确匹配到系统中的菜品 ID。

**三级梯次匹配策略**：

| 级别 | 策略 | 技术实现 | 成功率 |
|---|---|---|---|
| **L1 精确匹配** | 利用评价关联的档口名 + 菜品名 + 用餐时段直接查库 | SQL 精确查询 | ~60% |
| **L2 向量模糊匹配** | 将评价文本向量化，与当天该档口供应菜单做余弦相似度检索 | `nomic-embed-text` + Milvus | ~30% |
| **L3 LLM 语义推断** | 将时间、档口、评价原文作为上下文交给 LLM 推断 | Qwen2.5 单次调用 | ~8% |

**降级策略**：

> 若三级匹配后置信度仍低于 0.6，将 `dish_info["dish_id"]` 标记为 `"UNKNOWN"`，同时将 `risk_level` **强制提升至 4**。系统通过条件路由将该评价直接送入**人工标注队列**，下游不再生成任何诊断结论，杜绝"猜菜乱改"的风险。

```python
# 菜品消歧核心逻辑
DISH_ROUTING_PROMPT = """
你是食堂菜品管理专家。根据以下信息，从当天供应菜单中推断用户评价的具体菜品：

- 用餐时段：{meal_time}
- 档口名称：{stall_name}
- 用户评论：{review_text}
- 当天供应菜单（JSON）：{daily_menu}

请输出 JSON：
{{"dish_id": "D102", "dish_name": "红烧肉", "confidence": 0.92, "reason": "评价中提到'红烧'和'肉太硬'，匹配菜单中的红烧肉"}}
"""
```

---

#### 3.5.3 RAG Knowledge Retrieval（知识检索）

**目标**：从知识库中拉取该菜品的 SOP 标准、历史客诉和成本约束，为冲突检测和整改生成提供事实依据。

**按需触发策略**：

```
正面评价（评分 ≥ 4，无具体槽点）→ 跳过检索，直接归档
负面评价（评分 ≤ 3，或包含槽点关键词）→ 触发检索
```

**检索维度与来源**：

| 检索维度 | 向量库 Collection | 检索内容 |
|---|---|---|
| SOP 标准卡 | `sop_collection` | 投料比例、烹饪温度、加工时长、出餐标准 |
| 历史客诉 | `history_complaints` | 该菜品过去 30 天的差评记录与已采取措施 |
| 成本约束 | `cost_card` | 单份成本上限，确保整改建议不超预算 |
| 食安规范 | `food_safety` | 食材相克、温控标准、过敏原信息 |

**技术实现**：

```python
from langchain_milvus import MilvusVectorStore

# 连接池方式检索，避免高并发时连接耗尽
vector_store = MilvusVectorStore(
    collection_name="sop_collection",
    connection_args={"host": config.MILVUS_HOST, "port": config.MILVUS_PORT}
)

retrieved_docs = vector_store.similarity_search(
    query=f"{dish_name} {complaint_keywords}",
    k=3,                           # Top-3 最相关结果
    filter={"dish_id": dish_id}    # 按菜品过滤，多租户隔离
)
```

---

#### 3.5.4 Conflict Detection（冲突检测）

**目标**：区分"众口难调"的主观口味差异与"生产批次"的品控波动，避免 Agent 对偏好问题做出错误干预。

**核心算法：时间切片 × 主厨班次交叉对比**

```
同一菜品 + 同一用餐时段 → 按评价维度分组统计 → 交叉对比判断
```

**三种冲突类型**：

| 冲突类型 | 判定逻辑 | 示例 | Agent 行为 |
|---|---|---|---|
| `NO_CONFLICT` | 负面评价占比 < 10%，且无集中槽点 | 零星差评，好评为主 | 归档，不触发整改 |
| `SUBJECTIVE_TASTE` | 同一时段出现两极分化且无主厨/批次变动 | 20% 觉得太辣，80% 觉得不够辣 | 建议维持现状或增加自助调料 |
| `QUALITY_FLUCTUATION` | 历史好评 → 当前集中差评 + 存在主厨/批次变动 | 昨日好评如潮，今日集中反馈"肉太柴" | 触发整改单，指向具体工艺环节 |

**输出格式（JSON Schema）**：

```json
{
  "conflict_type": "QUALITY_FLUCTUATION",
  "confidence": 0.85,
  "analysis_summary": "同一时间段对土豆肉丝咸淡评价呈两极分化，且今日代班厨师非原主厨，判定为主观口味偏好叠加工艺不稳。",
  "evidence": [
    {"review_id": "R001", "text": "今天中午的土豆肉丝咸死卖盐的了。", "dimension": "口味-太咸"},
    {"review_id": "R003", "text": "感觉今天的肉丝没什么味道啊。", "dimension": "口味-太淡"}
  ],
  "dimension_distribution": {
    "口味-太咸": 12, "口味-太淡": 8, "口感-太硬": 3, "分量-太少": 2
  }
}
```

---

#### 3.5.5 Confidence Evaluation（置信度评估）

**目标**：用量化加权取代 LLM 主观判断，给每个诊断结论一个可追溯的可信度分数。

**三维加权模型**：

```python
def calculate_confidence(sample_density_score, sop_match_score, history_similarity_score):
    """
    三维量化加权置信度计算

    Args:
        sample_density_score:    样本密度 (权重 40%) - 负面评价数 / 当日总单量
        sop_match_score:         SOP映射度 (权重 30%) - 槽点能否映射到SOP工艺步骤
        history_similarity_score: 历史相似度 (权重 30%) - 过去30天同类客诉的余弦相似度
    Returns:
        float: 0.0 - 1.0
    """
    return (
        sample_density_score * 0.40 +
        sop_match_score * 0.30 +
        history_similarity_score * 0.30
    )
```

**各因子评分标准**：

| 因子 | 高分 (0.8-1.0) | 中分 (0.5-0.7) | 低分 (0.0-0.4) |
|---|---|---|---|
| **样本密度** | 负面 ≥ 10 条且占比 > 15% | 负面 3-9 条 | 负面 < 3 条 |
| **SOP 映射度** | 槽点能在 SOP 中精确定位工艺参数 | 模糊相关（如"不好吃"） | 无法映射（如"态度差"） |
| **历史相似度** | 过去 30 天有高度相似客诉且已完成闭环 | 有相似记录但未闭环 | 无历史记录或完全不相似 |

---

#### 3.5.6 Action Report（整改单生成）

**目标**：生成后厨一线人员能直接执行的、结构化的操作指令，杜绝大段散文。

**设计原则**：**固定模板 + LLM 内容填充**——模板保证可执行性，LLM 保证灵活性。

**模板结构**：

```text
【品控异常处理单】
━━━━━━━━━━━━━━━━━━━━
■ 菜品信息
  菜品名称：{dish_name}
  所属档口：{stall_name}
  当班主厨：{chef_name}
  发生时段：{meal_time}

■ 问题定位
  {一句话描述核心问题，如"红烧肉口感过柴，今日差评率 12%"}

■ 根因推测
  {结合 SOP 与实际情况的推断，1-2 句}

■ 操作指令
  {可执行的具体操作步骤，含量化参数}

■ 验证标准
  {如何判断问题已解决，可量化的验收条件}
━━━━━━━━━━━━━━━━━━━━
```

**生成示例**：

```text
【品控异常处理单】
━━━━━━━━━━━━━━━━━━━━
■ 菜品信息
  菜品名称：红烧肉
  所属档口：二楼川湘档口
  当班主厨：张师傅
  发生时段：午餐（11:30-13:00）

■ 问题定位
  红烧肉口感过柴，今日差评率 12%（日常均值 3%）。

■ 根因推测
  依据 SOP 规定高压锅压制时间应为 20 分钟，结合今日出餐速度异常偏快，
  推测为收汁与炖煮时间不足导致瘦肉纤维未充分软化。

■ 操作指令
  1. 下一餐次加工时，高压锅上汽后务必压制满 20 分钟（可设定时器）
  2. 出锅前随机抽检 2 块，用筷子穿透肉块验证软烂程度
  3. 当前剩余批次如未售完，回锅加炖 10 分钟后再出餐

■ 验证标准
  筷子可轻松穿透肉块中心，肥肉部分软糯不散，瘦肉不塞牙。
━━━━━━━━━━━━━━━━━━━━
```

---

### 3.6 条件路由与分支逻辑

Agent 工作流中存在两处关键条件分支，由 LangGraph 的 `add_conditional_edges` 实现：

**分支 ①：消歧置信度判断**

```python
def dish_routing_router(state: AgentState) -> str:
    """
    消歧节点的路由函数：
    - 匹配置信度 ≥ 0.6 → 进入 RAG 检索
    - 匹配置信度 < 0.6 → 进入人工标注队列（不生成诊断）
    """
    if state["dish_info"].get("match_confidence", 0) >= 0.6:
        return "rag_retrieval"
    else:
        state["risk_level"] = max(state["risk_level"], 4)
        return "human_annotation_queue"
```

**分支 ②：置信度判断**

```python
def confidence_router(state: AgentState) -> str:
    """
    置信度路由函数：
    - 置信度 ≥ 0.75 → 自动生成整改单并分发
    - 置信度 < 0.75 或触发食安敏感词 → 推人工复核
    """
    if state["confidence"] >= 0.75 and state["risk_level"] < 5:
        return "action_report"
    else:
        state["human_review_required"] = True
        return "human_review"
```

---

### 3.7 人机协同闭环

**触发条件**（满足任一即触发）：

| 条件 | 场景 |
|---|---|
| 系统置信度 < 0.75 | 评价模糊、证据不足，Agent 无法做出高置信判断 |
| 触发食安敏感词 | 评价含"异物""变质""肚子疼""钢丝球"等黑名单关键词 |
| `risk_level >= 4` | 消歧失败导致风险升级，或涉及食品安全 |

**推送路径**：

```
Agent 工作流暂停
    → 企业微信 Webhook 推送告警卡片（含菜品、风险等级、原始评价摘要）
    → 店长点击卡片进入系统「决策沙盘页」
    → 左侧：Agent 诊断报告 + [采纳] / [修改后下发] / [驳回] 按钮
    → 中间：原始差评列表，食安敏感词自动标红
    → 右侧：标准 SOP 参数 + 历史客诉趋势图
    → 店长一键操作 → 结果回写
```

**持续学习闭环**：

```python
# 店长操作后，反馈回写 Milvus 知识库
def feedback_loop(review_id: str, action: str, correction: str):
    """
    action ∈ {"approved", "modified", "rejected"}
    """
    feedback_vector = embedding_model.embed(correction)
    vector_store.insert(
        collection="history_complaints",
        vector=feedback_vector,
        metadata={
            "review_id": review_id,
            "action": action,
            "correction": correction,
            "timestamp": datetime.now().isoformat()
        }
    )
```

> 店长点击"采纳/修改/驳回"后，处理结果自动向量化并实时追加到该菜品的 `history_complaints` 集合中。当下次遇到类似评价时，Agent 的「历史相似度」因子会命中该记录，**避免重复犯同样的判断错误**。

#### 整改单执行追踪

整改单下发至后厨后，系统通过以下状态机追踪执行闭环：

```
下发 (dispatched)
    → 后厨确认收到 (acknowledged)  ← 当班主厨在系统内点击「确认收到」
    → 执行中 (in_progress)          ← 主厨点击「开始执行」
    → 已完成 (completed)            ← 主厨点击「执行完成」+ 填写执行备注
    → 待验证 (pending_verification)  ← 下一餐次自动追踪该菜品的差评变化
    → 已验证 (verified)             ← 差评率回归正常后自动标记
```

**追踪数据表（corrective_actions 扩展字段）**：

```sql
ALTER TABLE corrective_actions ADD COLUMN
    execute_status  ENUM('dispatched','acknowledged','in_progress','completed',
                         'pending_verification','verified','rejected') DEFAULT 'dispatched',
    acknowledged_at DATETIME,
    executed_at     DATETIME,
    completed_at    DATETIME,
    verified_at     DATETIME,
    execute_note    TEXT,           -- 主厨执行备注
    effect_score    DECIMAL(3,2),   -- 效果评分（整改后差评率变化，自动计算）
    overdue_alert   BOOLEAN DEFAULT FALSE;  -- 超时未执行告警
```

**超时告警**：整改单下发后 4 小时内未确认收到 → 系统标记 `overdue_alert=TRUE` → 日报页面展示超时未处理整改单列表。

**效果自动验证**：整改单标记为 `completed` 后，系统在下一餐次自动追踪该菜品的差评率。若差评率从 12.8% 降至 3% 以下 → `effect_score = 0.95`，自动标记为 `verified`。若未见改善 → 重新触发新一轮诊断。

---

### 3.8 LangGraph 完整工作流代码框架

```python
from langgraph.graph import StateGraph, END

def create_canteen_agent_workflow():
    """
    食堂品控 Agent 完整工作流定义
    返回值：编译后的 LangGraph 可执行图
    """
    workflow = StateGraph(AgentState)

    # ===== 注册节点 =====
    workflow.add_node("review_cleansing", review_cleansing_node)
    workflow.add_node("dish_routing", dish_routing_node)
    workflow.add_node("rag_retrieval", rag_retrieval_node)
    workflow.add_node("conflict_detection", conflict_detection_node)
    workflow.add_node("confidence_evaluation", confidence_evaluation_node)
    workflow.add_node("action_report", action_report_node)
    workflow.add_node("human_review", human_review_node)           # 人工复核节点
    workflow.add_node("human_annotation", human_annotation_node)   # 人工标注队列
    workflow.add_node("archive", archive_node)                     # 归档节点

    # ===== 定义边 =====
    workflow.set_entry_point("review_cleansing")
    workflow.add_edge("review_cleansing", "dish_routing")

    # 条件分支 ①：消歧路由
    workflow.add_conditional_edges(
        "dish_routing",
        dish_routing_router,
        {
            "rag_retrieval": "rag_retrieval",
            "human_annotation": "human_annotation"
        }
    )

    workflow.add_edge("rag_retrieval", "conflict_detection")
    workflow.add_edge("conflict_detection", "confidence_evaluation")

    # 条件分支 ②：置信度路由
    workflow.add_conditional_edges(
        "confidence_evaluation",
        confidence_router,
        {
            "action_report": "action_report",
            "human_review": "human_review"
        }
    )

    workflow.add_edge("action_report", "archive")
    workflow.add_edge("human_review", "archive")
    workflow.add_edge("human_annotation", END)

    workflow.add_edge("archive", END)

    return workflow.compile()
```

---

### 3.9 异常处理与降级策略

| 异常场景 | 降级策略 | 恢复机制 |
|---|---|---|
| **Milvus 向量库不可用** | 跳过 RAG 检索节点，仅以 SOP 静态规则库兜底；`knowledge_context` 填充为本地缓存的菜品基础参数 | 每 30s 健康检查，恢复后自动重连 |
| **LLM 调用超时（>30s）** | 单节点重试 2 次，仍失败则 `risk_level += 1` 并路由至人工复核 | 降级日志记录，支持事后批量重新推理 |
| **评价数据格式异常** | 格式不合规的评价在 Cleansing 节点被标记为 `INVALID`，不入下游 | 原始数据保留在 `raw_reviews`，支持回溯 |
| **Dish Routing 三级匹配均失败** | 标记 `UNKNOWN`，强制进入人工标注队列 | 人工标注后写入菜品映射表，后续同款描述可命中 L1 精确匹配 |
| **整改单生成结果为空** | 使用预设的通用兜底模板（"请后厨主管根据差评内容进行人工核查"） | 触发运营告警，通知技术团队排查 |

---

### 3.10 端到端案例走查

以下用一条真实评论完整走查 Agent 工作流的各节点输入输出：

**原始评价**：
> "今天中午二楼川湘档口的红烧肉咬都咬不动，跟昨天完全不是一个水平，是不是换人了？"

| 节点 | 输入 | 输出 |
|---|---|---|
| **Review Cleansing** | 原始评价文本 | `filtered_review`: `{meal_time: "lunch", stall: "二楼川湘档口", complaint: "红烧肉咬不动", severity: 3}` |
| **Dish Routing** | `filtered_review` + 当天菜单 | `dish_info`: `{dish_id: "D045", dish_name: "红烧肉", chef_id: "C012" (代班), match_confidence: 0.94}` |
| **RAG Retrieval** | `dish_id: D045` + 槽点"咬不动" | `knowledge_context`: "SOP 规定高压锅压制 20 分钟；历史记录：3 月 15 日类似客诉，原因为炖煮时间不足" |
| **Conflict Detection** | 差评集中度 + SOP + 主厨变动 | `conflict_type: QUALITY_FLUCTUATION`，`evidence: [R045, R046, R047]`，主厨从李师傅变为代班张师傅 |
| **Confidence Evaluation** | 样本密度 0.9 × 0.4 + SOP 映射 1.0 × 0.3 + 历史相似 0.8 × 0.3 | `confidence: 0.90` |
| **Action Report** | 全部上游上下文 | 整改单 → 定位："红烧肉口感过柴" → 根因："今日代班厨师炖煮时间未达 SOP 标准" → 指令："高压锅上汽后压制满 20 分钟" → 分发至当班主厨 |
| **Human Review** | — | 未触发（`confidence ≥ 0.75` 且无食安敏感词） |

## 4. Agent 配置与参数化管理

> **核心定位**：Agent 配置页是 LangGraph 工作流各节点的**动态参数化面板**。管理员通过前端修改配置 → Service 层写 MySQL + 刷新 Redis → Agent 节点下次执行时从 Redis 读取最新值，**无需重启微服务**，秒级生效。

---

### 4.1 四大配置维度总览

| 维度 | 控制内容 | 影响节点 | 典型配置项 |
|---|---|---|---|
| **预警规则与触发阈值** | 决定 Agent 何时告警、何时推人工 | Review Cleansing / Confidence Evaluation | 客诉熔断线、情感评分刻度、敏感词黑名单 |
| **RAG 检索与知识库调度** | 控制向量检索的精度与连接稳定性 | RAG Retrieval | Top-K、相似度阈值、Milvus 连接参数 |
| **数据源接入** | 控制评价数据的入口与格式 | Review Cleansing（入口） | CSV/Excel 上传、API 密钥管理 |
| **AI 推理参数** | 微调 LLM 的思考方式与输出风格 | 全部 LLM 调用节点 | Temperature、System Prompt、模型选择 |

---

### 4.2 三级继承模型

配置采用 **全局默认 → 食堂级覆盖 → 档口级覆盖** 的三级继承机制。下级未设置时自动继承上级，下级显式设置后覆盖上级。

```
全局默认配置 (Global)
    │
    ├── 一食堂 (CANTEEN_01) ── 继承全局，但覆写了「客诉熔断线=8条」
    │       │
    │       ├── 川湘档口 ── 继承一食堂，未覆写
    │       └── 面食档口 ── 继承一食堂，覆写了「敏感词」追加"不熟"
    │
    └── 二食堂 (CANTEEN_02) ── 全部继承全局默认，未做任何覆写
```

**前端 UI 示意**：

> 当管理员在「一食堂 → 川湘档口」层级查看配置时：
> - 客诉熔断线：**8 条**（已覆写 · 继承自一食堂）
> - 敏感词黑名单：「异物, 变质, 肚子疼, ...」（未覆写 · 继承自全局）
>
> 未覆写的字段以灰色斜体展示继承来源，点击「覆盖」按钮后可输入新值。

**配置优先级规则（伪代码）**：

```python
def resolve_config(key: str, canteen_id: str, stall_id: str) -> Any:
    """
    按 stall → canteen → global 优先级逐级查找
    """
    # 1. 先查档口级
    value = db.query(f"SELECT value FROM config WHERE key='{key}' AND stall_id='{stall_id}'")
    if value is not None:
        return value
    # 2. 再查食堂级
    value = db.query(f"SELECT value FROM config WHERE key='{key}' AND canteen_id='{canteen_id}' AND stall_id IS NULL")
    if value is not None:
        return value
    # 3. 最后回退全局默认
    return db.query(f"SELECT value FROM config WHERE key='{key}' AND canteen_id IS NULL")
```

---

### 4.3 配置存储与生效链路

```mermaid
sequenceDiagram
    participant Admin as 管理员
    participant Vue as Vue3 前端
    participant Ctrl as Controller
    participant Svc as Service
    participant DB as MySQL
    participant Redis as Redis
    participant Agent as LangGraph 节点

    Admin->>Vue: 修改预警阈值: 5 → 8
    Vue->>Ctrl: PUT /api/v1/config {key:'warning_threshold', value:8}
    Ctrl->>Svc: update_config(config_data)
    Svc->>DB: UPDATE config SET value=8 WHERE key='warning_threshold'
    DB-->>Svc: OK
    Svc->>Redis: SET config:warning_threshold 8
    Svc-->>Ctrl: 200 OK
    Ctrl-->>Vue: 配置已保存
    Vue-->>Admin: ✅ 保存成功

    Note over Agent,Redis: 下次推理时生效（秒级）

    Agent->>Redis: GET config:warning_threshold
    Redis-->>Agent: 8
    Agent->>Agent: 使用新阈值执行推理
```

**关键设计要点**：

| 要点 | 说明 |
|---|---|
| **MySQL 为真实源** | 所有配置以 MySQL 为准，Redis 为加速缓存层。Agent 启动或 Redis 不可用时从 MySQL 加载 |
| **Redis 缓存策略** | 无 TTL（热配置不自动过期），由 Service 层在配置变更时主动刷新。重启时全量从 MySQL 同步 |
| **Agent 读取方式** | 每个推理请求在入口节点（Review Cleansing）一次性从 Redis 读取全部配置到 `AgentState`，下游节点从 State 中读取，避免重复网络 I/O |
| **生效延迟** | 秒级——取决于当前正在执行的推理任务何时结束。无任务时下次请求即刻生效 |

---

### 4.4 维度一：预警规则与触发阈值

#### 4.4.1 客诉数量熔断线

| 配置项 | 默认值 | 可配范围 | 说明 |
|---|---|---|---|
| `warning_threshold_per_meal` | 5 条 | 1-50 | 同一菜品在同一用餐时段内负面评价数 ≥ 此值时，`risk_level` 自动提升至 4，强制推人工复核 |
| `food_safety_immediate` | 1 条 | 1-5 | 食安敏感词命中评价数 ≥ 此值时，`risk_level` 直接升至 5，阻断自动流转 |

#### 4.4.2 情感评分阈值

| 配置项 | 默认值 | 可配范围 | 说明 |
|---|---|---|---|
| `severity_severe` | 0.3 | 0.0-0.5 | 大模型情感评分 ≤ 此值的评价标记为"严重客诉"，触发食安级别关注 |
| `severity_optimization` | 0.6 | 0.4-0.8 | 评分在 `(severity_severe, severity_optimization]` 区间的评价标记为"口味优化"类，走标准整改流程 |
| `severity_normal` | 0.8 | — | 评分 > 此值的为正面/中性评价，直接归档 |

#### 4.4.3 敏感词黑名单

- **管理方式**：前端 textarea 逐行输入，每行一个关键词
- **出厂默认预置**：`异物 | 变质 | 肚子疼 | 钢丝球 | 头发 | 虫子 | 拉肚子 | 食物中毒`
- **匹配模式**：子串匹配（评论中出现黑名单中的任意词即命中）
- **可追加自定义**：管理员可为每个食堂/档口独立追加关键词（如素食档口追加"肉末""荤油"）

**敏感词命中后的处理链路**：

```
评价进入 Review Cleansing
    → 文本与黑名单做子串匹配（从 Redis DB 0 读取黑名单）
    → 命中 → risk_level = max(risk_level, 5)
    → AgentState 进入 Conflict Detection 前，条件路由检测 risk_level >= 5
    → 不执行自动推理，直接路由至 Human Review
    → 系统界面标红命中的敏感词，前端展示告警横幅
```

---

### 4.5 维度二：RAG 检索与知识库调度

| 配置项 | 默认值 | 可配范围 | 映射至 LangGraph 参数 |
|---|---|---|---|
| `milvus_host` | `localhost` | IP/Domain | `MilvusVectorStore(connection_args={"host": ...})` |
| `milvus_port` | `19530` | 1-65535 | `MilvusVectorStore(connection_args={"port": ...})` |
| `milvus_collection` | `sop_collection` | Collection 名 | `MilvusVectorStore(collection_name=...)` |
| `rag_top_k` | 3 | 3-5 | `vector_store.similarity_search(k=...)` |
| `rag_similarity_threshold` | 0.6 | 0.0-1.0 | 过滤相似度低于此值的结果（`score >= threshold` 才保留） |
| `rag_connection_pool_size` | 10 | 5-50 | langchain_milvus 内部连接池大小，对应饭点高并发场景 |

> `rag_top_k` 和 `rag_similarity_threshold` 对所有 Collection（SOP / 历史客诉 / 成本卡 / 食安规范）统一生效，不做 Collection 级别的独立配置，以降低管理复杂度。

---

### 4.6 维度三：数据源接入配置

所有评价数据通过**纯手工上传**方式导入系统，不使用爬虫：

| 配置项 | 说明 |
|---|---|
| **文件上传** | 支持 CSV / Excel（`.csv`, `.xlsx`, `.xls`），单文件上限 50MB |
| **列名校验** | 上传时前端校验必填列：`timestamp`、`stall_name`、`dish_name`、`rating`、`review_text`；缺失列时拒绝上传并提示 |
| **API 密钥管理** | 若未来接入自有小程序评价 API，可在此页面管理 API Token（生成 / 吊销 / 权限范围）。当前版本仅支持手工上传 |

文件上传与 API 密钥管理集成在**数据源接入 Tab**的同一页面下，表单区 + 已上传文件列表 + 密钥管理区三段布局。

---

### 4.7 维度四：AI 推理参数

| 配置项 | 默认值 | 可配范围 | 说明 |
|---|---|---|---|
| `llm_temperature` | 0.3 | 0.0-2.0 | 工作流统一设置，控制所有 LLM 调用节点的输出发散程度。低值保证诊断一致性，高值用于口味创新建议（如第 7 章智能问答可独立覆盖） |
| `llm_model` | `qwen2.5:7b-instruct` | 已安装模型列表 | 通过 Ollama API 获取可用模型列表，管理员从下拉菜单选择 |
| `system_prompt` | （见下方默认 Prompt） | 文本区域 | 管理员可编辑 Agent 全局系统级 Prompt，微调分析倾向（如偏向"提升口味"或"控制成本"） |

**System Prompt 默认模板**：

```text
你是一个资深餐饮品控专家，服务于食堂后厨质量改进。
在分析每一条评价时，请遵循以下原则：
1. 优先关注食品安全相关投诉（异物、变质、过敏原）
2. 区分主观口味偏好与客观品控问题
3. 给出的整改建议必须具体、可量化、可执行
4. 整改建议需考虑单份成本约束，不超预算
5. 语气专业但不傲慢，面向后厨一线人员
```

---

### 4.8 Prompt 版本控制

System Prompt 的每次修改自动存档，支持从历史列表中任意版本回滚：

**`prompt_versions` 表结构**：

```sql
CREATE TABLE prompt_versions (
    id          BIGINT PRIMARY KEY AUTO_INCREMENT,
    config_id   VARCHAR(64)  NOT NULL,       -- 配置标识（如 'global', 'canteen_01'）
    version     INT          NOT NULL,       -- 版本号（自增）
    content     TEXT         NOT NULL,       -- Prompt 完整内容
    summary     VARCHAR(200),                -- 变更摘要（管理员手动填写）
    created_by  VARCHAR(64),                 -- 操作人
    created_at  DATETIME     DEFAULT NOW(),
    INDEX idx_config_version (config_id, version DESC)
);
```

**前端交互流程**：

```
管理员编辑 System Prompt
    → 点击「保存」→ 弹出摘要输入框（可选）
    → Service 向 prompt_versions 插入新版本（version = max(version) + 1）
    → 同步更新 Redis 中 config:system_prompt 为最新内容
    → 即时生效

管理员需要回滚
    → 点击「版本历史」→ 展示版本列表（时间戳 + 摘要 + 内容预览）
    → 选择目标版本 → 点击「回滚到此版本」
    → Service 将该版本内容复制为新版本（version = max(version) + 1），不删除旧版本
    → 刷新 Redis → 即时生效
```

> 回滚操作本身也会产生一条新的 `prompt_versions` 记录（`summary` 自动标记为 `"回滚至 version N"`），确保完整的审计追溯。

---

### 4.9 配置项与 AgentState 字段映射

| 配置项 | Redis Key | AgentState 消费字段 | 消费节点 |
|---|---|---|---|
| 敏感词黑名单 | `config:sensitive_words` | `risk_level`（命中后升至 5） | Review Cleansing |
| 客诉熔断线 | `config:warning_threshold` | `human_review_required`（判定条件） | Conflict Detection |
| 情感评分阈值 | `config:severity_thresholds` | `risk_level` 初始赋值 | Review Cleansing |
| RAG Top-K | `config:rag_top_k` | `knowledge_context`（检索结果条数） | RAG Retrieval |
| RAG 相似度阈值 | `config:rag_similarity_threshold` | `knowledge_context`（结果过滤） | RAG Retrieval |
| Milvus 连接参数 | `config:milvus_*` | `knowledge_context`（检索可用性） | RAG Retrieval |
| LLM Temperature | `config:llm_temperature` | 所有 LLM 调用 | 全部 LLM 节点 |
| System Prompt | `config:system_prompt` | 所有 LLM 调用的系统上下文 | 全部 LLM 节点 |

---

### 4.10 前端页面布局设计

配置管理页面集成在 Vue3 前端中，采用 **四 Tab + 层级选择器** 的布局：

```
┌──────────────────────────────────────────────────────────┐
│  Agent 配置管理                                           │
│                                                          │
│  配置层级: [全局默认 ▾]  [一食堂 ▾]  [川湘档口 ▾]         │
│                                                          │
│  ┌─ 预警规则 ─┬─ RAG检索 ─┬─ 数据源 ─┬─ AI推理 ─┐       │
│  │            │           │          │          │       │
│  │  客诉熔断线:  [5] 条   │          │          │       │
│  │  严重评分阈值: [0.3]   │          │          │       │
│  │  优化评分阈值: [0.6]   │          │          │       │
│  │                       │          │          │       │
│  │  敏感词黑名单:         │          │          │       │
│  │  ┌──────────────────┐ │          │          │       │
│  │  │ 异物             │ │          │          │       │
│  │  │ 变质             │ │          │          │       │
│  │  │ 肚子疼           │ │          │          │       │
│  │  │ ...              │ │          │          │       │
│  │  └──────────────────┘ │          │          │       │
│  │  [+ 添加关键词]       │          │          │       │
│  │                       │          │          │       │
│  │            [保存配置]  [版本历史] [导出] [导入]│       │
│  └───────────────────────┴──────────┴──────────┴───────┘
│                                                          │
│  ┌─ 继承状态提示 ───────────────────────────────────┐    │
│  │  客诉熔断线「8条」已覆写（一食堂级）                │    │
│  │  敏感词黑名单「未覆写」继承自全局默认               │    │
│  └─────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────┘
```

---

### 4.11 配置校验规则

校验分两层：**前端即时校验**（Pydantic schema 同步至前端）+ **后端 Service 层二次校验**：

| 配置项 | 校验规则 | 错误提示 |
|---|---|---|
| `warning_threshold_per_meal` | `1 ≤ value ≤ 50, type=int` | "熔断线必须在 1-50 之间" |
| `severity_severe` / `severity_optimization` | `0.0 ≤ value ≤ 1.0, type=float`；且 `severe < optimization` | "阈值范围为 0.0-1.0，且严重阈值需小于优化阈值" |
| `rag_top_k` | `value ∈ {3, 4, 5}` | "Top-K 仅支持 3、4、5" |
| `rag_similarity_threshold` | `0.0 ≤ value ≤ 1.0, type=float` | "相似度阈值范围为 0.0-1.0" |
| `llm_temperature` | `0.0 ≤ value ≤ 2.0, type=float` | "Temperature 范围为 0.0-2.0" |
| `milvus_port` | `1 ≤ value ≤ 65535, type=int` | "端口号范围为 1-65535" |
| 敏感词黑名单 | 每行 ≤ 50 字符，总行数 ≤ 500，不含特殊正则符号 | "单关键词不超过 50 字符" |
| CSV/Excel 列名 | 必须包含 `timestamp, stall_name, dish_name, rating, review_text` | "缺少必填列: {missing_columns}" |

---

### 4.12 配置导入导出

支持将当前层级的配置导出为 JSON，便于跨食堂迁移或备份：

**导出格式**：

```json
{
  "version": "1.0",
  "exported_at": "2024-06-01T15:30:00Z",
  "scope": {"canteen_id": "CANTEEN_01", "stall_id": null},
  "config": {
    "warning_threshold_per_meal": 8,
    "severity_severe": 0.3,
    "severity_optimization": 0.6,
    "sensitive_words": ["异物", "变质", "肚子疼", "钢丝球"],
    "rag_top_k": 3,
    "rag_similarity_threshold": 0.6,
    "llm_temperature": 0.3,
    "system_prompt": "你是一个资深餐饮品控专家..."
  }
}
```

**导入行为**：
- 只导入当前选择层级（不会越级写入），覆盖该层级已覆写的字段
- 未覆写字段（继承自上级的）不受导入影响
- 导入前弹出预览对比弹窗（新值 vs. 旧值），管理员确认后生效

## 5. 数据采集与 ETL 层

> **核心定位**：数据采集与 ETL 层是系统唯一的数据入口。所有评价数据由食堂管理员通过 CSV/Excel 手工上传，不走爬虫，经过「编码检测 → 列名校验 → 字段校验 → 去重 → 两阶段导入（预览→确认）」流水线后，写入 MySQL 并触发 Agent 推理。

---

### 5.1 设计原则

| 原则 | 说明 |
|---|---|
| **纯手工上传，零爬虫** | 所有数据来源均为管理员主动上传的 CSV/Excel 文件，系统不发起任何外部网络请求抓取数据 |
| **全量校验，整批回滚** | 文件中任一行数据格式不合法，整批拒绝导入并返回详细错误清单，保证数据库不留脏数据 |
| **完全去重** | 以 `(user_id, dish_name, stall_name, meal_time)` 四元组为唯一约束，重复提交直接拒绝 |
| **原始数据永存** | 所有评价原始数据在 MySQL 中永久保留，不做定期归档或删除，支撑长期趋势分析 |
| **预览后确认** | 上传后先展示前 10 行解析结果，管理员确认字段映射无误后才正式执行导入 |

---

### 5.2 支持的文件格式与编码

| 格式 | 扩展名 | 单文件上限 | 编码策略 |
|---|---|---|---|
| **CSV** | `.csv` | 50 MB | `chardet` 自动检测编码（UTF-8 / GBK / GB2312 / GB18030），检测结果在前端预览页展示，管理员可手动纠正 |
| **Excel** | `.xlsx`, `.xls` | 50 MB | 使用 `openpyxl`（.xlsx）和 `xlrd`（.xls）解析，Excel 自带编码元数据，无需额外检测 |

---

### 5.3 必填列 Schema

上传文件必须包含以下列（列名不区分大小写，支持中英文列名自动映射）：

| 列名（标准） | 列名（中文别名） | 类型 | 校验规则 |
|---|---|---|---|
| `timestamp` | `时间戳` / `评价时间` / `日期` | datetime | 格式 `YYYY-MM-DD HH:MM:SS` 或 ISO-8601 |
| `stall_name` | `档口名` / `档口` / `窗口` | string | 非空，≤ 100 字符 |
| `dish_name` | `菜品名` / `菜品` / `菜名` | string | 非空，≤ 100 字符 |
| `rating` | `评分` / `打分` / `星级` | integer | 1-5（1=极差，5=极好） |
| `review_text` | `评价内容` / `评论` / `意见` | string | 非空，≤ 2000 字符 |
| `user_id` | `用户ID` / `用户` / `工号` | string | 可选列（缺失时系统自动生成匿名 ID） |
| `meal_time` | `用餐时段` / `餐次` | string | 可选列（缺失时根据 timestamp 自动推算：06:00-10:00→breakfast，10:00-14:00→lunch，14:00-18:00→dinner，其他→other） |

**列名映射逻辑**：

```python
COLUMN_ALIASES = {
    "timestamp":    ["timestamp", "时间戳", "评价时间", "日期", "date", "time"],
    "stall_name":   ["stall_name", "档口名", "档口", "窗口", "stall", "window"],
    "dish_name":    ["dish_name", "菜品名", "菜品", "菜名", "dish", "food"],
    "rating":       ["rating", "评分", "打分", "星级", "score", "star"],
    "review_text":  ["review_text", "评价内容", "评论", "意见", "review", "comment", "content"],
    "user_id":      ["user_id", "用户ID", "用户", "工号", "user", "uid", "employee"],
    "meal_time":    ["meal_time", "用餐时段", "餐次", "meal", "period"],
}
```

---

### 5.4 两阶段导入流程

```mermaid
sequenceDiagram
    participant Admin as 管理员
    participant Vue as Vue3 前端
    participant API as FastAPI Controller
    participant Svc as Service
    participant DB as MySQL
    participant MQ as RabbitMQ

    Note over Admin,Vue: ====== 阶段一：上传与预览 ======

    Admin->>Vue: 选择文件（CSV/Excel）
    Vue->>Vue: 前端解析文件，检测编码
    Vue->>Vue: 提取列名，自动映射为标准列名
    Vue->>API: POST /api/v1/reviews/preview {columns, sample_rows}
    API->>Svc: preview_import(columns, rows)
    Svc-->>API: {mapped_columns, validation_errors[], preview_rows[10]}
    API-->>Vue: 预览数据 + 列映射结果
    Vue-->>Admin: 展示前 10 行 + 列映射确认界面

    Note over Admin,Vue: ====== 阶段二：确认导入 ======

    Admin->>Vue: 确认列映射无误，点击「确认导入」
    Vue->>API: POST /api/v1/reviews/upload {file, column_mapping, canteen_id}
    API->>Svc: execute_import(file, column_mapping, canteen_id)
    Svc->>Svc: 逐行校验（类型/范围/非空/唯一性）
    alt 校验失败
        Svc-->>API: 422 {error: "第 15 行 rating 超出范围", failed_rows: [...]}
        API-->>Vue: 错误详情（含行号、列名、错误原因）
        Vue-->>Admin: 显示完整错误列表，整批回滚
    else 校验通过
        Svc->>DB: BEGIN TRANSACTION
        Svc->>DB: INSERT INTO reviews (批量写入，含去重检查)
        Svc->>DB: COMMIT
        Svc->>MQ: 逐条发布评价到 RabbitMQ（触发 Agent 推理）
        Svc-->>API: 200 {imported_count: 385, skipped_duplicates: 12}
        API-->>Vue: 导入成功
        Vue-->>Admin: ✅ 成功导入 385 条评价（12 条重复已自动跳过）
    end
```

---

### 5.5 逐行校验规则

Service 层在导入阶段对每一行执行以下校验，全量校验通过后才开启数据库事务：

| 校验项 | 规则 | 错误示例 |
|---|---|---|
| **类型校验** | `rating` 必须为整数，`timestamp` 必须为合法 datetime | `rating="还行"` → 类型错误 |
| **范围校验** | `rating` 必须在 1-5 之间 | `rating=6` → 超出范围 |
| **非空校验** | `stall_name`、`dish_name`、`review_text` 不可为空 | `review_text=""` → 空值 |
| **长度校验** | `stall_name` ≤ 100、`dish_name` ≤ 100、`review_text` ≤ 2000 | 评价内容超长 |
| **唯一性校验** | `(user_id, dish_name, stall_name, meal_time)` 四元组不可重复 | 同用户同菜品同餐次重复提交 |

**去重策略**：完全去重——以四元组为唯一约束。已存在于 `reviews` 表中的重复记录在导入时自动跳过，不计入失败，仅在前端提示跳过数量。MySQL 层面通过联合唯一索引兜底：

```sql
ALTER TABLE reviews ADD UNIQUE INDEX idx_review_unique
    (tenant_id, user_id, dish_name, stall_name, meal_time);
```

---

### 5.6 整批回滚机制

任一单行校验失败 → **整批数据全部拒绝，不部分写入**。

```python
# Service 层伪代码
def execute_import(file, column_mapping, canteen_id):
    rows = parse_file(file, column_mapping)
    errors = []

    # 全量校验阶段（不写库）
    for idx, row in enumerate(rows):
        err = validate_row(row)
        if err:
            errors.append({"row": idx + 1, "errors": err})

    if errors:
        raise ImportValidationError(errors)  # 整批拒绝

    # 批量写入阶段（事务保护）
    with db.transaction():
        for row in rows:
            try:
                db.insert("reviews", row)
            except DuplicateError:
                skipped_count += 1  # 重复跳过
            except Exception:
                db.rollback()
                raise  # 非重复错误则回滚整批
```

**前端错误展示**：

```
❌ 导入失败：文件中共 2 行数据不合法

第 15 行：
  - rating: 值"6"超出范围（1-5）
第 23 行：
  - review_text: 不能为空
  - dish_name: 不能为空

请修正后重新上传。已回滚所有数据，数据库未受影响。
```

---

### 5.7 数据标准化（ETL 归一化）

导入完成后，Service 层在写入 MySQL 前执行以下标准化处理：

| 标准化项 | 输入示例 | 输出 | 方法 |
|---|---|---|---|
| **档口名归一** | "二楼 川湘档口" / "2楼川湘" / "川湘窗口" | `二楼川湘档口` | 去除多余空格；LLM 小模型归一化映射到系统注册档口名 |
| **菜品名归一** | "土豆烧肉" / "土豆炖肉" / "红烧土豆肉" | `土豆烧肉` | 向量相似度 + 别名表匹配 |
| **用餐时段推算** | timestamp = `12:35`（无 meal_time 列） | `lunch` | 按时间窗推算 |
| **评分归一** | 原始评分 1-10 分制表格 | 线性映射为 1-5 | `new_rating = ceil(original * 5 / 10)` |
| **空白清理** | `"  太咸了  !!  "` | `"太咸了 !!"` | 首尾去空格，多空格压缩 |

---

### 5.8 原始数据存储（reviews 表 DDL）

```sql
CREATE TABLE reviews (
    id              BIGINT PRIMARY KEY AUTO_INCREMENT,
    tenant_id       VARCHAR(32)  NOT NULL,        -- 多租户标识
    user_id         VARCHAR(64)  NOT NULL,        -- 用户标识
    stall_name      VARCHAR(100) NOT NULL,        -- 档口名（归一化后）
    stall_name_raw  VARCHAR(100),                 -- 档口名（原始值，保留溯源）
    dish_name       VARCHAR(100) NOT NULL,        -- 菜品名（归一化后）
    dish_name_raw   VARCHAR(100),                 -- 菜品名（原始值）
    rating          TINYINT      NOT NULL,        -- 评分 1-5
    review_text     TEXT         NOT NULL,        -- 评价原文
    meal_time       ENUM('breakfast','lunch','dinner','other') NOT NULL,
    review_time     DATETIME     NOT NULL,        -- 评价时间戳
    status          ENUM('pending','processing','done','failed') DEFAULT 'pending',
    risk_level      TINYINT      DEFAULT 1,       -- Agent 判定后的风险等级
    agent_result    JSON,                          -- Agent 推理结果（JSON）
    corrective_action_id BIGINT,                   -- 关联的整改单 ID
    source_file     VARCHAR(255),                  -- 来源文件名（溯源）
    created_at      DATETIME     DEFAULT NOW(),
    updated_at      DATETIME     DEFAULT NOW() ON UPDATE NOW(),

    INDEX idx_tenant_time  (tenant_id, review_time),
    INDEX idx_dish_time    (dish_name, review_time),
    INDEX idx_status       (status),
    UNIQUE INDEX idx_review_unique (tenant_id, user_id, dish_name(50), stall_name(50), meal_time)
);
```

---

### 5.9 API 端点

| 端点 | 说明 |
|---|---|
| `POST /api/v1/reviews/preview` | 阶段一：接收文件前 N 行，返回列映射建议 + 前 10 行预览数据 |
| `POST /api/v1/reviews/upload` | 阶段二：确认后执行全量导入（校验→事务写入→发布 MQ） |
| `GET /api/v1/reviews?status=failed` | 查询导入失败的记录及失败原因 |

---

### 5.10 导入后触发 Agent

导入成功写入 MySQL 后，Service 层逐条将评价发布至 RabbitMQ，触发 LangGraph Agent 异步推理：

```python
# Service 层伪代码：导入后触发 Agent
def publish_to_agent(reviews: List[dict]):
    for review in reviews:
        priority = "high" if any(
            kw in review["review_text"]
            for kw in config.sensitive_words  # 从 Redis 读取黑名单
        ) else "normal"

        mq.publish(
            exchange="canteen.review.topic",
            routing_key=f"review.priority.{priority}",
            message={
                "review_id": review["id"],
                "canteen_id": review["tenant_id"],
                "priority": priority,
                "payload": {
                    "meal_time": review["meal_time"],
                    "stall_name": review["stall_name"],
                    "dish_name": review["dish_name"],
                    "review_text": review["review_text"],
                    "rating": review["rating"],
                    "user_id": review["user_id"],
                },
                "timestamp": datetime.now().isoformat(),
                "retry_count": 0,
            }
        )
```

> 已命中敏感词黑名单的评价在发布时自动标记 `priority=high`，进入 RabbitMQ 高优队列被 Agent 优先消费。

## 6. 知识库层

> **核心定位**：知识库层是 Agent 做出「专业改进建议」而非「瞎编」的基石。它存储四大维度的向量化餐饮专业知识——SOP 标准、历史客诉、成本约束、食安规范——通过 Milvus 向量数据库承载，由 langchain_milvus 提供连接池管理，为 RAG Retrieval 节点提供毫秒级相似检索。

---

### 6.1 四大知识维度

| 维度 | Collection | 数据来源 | 检索触发条件 | 典型内容示例 |
|---|---|---|---|---|
| **SOP 标准卡** | `sop_collection` | 管理员手动录入/上传 | 负面评价包含可映射的工艺槽点 | "红烧肉：高压锅上汽后压制 20 分钟，标准放盐量 5g/份" |
| **历史客诉库** | `history_complaints` | Agent 推理结果 + 人工反馈自动写入 | 负面评价触发 RAG 检索时 | "3月15日红烧肉'太硬'客诉，根因炖煮不足，已整改为延长 5 分钟" |
| **成本约束卡** | `cost_card` | 管理员手动录入 | 整改单生成前（确保建议不超预算） | "红烧肉单份食材成本上限 4.5 元，不可建议增加高单价配料" |
| **食安规范库** | `food_safety` | 管理员录入 + 法规文件上传 | 食安敏感词命中时 | "猪肉中心温度需达 75°C 以上；四季豆须彻底煮熟破坏皂苷" |

---

### 6.2 向量化流水线

```
原始文档（SOP手册 / 菜谱 / 成本表 / 食安规定）
    ↓ 文档拆分
文本分块（Chunk Size=512 tokens, Overlap=64 tokens）
    ↓ Embedding
nomic-embed-text（Ollama 本地推理，768 维向量）
    ↓ 向量入库
Milvus Collection（含 Metadata 标签）
```

**分块策略**：每道菜品的 SOP 为一个独立 chunk，确保检索结果粒度精确到"单品 + 单项工艺"，避免跨菜品的混合检索噪音。

**向量化代码示例**：

```python
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_ollama import OllamaEmbeddings
from langchain_milvus import MilvusVectorStore

# 文档分块
splitter = RecursiveCharacterTextSplitter(
    chunk_size=512,
    chunk_overlap=64,
    separators=["\n## ", "\n### ", "\n", "。", "；"]
)

# 向量嵌入
embedding = OllamaEmbeddings(
    model="nomic-embed-text",
    base_url="http://ollama:11434"
)

# Milvus 入库
vector_store = MilvusVectorStore(
    embedding_function=embedding,
    collection_name="sop_collection",
    connection_args={"host": "milvus", "port": "19530"},
    index_params={
        "metric_type": "COSINE",
        "index_type": "IVF_FLAT",
        "params": {"nlist": 128}
    }
)

# 批量写入（带 Metadata）
docs = splitter.split_documents(raw_document)
for doc in docs:
    doc.metadata = {
        "dish_id": "D045",
        "dish_name": "红烧肉",
        "canteen_id": "CANTEEN_01",
        "stall_id": "S02",
        "doc_type": "sop",        # sop / history / cost / safety
        "process_step": "炖煮",   # 工艺环节
        "updated_at": "2024-06-01"
    }
vector_store.add_documents(docs)
```

---

### 6.3 Collection 设计

每个 Collection 采用统一的 Metadata 标签体系，支撑多维度过滤检索：

```python
# 通用 Metadata Schema（所有 Collection 共用）
METADATA_SCHEMA = {
    "dish_id":       str,       # 菜品唯一标识（如 "D045"）
    "dish_name":     str,       # 菜品名称（冗余，便于调试）
    "canteen_id":    str,       # 食堂标识（多租户隔离）
    "stall_id":      str,       # 档口标识
    "doc_type":      str,       # 文档类型：sop / history / cost / safety
    "process_step":  str,       # 关联的工艺环节（如 "炖煮"、"调味"、"火候"）
    "severity_tag":  str,       # 严重程度标签（仅 history_complaints）
    "cost_per_serving": float,  # 单份成本（仅 cost_card）
    "source":        str,       # 来源（文件名 / 管理员录入 / Agent 自动生成）
    "updated_at":    datetime,  # 最后更新时间
}
```

**各 Collection 特有 Metadata 字段**：

| Collection | 特有字段 | 说明 |
|---|---|---|
| `sop_collection` | `process_step`, `standard_quantity`, `standard_time` | 标准工艺参数 |
| `history_complaints` | `review_id`, `severity_tag`, `corrective_action`, `action_result` | 完整客诉-整改闭环链路 |
| `cost_card` | `cost_per_serving`, `ingredient_list`, `cost_breakdown` | 成本约束数据 |
| `food_safety` | `regulation_source`, `risk_category`, `critical_limit` | 法规来源与关键限值 |

**索引参数**：

```json
{
  "collection_name": "sop_collection",
  "index_type": "IVF_FLAT",
  "metric_type": "COSINE",
  "params": {"nlist": 128}
}
```

> 选择 IVF_FLAT + COSINE 组合：食堂场景数据量中等（数百至数千条 chunks），IVF_FLAT 在召回率与查询速度之间取得最佳平衡；COSINE 适合语义相似度比较（而非欧氏距离）。

---

### 6.4 多租户隔离方案

详见 2.12 节架构设计。每个食堂在 Milvus 中拥有独立的 **Partition**：

```
sop_collection
    ├── Partition: canteen_01  ← 一食堂
    └── Partition: canteen_02  ← 二食堂
```

**检索时的双层过滤**：

```python
retrieved_docs = vector_store.similarity_search(
    query=f"{dish_name} {complaint_keywords}",
    k=3,                                           # 由配置项 rag_top_k 控制
    partition_name=f"canteen_{tenant_id}",          # 第一层：Partition 硬隔离
    expr=f'stall_id == "{stall_id}" and score >= {threshold}'  # 第二层：Metadata 精细过滤
)
```

---

### 6.5 知识入库流程

#### 6.5.1 SOP 与成本卡录入

管理员在 Agent 配置页面（第 4 章）的知识库管理 Tab 中**手工录入或上传文档**：

```
管理员操作
    → 选择菜品 + 知识维度（SOP/成本/食安）
    → 填写结构化表单 或 上传 Markdown/PDF 文档
    → Service 层接收 → 文本分块 → 向量化 → 写入对应 Milvus Collection + Partition
    → 返回入库状态：{chunk_count: 12, collection: "sop_collection", status: "ok"}
```

**录入效率估算**：

| 录入方式 | 单道菜耗时 | 120 道菜总耗时 |
|---|---|---|
| 结构化表单填写（已知工艺参数） | 3-5 分钟 | 约 1 个工作日 |
| 上传 Markdown 文档（已有电子版 SOP） | 1 分钟 | 约 2 小时 |
| 从零整理（老厨师口述 → 笔录 → 录入） | 20-30 分钟 | 约 5-7 个工作日 |

> **应对策略**：Phase 1 试点期只录入 30 道核心菜品（约 1 天工作量）。Phase 2 由技术团队协助批量录入剩余菜品。若食堂无任何电子化 SOP 文档，建议从红牌预警频次最高的菜品开始优先录入（而非 120 道全量）。

**支持的上传格式**：

| 格式 | 说明 |
|---|---|
| Markdown（`.md`） | 推荐格式，直接按标题层级分块 |
| PDF（`.pdf`） | 使用 PyMuPDF 提取文本后分块 |
| 结构化表单 | 前端填写固定字段（工艺步骤、标准参数、验证标准），后端模板化为文本后向量化 |

#### 6.5.2 历史客诉自动入库（持续学习闭环）

详见 3.7 节人机协同闭环。店长处理完人工复核后，结果自动向量化写入 `history_complaints`：

```
店长在决策沙盘页点击 [采纳] / [修改后下发] / [驳回]
    → Service 层将处理结果构造为结构化文本
    → 向量化后写入 history_complaints / Partition: canteen_XX
    → 下次同类评价触发 RAG 时，历史命中因子提升置信度
```

---

### 6.6 检索策略与优化

| 参数 | 默认值 | 由配置项控制 | 说明 |
|---|---|---|---|
| Top-K | 3 | `rag_top_k`（4.5 节） | 每次检索返回最相关的 3 条知识记录 |
| 相似度阈值 | 0.6 | `rag_similarity_threshold`（4.5 节） | COSINE 相似度 < 0.6 的结果丢弃，避免不相关知识干扰 |
| 连接池大小 | 10 | `rag_connection_pool_size`（4.5 节） | langchain_milvus 内部连接池，应对饭点 300-500 条/日的高并发 |
| 检索超时 | 3s | 硬编码 | 超过 3s 未返回则降级：使用本地缓存的菜品基础参数兜底 |

**检索优先级**（多 Collection 检索时的合并策略）：

```
1. sop_collection   —— 权重最高，SOP 标准是整改建议的锚点
2. history_complaints —— 辅助判断，提供历史相似案例参考
3. cost_card        —— 约束层，确保整改建议在预算内
4. food_safety      —— 安全底线层，仅在食安敏感词命中时检索
```

合并策略：各 Collection 独立检索后，按优先级拼接为 `knowledge_context` 字符串注入 AgentState。

---

### 6.7 langchain_milvus 连接管理

直接采用 `langchain_milvus` 模块而非底层 PyMilvus 客户端，原因：

| 对比维度 | langchain_milvus | 原生 PyMilvus |
|---|---|---|
| **连接池管理** | 内置连接池，自动管理连接生命周期 | 需手动管理 `connections.connect()` / `disconnect()` |
| **高并发安全性** | 连接池耗尽时排队等待，而非直接报错断联 | 并发请求超出连接数时直接抛异常 |
| **与 LangChain 生态集成** | 与 `OllamaEmbeddings`、`TextSplitter` 无缝衔接 | 需自行编写向量化到检索的胶水代码 |
| **Metadata 过滤** | 原生支持 `filter` / `expr` 参数 | 需手写 Milvus DSL 表达式 |

**连接池配置**（在 Agent 微服务启动时初始化）：

```python
from langchain_milvus import MilvusVectorStore

vector_store = MilvusVectorStore(
    embedding_function=OllamaEmbeddings(model="nomic-embed-text"),
    collection_name="sop_collection",
    connection_args={
        "host": config.MILVUS_HOST,
        "port": config.MILVUS_PORT,
        "pool_size": config.RAG_CONNECTION_POOL_SIZE,  # 默认 10
    }
)
```

> 通过配置页面的 `rag_connection_pool_size` 参数，管理员可在饭点高峰前临时调大连接池，饭后调回默认值，无需重启 Agent 微服务。

---

### 6.8 知识库维护

| 维护操作 | 频率 | 说明 |
|---|---|---|
| **新增菜品 SOP** | 按需（新菜上线时） | 管理员录入工艺参数，向量化入库 |
| **更新 SOP** | 按需（工艺变更时） | 覆盖旧向量（以 `dish_id + process_step` 去重） |
| **历史客诉自动增长** | 持续（Agent 每次推理闭环后） | 无需人工干预，持续学习闭环自动追加 |
| **过期 SOP 清理** | 季度 | 已下架超过 90 天的菜品 SOP 标记为 `status=archived`，检索时自动过滤 |
| **向量索引重建** | 月度 | 当 Collection 数据量增长超过 30% 时，重建 IVF_FLAT 索引以保持检索性能 |

## 7. 核心业务页面设计

> **核心定位**：系统前端（Vue3 + Element Plus）提供四个核心页面，分别面向管理层（日报看板）、后厨执行层（单项诊断）、系统管理员（配置与知识库）、以及深度排查场景（智能问答沙盘）。四个页面通过 REST API 与 WebSocket 从 FastAPI 后端获取数据，完全解耦。

---

### 7.1 页面导航结构

```
┌─────────────────────────────────────────────────┐
│  食堂品控智能 Agent                    [admin ▾] │
├─────────────────────────────────────────────────┤
│  📊 每日日报  │  🔍 单品诊断  │  ⚙️ 系统配置  │  💬 智能问答  │
└─────────────────────────────────────────────────┘
```

| 导航项 | 页面 | 目标用户 | 核心功能 |
|---|---|---|---|
| 📊 每日日报 | 每日菜品质量日报 | 食堂经理 / 后勤主管 | 全局情绪看板、红黑榜、槽点雷达、AI 摘要 |
| 🔍 单品诊断 | 菜品单项诊断与改进单 | 后厨主管 / 当班主厨 | 客诉原声、SOP 比对、AI 诊断、整改单下发 |
| ⚙️ 系统配置 | Agent 配置与知识库管理 | 系统管理员 | 预警阈值、Prompt 管理、知识库录入（详见第 4 章） |
| 💬 智能问答 | 智能问答与决策沙盘 | 食堂经理 / 后勤主管 | 多轮对话、预设快捷问询、动态数据卡片 |

---

### 7.2 页面一：每日菜品质量日报（管理看板）

**目标用户**：食堂经理、后勤主管。**使用频率**：每日晨会前查看。

**页面布局**：

```
┌──────────────────────────────────────────────────────────────┐
│  📊 每日菜品质量日报                          2024-06-01 ▾   │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─── 全局情绪指数 ─────────────┬── 红黑榜 ──────────────┐  │
│  │                              │                        │  │
│  │  🟢 好评率  72%  (358条)     │ 🏆 零差评 TOP3        │  │
│  │  🟡 中性率  18%  (89条)      │  1. 清炒时蔬  ⭐4.8   │  │
│  │  🔴 差评率  10%  (50条)      │  2. 番茄炒蛋  ⭐4.7   │  │
│  │                              │  3. 糖醋里脊  ⭐4.6   │  │
│  │  [环形图: 绿72% 黄18% 红10%] │                        │  │
│  │                              │ ⚠️ 红牌预警 TOP3       │  │
│  │                              │  1. 红烧肉   差评12条  │  │
│  │                              │  2. 麻婆豆腐 差评8条   │  │
│  │                              │  3. 宫保鸡丁 差评5条   │  │
│  └──────────────────────────────┴────────────────────────┘  │
│                                                              │
│  ┌─── 槽点雷达图 ───────────────────────────────────────┐   │
│  │                                                       │   │
│  │         [雷达图: 太咸40% / 量少30% / 不熟20% /       │   │
│  │                   态度差10% / 太油15% / 异物3%]       │   │
│  │                                                       │   │
│  └───────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌─── 核心改进摘要（AI 生成）──────────────────────────┐    │
│  │                                                       │   │
│  │  📝 今日主要问题集中在二楼面食档口，反映汤底过咸的    │   │
│  │     评价高达 15 条，需重点关注。红烧肉差评集中在"口   │   │
│  │     感过柴"，初步判断为今日代班厨师炖煮时间不足。     │   │
│  │     详见 → 红烧肉诊断报告                               │   │
│  │                                                       │   │
│  └───────────────────────────────────────────────────────┘   │
│                                                              │
│  [查看昨日] [查看上周] [导出 PDF]                              │
└──────────────────────────────────────────────────────────────┘
```

**数据来源**：

| 模块 | API | 刷新方式 |
|---|---|---|
| 全局情绪指数 | `GET /api/v1/dashboard/summary` | WebSocket 实时推送（有新评价时增量更新） |
| 红黑榜 | `GET /api/v1/dashboard/summary` | 同上 |
| 槽点雷达图 | `GET /api/v1/dashboard/radar?date=2024-06-01` | 页面加载时请求 |
| AI 摘要 | `GET /api/v1/dashboard/summary` | 每日 20:00 Celery 定时生成后更新 |

**交互行为**：

- 点击红牌预警中的菜品名 → 跳转至「单品诊断页」并自动加载该菜品诊断报告
- 点击「查看昨日/上周」→ 日期选择器切换历史日报
- 导出 PDF：后端使用 WeasyPrint 将当日日报渲染为 PDF 下载

---

### 7.3 页面二：菜品单项诊断与改进单（后厨执行端）

**目标用户**：后厨主管、当班主厨。**使用频率**：当某菜品触发红牌预警或差评集中爆发时。

**页面布局**：

```
┌──────────────────────────────────────────────────────────────┐
│  🔍 菜品单项诊断                              红烧肉 (D045)  │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌── 基础信息 ──────────────────────────────────────────┐   │
│  │  菜品名称：红烧肉         所属档口：二楼川湘档口        │   │
│  │  当班主厨：张师傅（代班） 单份成本：¥4.20              │   │
│  │  当日销量：86 份          日常销量均值：75 份           │   │
│  │  当日差评率：12.8% ← 异常（日常均值 3.0%）             │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌── 客诉原声 ──────────────────────────────────────────┐   │
│  │  🗣️ "今天中午的红烧肉咬都咬不动，跟昨天完全不一样"      │   │
│  │  🗣️ "**肉太硬**了，塞牙，是不是换师傅了？"              │   │
│  │  🗣️ "**火候不够**，废了半天劲嚼不烂"                   │   │
│  │  🗣️ "**分量也比昨天少**，一共就三块肉"                  │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌── 知识库比对 ────────────────────────────────────────┐   │
│  │  📋 标准 SOP：高压锅上汽后压制 20 分钟，盐量 5g/份      │   │
│  │  📋 历史参考：2024-03-15 同类客诉"肉太硬"，             │   │
│  │     根因炖煮时间不足，已整改为延长 5 分钟               │   │
│  │  📋 成本约束：单份食材成本 ≤ ¥4.50                     │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌── AI 智能诊断 ───────────────────────────────────────┐   │
│  │  🧠 冲突类型：品控波动 (QUALITY_FLUCTUATION)            │   │
│  │  🧠 置信度：90%                                         │   │
│  │  🧠 分析：评价集中反馈肉质过硬，结合今日代班厨师非      │   │
│  │     原主厨且出餐速度偏快，推测炖煮时间未达 SOP 标准。   │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌── 整改单 ────────────────────────────────────────────┐   │
│  │  【品控异常处理单】                                    │   │
│  │  ■ 问题定位：红烧肉口感过硬，差评率 12.8%              │   │
│  │  ■ 根因推测：代班厨师高压锅压制时间未达 SOP 标准        │   │
│  │  ■ 操作指令：                                          │   │
│  │    1. 下一餐次高压锅上汽后务必压制满 20 分钟            │   │
│  │    2. 出锅前随机抽检 2 块，用筷子穿透肉块验证软烂       │   │
│  │    3. 当前剩余批次回锅加炖 10 分钟后再出餐              │   │
│  │  ■ 验证标准：筷子可轻松穿透肉块中心，不塞牙              │   │
│  │                                                        │   │
│  │  [下发至后厨]  [修改后下发]  [驳回/忽略]                │   │
│  └──────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

**数据来源**：

| 模块 | API | 说明 |
|---|---|---|
| 基础信息 | `GET /api/v1/dishes/{id}/diagnosis` | 含当日销量、差评率、当班主厨 |
| 客诉原声 | `GET /api/v1/dishes/{id}/reviews?sentiment=negative` | 过滤后的差评列表，敏感词自动高亮 |
| 知识库比对 | `GET /api/v1/dishes/{id}/diagnosis` | 包含 SOP 参数、历史相似客诉、成本约束 |
| AI 诊断 | `GET /api/v1/dishes/{id}/diagnosis` | Agent 推理结果（冲突类型、置信度、分析） |
| 整改单 | `GET /api/v1/dishes/{id}/diagnosis` | Agent 生成的结构化整改单 |

**交互行为**：

- 客诉原声中的敏感词（如"肉太硬""火候不够"）自动以 **红色粗体** 高亮
- **[下发至后厨]**：将整改单状态更新为 `dispatched`，并在系统内通知当班主厨
- **[修改后下发]**：弹出整改单编辑器，店长修改后下发
- **[驳回/忽略]**：标记为 `rejected`，反馈回写 Milvus 历史客诉库（持续学习）

---

### 7.4 页面三：Agent 配置与知识库管理（后台配置端）

**目标用户**：系统管理员。详细设计见 **第 4 章 Agent 配置与参数化管理**。

本章补充知识库管理 Tab 的页面布局：

```
┌──────────────────────────────────────────────────────────────┐
│  ⚙️ 系统配置                    [全局默认 ▾] [一食堂 ▾]       │
├──────────────────────────────────────────────────────────────┤
│  ┌─ 预警规则 ─┬─ RAG检索 ─┬─ 数据源 ─┬─ AI推理 ─┬─ 知识库 ─┐ │
│  │            │           │          │          │          │ │
│  │            │           │          │          │ 菜品：    │ │
│  │            │           │          │          │ [红烧肉 ▾]│ │
│  │  (详见     │  (详见    │  (详见   │  (详见   │          │ │
│  │   第4章)   │   第4章)  │   第4章) │   第4章) │ 维度：    │ │
│  │            │           │          │          │ ○ SOP标准 │ │
│  │            │           │          │          │ ○ 成本卡  │ │
│  │            │           │          │          │ ○ 食安规范│ │
│  │            │           │          │          │          │ │
│  │            │           │          │          │ ┌───────┐│ │
│  │            │           │          │          │ │工艺步骤││ │
│  │            │           │          │          │ │: 炖煮  ││ │
│  │            │           │          │          │ │标准时长││ │
│  │            │           │          │          │ │: 20min ││ │
│  │            │           │          │          │ │放盐量  ││ │
│  │            │           │          │          │ │: 5g/份 ││ │
│  │            │           │          │          │ └───────┘│ │
│  │            │           │          │          │          │ │
│  │            │           │          │          │ 或上传： │ │
│  │            │           │          │          │ [选择.md]│ │
│  │            │           │          │          │ [选择.pdf]│ │
│  │            │           │          │          │          │ │
│  │            │           │          │          │[保存]    │ │
│  └────────────┴───────────┴──────────┴──────────┴──────────┘ │
└──────────────────────────────────────────────────────────────┘
```

**知识库 Tab 功能**：

| 功能 | 说明 |
|---|---|
| 菜品选择器 | 下拉搜索菜品名，选择后展示该菜品的已有知识条目列表 |
| 维度切换 | SOP 标准 / 成本卡 / 食安规范 三个 Radio 切换 |
| 结构化表单 | 按 Collection 的 Metadata Schema 提供对应字段输入框 |
| 文件上传 | 支持 Markdown (.md) 和 PDF (.pdf)，自动分块 + 向量化入库 |
| 已有条目列表 | 展示该菜品已入库的知识条目，支持编辑/删除 |

---

### 7.5 页面四：智能问答与决策沙盘（交互式排查）

**目标用户**：食堂经理、后勤主管。**使用频率**：需要深度排查特定问题时。

**页面布局**：

```
┌──────────────────────────────────────────────────────────────┐
│  💬 智能问答                                                 │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─ 对话区 ─────────────────────────────────────────────┐   │
│  │                                                       │   │
│  │  👤 为什么今天红烧肉评价这么差？                       │   │
│  │                                                       │   │
│  │  🤖 根据今日数据分析，红烧肉共收到 86 条评价，         │   │
│  │     其中差评 11 条（差评率 12.8%，远高于日常 3%）。   │   │
│  │     主要槽点集中在"口感太硬"（8条）和"分量偏少"      │   │
│  │     （3条）。                                          │   │
│  │                                                       │   │
│  │     ┌─────────────────────────────────────┐           │   │
│  │     │ 📊 红烧肉今日评价趋势                │           │   │
│  │     │ [折线图: 11:00-13:00 差评集中爆发]   │           │   │
│  │     │ 当班主厨：张师傅（代班）← 关键变化    │           │   │
│  │     │ [查看完整诊断报告 →]                  │           │   │
│  │     └─────────────────────────────────────┘           │   │
│  │                                                       │   │
│  │  👤 上周哪个档口客诉最多？                              │   │
│  │                                                       │   │
│  │  🤖 上周（5/25-5/31）客诉最多的档口是二楼川湘档口，  │   │
│  │     共收到差评 34 条，主要集中在红烧肉（12条）和      │   │
│  │     麻婆豆腐（8条）。                                  │   │
│  │                                                       │   │
│  │     ┌─────────────────────────────────────┐           │   │
│  │     │ 🏆 上周各档口差评排名                │           │   │
│  │     │ [柱状图: 川湘34 / 面食22 / 快餐18]   │           │   │
│  │     └─────────────────────────────────────┘           │   │
│  └───────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌─ 快捷问询 ──────────────────────────────────────────┐    │
│  │  [查询昨日客诉最多档口]  [生成上周综合改进报告]        │    │
│  │  [今日食安异常汇总]      [近7天差评趋势分析]           │    │
│  └───────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌─ 输入区 ──────────────────────────────────────────┐      │
│  │  [请输入您的问题...]                          [发送] │      │
│  └───────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

**技术实现**：

| 特性 | 实现方式 |
|---|---|
| **多轮对话** | SSE（Server-Sent Events）流式响应，`GET /api/v1/chat?query=...`，会话上下文保存在 Redis DB 1 中（TTL 30min） |
| **上下文记忆** | 每次请求携带 `session_id`，后端从 Redis 读取最近 10 轮对话历史注入 LLM |
| **预设快捷问询** | 前端 Tag 点击 → 填入预设查询文本 → 自动发送 |
| **动态数据卡片** | LLM 应答中返回结构化 JSON（含 `card_type` + `card_data`），前端根据 `card_type` 渲染对应组件（折线图/柱状图/表格/链接） |

**LLM 的 Function Calling 流程**：

```python
# 智能问答节点的 Function Calling 定义
FUNCTIONS = [
    {
        "name": "query_dish_stats",
        "description": "查询指定菜品在某个时间范围内的评价统计",
        "parameters": {
            "dish_name": str,
            "date_range": ("today", "yesterday", "last_week", "last_month"),
        }
    },
    {
        "name": "query_stall_ranking",
        "description": "查询客诉档口排名",
        "parameters": {
            "date_range": str,
            "metric": ("complaints", "praise"),
            "top_k": int,
        }
    },
    {
        "name": "get_diagnosis_report",
        "description": "获取指定菜品的完整诊断报告",
        "parameters": {"dish_id": str},
    },
]
```

> 当用户问"为什么今天红烧肉评价这么差"时，LLM 识别意图 → 调用 `query_dish_stats(dish_name="红烧肉", date_range="today")` → 获取统计数据 → 生成自然语言回答 + 嵌入趋势折线图卡片。

---

### 7.6 页面间导航关系

```
每日日报 ──点击红牌菜品──→ 单品诊断页
                                │
                    [下发整改单] / [修改] / [驳回]
                                │
                                ↓
                          写回 MySQL + Milvus
                                │
                    ┌───────────┴───────────┐
                    ↓                       ↓
              日报数据更新          历史客诉库增长
              (WebSocket 推送)      (持续学习闭环)

智能问答 ──查看完整报告──→ 单品诊断页

系统配置 ──修改阈值──→ Redis 热配置刷新 ──→ Agent 下次推理生效
```

---

### 7.7 前端技术选型

| 技术 | 用途 |
|---|---|
| **Vue 3** (Composition API) | 整体前端框架 |
| **Element Plus** | UI 组件库（表格、表单、日期选择器、对话框） |
| **ECharts 5** | 数据可视化（环形图、雷达图、折线图、柱状图） |
| **Pinia** | 状态管理（全局情绪指数、WebSocket 连接状态） |
| **xlsx / papaparse** | 前端 CSV/Excel 解析与预览 |
| **marked + highlight.js** | Markdown 渲染 + 代码高亮（智能问答中的格式化回复） |
| **WebSocket 原生 API** | 日报实时数据推送 |

**前端路由**：

```javascript
// router/index.js
const routes = [
    { path: '/',             redirect: '/dashboard' },
    { path: '/dashboard',    component: DailyDashboard },
    { path: '/diagnosis/:id', component: DishDiagnosis },
    { path: '/config',       component: AgentConfig },
    { path: '/chat',         component: SmartChat },
];
```

## 8. 技术选型与部署方案

> **核心定位**：本章汇总系统全栈技术选型、版本锁定、硬件要求、以及从零到一的完整部署流程。容器化部署清单详见 2.15 节，此处聚焦选型理由与部署步骤。

---

### 8.1 全栈技术选型

| 层级 | 技术 | 版本 | 选型理由 |
|---|---|---|---|
| **后端框架** | FastAPI | ≥0.111 | 原生异步（async/await）、自动 OpenAPI 文档、Pydantic 校验、高性能 |
| **Agent 编排** | LangGraph | ≥0.2 | 状态图驱动的多节点工作流、条件路由、与 LangChain 生态无缝集成 |
| **LLM 推理** | Ollama + Qwen2.5 | 7B/14B | 本地部署（数据不出网）、中文能力强、支持 Function Calling |
| **Embedding** | nomic-embed-text (Ollama) | latest | 768 维、中英文双语、本地推理、通过 OllamaEmbeddings 集成 |
| **向量数据库** | Milvus | ≥2.4.0 | 分布式向量检索、Partition 多租户隔离、IVF_FLAT 索引 |
| **Milvus 客户端** | langchain_milvus | ≥0.1 | 连接池管理、Metadata 过滤、与 OllamaEmbeddings 一致接口 |
| **消息队列** | RabbitMQ | 3.12 | 消息确认、死信队列、Topic Exchange 路由、管理界面 |
| **关系型数据库** | MySQL | 8.0 | ACID 事务、成熟运维、SQLAlchemy ORM |
| **缓存** | Redis | 7 | 微秒级读写、多 DB 分库、Celery 后端 |
| **异步任务** | Celery + Celery Beat | ≥5.3 | 定时调度、分布式 Worker、Flower 监控 |
| **前端框架** | Vue 3 + Element Plus | ≥3.4 | Composition API、成熟 UI 组件库 |
| **可视化** | ECharts | 5 | 丰富的图表类型（环形/雷达/折线/柱状）、大数据量渲染 |
| **容器化** | Docker + Docker Compose | ≥24 | 一键部署、环境隔离、GPU 透传 |
| **PDF 生成** | WeasyPrint | ≥60 | 日报 PDF 导出、HTML → PDF 渲染 |

---

### 8.2 Python 依赖清单

```
# backend/requirements.txt
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
sqlalchemy>=2.0
pymysql>=1.1
alembic>=1.13
pydantic>=2.7
celery[redis]>=5.3
pika>=1.3                    # RabbitMQ 客户端
redis>=5.0
python-multipart>=0.0.9      # 文件上传
openpyxl>=3.1                # Excel 解析
xlrd>=2.0                    # .xls 解析
chardet>=5.2                 # 编码检测
weasyprint>=60               # PDF 导出
```

```
# agent/requirements.txt
langgraph>=0.2.0
langchain>=0.2.0
langchain-ollama>=0.1
langchain-milvus>=0.1
pymilvus>=2.4.0
pika>=1.3
redis>=5.0
httpx>=0.27
```

---

### 8.3 硬件要求

| 组件 | 最低配置 | 推荐配置 | 说明 |
|---|---|---|---|
| **CPU** | 8 核 | 16 核 | Celery Worker + FastAPI + RabbitMQ 共享 |
| **内存** | 32 GB | 64 GB | Ollama 7B 模型约占 8-10 GB，Milvus 约 4 GB，MySQL/Redis 各 2 GB |
| **GPU** | 1 × NVIDIA 16GB+（T4/V100/A10） | 1 × NVIDIA 24GB+（A10/A100） | Qwen2.5 7B 约 14 GB 显存，14B 约 28 GB |
| **磁盘** | 250 GB SSD | 500 GB SSD | 模型文件 + Milvus 索引 + MySQL 数据 + Docker 镜像 |
| **网络** | 内网千兆 | — | 部署在食堂内网，无需公网暴露 |

> **无 GPU 部署**：若不具备 GPU，Qwen2.5 7B 可在 CPU 上运行（内存需 ≥ 32 GB），但每次推理耗时会从 3-10 秒延长至 30-120 秒。适用于评价量 < 100 条/日的小型食堂。

---

### 8.4 环境变量

```bash
# .env
# ===== MySQL =====
MYSQL_ROOT_PASSWORD=changeme_2024
MYSQL_DATABASE=canteen_agent

# ===== RabbitMQ =====
RABBITMQ_DEFAULT_USER=admin
RABBITMQ_DEFAULT_PASS=changeme_2024
RABBITMQ_URL=amqp://admin:changeme_2024@rabbitmq:5672/

# ===== Redis =====
REDIS_URL=redis://redis:6379

# ===== Milvus =====
MILVUS_HOST=milvus
MILVUS_PORT=19530

# ===== Ollama =====
OLLAMA_HOST=http://ollama:11434
OLLAMA_MODEL=qwen2.5:7b-instruct
OLLAMA_EMBED_MODEL=nomic-embed-text

# ===== Agent =====
AGENT_INTERNAL_URL=http://agent:8001
AGENT_CONFIDENCE_THRESHOLD=0.75
AGENT_RAG_TOP_K=3
AGENT_RAG_SIMILARITY_THRESHOLD=0.6
```

---

### 8.5 一键部署流程

#### Step 1：环境准备

```bash
# 安装 Docker 及 NVIDIA Container Toolkit（GPU 环境）
# Ubuntu:
sudo apt update
sudo apt install -y docker.io docker-compose-v2
sudo nvidia-ctk runtime configure
sudo systemctl restart docker

# 克隆项目
git clone <repo-url> canteen-agent && cd canteen-agent
```

#### Step 2：配置环境变量

```bash
cp .env.example .env
# 编辑 .env，修改数据库密码等敏感配置
nano .env
```

#### Step 3：启动全部服务

```bash
docker compose up -d
# 等待所有容器进入 healthy 状态（约 30-60 秒）
docker compose ps
```

#### Step 4：拉取 LLM 模型

```bash
# 下载推理模型
docker exec -it canteen-agent-ollama-1 ollama pull qwen2.5:7b-instruct

# 下载 Embedding 模型
docker exec -it canteen-agent-ollama-1 ollama pull nomic-embed-text

# 验证模型可用
curl http://localhost:11434/api/tags
```

#### Step 5：初始化数据库

```bash
# 执行 Alembic 迁移创建表结构
docker exec -it canteen-agent-backend-1 alembic upgrade head

# 插入全局默认配置
docker exec -it canteen-agent-backend-1 python -m scripts.seed_config
```

#### Step 6：验证部署

```bash
# 后端健康检查
curl http://localhost:8000/api/v1/health

# Agent 健康检查（含 Milvus / Ollama 连通性）
curl http://localhost:8001/agent/health

# 前端页面
curl http://localhost:3000
```

**预期输出**：

```json
// GET /api/v1/health
{
  "status": "ok",
  "services": {
    "mysql": "connected",
    "redis": "connected",
    "rabbitmq": "connected"
  }
}

// GET /agent/health
{
  "status": "ok",
  "milvus": {"connected": true, "collections": 4},
  "ollama": {"connected": true, "model": "qwen2.5:7b-instruct"}
}
```

---

### 8.6 启动后检查清单

| 检查项 | 命令/方法 | 预期结果 |
|---|---|---|
| 所有容器健康 | `docker compose ps` | 全部 `Up (healthy)` |
| 模型已加载 | `curl http://localhost:11434/api/tags` | 包含 `qwen2.5:7b-instruct` 和 `nomic-embed-text` |
| Milvus Collection 已创建 | `GET /agent/health` | `collections: 4` |
| MySQL 表结构正常 | `docker exec -it canteen-agent-backend-1 alembic current` | 显示最新 migration 版本号 |
| 全局配置已写入 | Redis CLI → `KEYS config:*` | 返回 3 个 key（sensitive_words / warning_thresholds / rag_params） |
| Celery Worker 在线 | Flower 面板 → `http://localhost:5555` | 显示 1+ Worker 在线 |
| RabbitMQ 管理界面 | `http://localhost:15672`（admin/changeme_2024） | 显示 3 个 Queue 已创建 |

---

### 8.7 常见问题

| 问题 | 原因 | 解决 |
|---|---|---|
| Ollama 启动后无 GPU | Docker 未配置 NVIDIA runtime | `nvidia-ctk runtime configure && systemctl restart docker` |
| Agent 健康检查 Milvus 无连接 | Milvus 依赖 etcd/minio 未完全启动 | 等待 30s 后重试，milvus 容器启动较慢 |
| Celery Worker 无法连接 RabbitMQ | RabbitMQ 尚未就绪 | Worker 会自动重连，或手动 `docker compose restart celery_worker` |
| CSV 上传 500 错误 | 文件编码非 UTF-8/GBK | chardet 自动检测，若失败则提示管理员手动转换编码 |
| LLM 推理超时 | GPU 显存不足或并发过高 | 降低 RabbitMQ Prefetch Count，或扩容 Agent Worker 实例数 |

## 9. 实施计划与风险

> **核心定位**：系统采用三阶段交付策略——先跑通核心链路（MVP），再完善多租户与知识库（生产化），最后引入持续学习与智能问答（增强）。每阶段有明确的交付物、验收标准和风险应对。

---

### 9.1 三阶段交付路线图

```
Phase 1: MVP（6 周）          Phase 2: 生产化（4 周）       Phase 3: 增强（4 周）
┌─────────────────┐         ┌─────────────────┐         ┌─────────────────┐
│ 评价上传与清洗   │         │ 多租户隔离       │         │ 持续学习闭环     │
│ Agent 核心工作流 │  ───→   │ 知识库完整录入   │  ───→   │ 智能问答沙盘     │
│ 单品诊断与整改单 │         │ 配置页面完善     │         │ 性能优化与压测   │
│ 日报看板        │         │ 异常降级加固     │         │ 生产运维交接     │
└─────────────────┘         └─────────────────┘         └─────────────────┘
```

---

### 9.2 Phase 1：MVP（第 1-6 周）

**目标**：跑通「评价上传 → Agent 推理 → 整改单生成 → 日报看板」核心闭环，在 1 个食堂试点。

| 周次 | 任务 | 交付物 |
|---|---|---|
| **W1** | 环境搭建：Docker Compose 部署、Ollama 模型下载、MySQL/Milvus/Redis/RabbitMQ 初始化 | 所有服务 `docker compose ps` healthy |
| **W2** | 数据采集层开发：CSV/Excel 上传接口、编码检测、列映射、两阶段导入、reviews 表 | 可上传文件并预览前 10 行 |
| **W3** | Agent 核心工作流开发：LangGraph 6 节点实现（Cleansing→Routing→RAG→Conflict→Confidence→Report） | 单条评价可完整走通工作流 |
| **W4** | 单品诊断页 + 整改单模板开发；RabbitMQ 异步流转接入 | 差评触发 → 自动生成整改单 |
| **W5** | 日报看板开发：全局情绪指数、红黑榜、槽点雷达、AI 摘要 | 每日 20:00 自动生成日报 |
| **W6** | 试点部署：1 个食堂、2 个档口、~30 道菜品、导入历史评价数据试运行 | MVP 验收通过，试点可行 |

**Phase 1 验收标准**：

- [ ] CSV 文件上传成功率 > 99%（合法文件）
- [ ] Agent 工作流端到端成功率 > 90%（评价 → 整改单全自动）
- [ ] 整改单内容可执行（后厨主管反馈"看得懂、能照着做"）
- [ ] 日报数据与原始评价数据一致（数据准确性校验）

---

### 9.3 Phase 2：生产化（第 7-10 周）

**目标**：多租户隔离、知识库批量录入、配置页面上线、异常降级加固，扩展至 2 个食堂。

| 周次 | 任务 | 交付物 |
|---|---|---|
| **W7** | 多租户改造：MySQL tenant_id 迁移、Milvus Partition 创建、三级继承配置模型上线 | 两个食堂数据物理隔离 |
| **W8** | 知识库录入：SOP 标准卡（~120 道菜）、成本卡、食安规范批量向量化入库；配置页面 4 个 Tab 开发完成 | 知识库 Tab 可录入/编辑 |
| **W9** | 异常降级加固：Milvus 不可用兜底、LLM 超时重试、死信队列、整批回滚 | 所有降级策略可手动触发验证 |
| **W10** | 第二食堂部署 + 全量回归测试 + 性能压测（模拟 500 条/日并发） | 压测报告 + 生产上线 |

**Phase 2 验收标准**：

- [ ] 一食堂数据与二食堂数据完全隔离（交叉检索验证无泄漏）
- [ ] 知识库检索命中率 > 80%（差评槽点能在 SOP 中找到对应工艺参数）
- [ ] 配置变更后 5 秒内 Agent 生效（Redis 刷新验证）
- [ ] 模拟 Milvus 宕机 → Agent 降级不崩溃，兜底模板正常生成

---

### 9.4 Phase 3：增强（第 11-14 周）

**目标**：持续学习闭环、智能问答沙盘上线、性能调优、运维交接。

| 周次 | 任务 | 交付物 |
|---|---|---|
| **W11** | 持续学习闭环：人工复核反馈自动向量化写入 Milvus、历史命中因子参与置信度计算 | 反馈回写验证：同类差评第二次出现时置信度提升 |
| **W12** | 智能问答沙盘开发：SSE 流式对话、Function Calling、动态数据卡片渲染 | 4 类预设问询可正常返回图表 |
| **W13** | 性能调优：LLM 批处理优化、Milvus 索引重建、前端 ECharts 大数据量渲染优化 | 日均 500 条评价的处理延迟 < 60s |
| **W14** | 运维交接：操作手册、运维手册、培训视频录制、生产环境正式上线 | 管理员可独立完成日常配置修改与知识库更新 |

**Phase 3 验收标准**：

- [ ] 持续学习闭环：相同菜品同类差评复发时，Agent 诊断准确率提升 15%+
- [ ] 智能问答响应 < 5 秒（SSE 首 token）
- [ ] 食堂管理员可独立完成：上传评价文件 + 查看日报 + 修改配置 + 录入 SOP
- [ ] 系统连续运行 72 小时无宕机

---

### 9.5 风险矩阵

| 风险 ID | 风险描述 | 影响等级 | 概率 | 应对措施 |
|---|---|---|---|---|
| **R1** | LLM 推理延迟过高（>30s），影响用户体验 | 高 | 中 | Phase 1 即压测单条推理耗时；Phase 2 引入批处理模式；配置 RabbitMQ Prefetch Count 限流；无 GPU 场景默认推荐 14B→7B 模型降级 |
| **R2** | Dish Routing 消歧匹配率低（<60%），大量评价流入人工队列 | 高 | 中 | 预设菜品别名表（"土豆烧肉"="土豆炖肉"）；LLM 语义推断兜底；人工标注后自动加入映射表 |
| **R3** | 食堂管理员无法提供结构化 SOP 数据，知识库为空 | 高 | 高 | Phase 1 先用通用烹饪知识库兜底；Phase 2 由技术团队协助录入前 30 道核心菜品 SOP；提供简易表单模板降低录入门槛 |
| **R4** | Milvus 连接池在饭点高并发时耗尽 | 中 | 低 | langchain_milvus 自带连接池管理；配置页面可动态调整连接池大小；Phase 2 压测验证并发上限 |
| **R5** | 食堂管理层不愿改变现有工作流程，系统推广受阻 | 高 | 中 | Phase 1 只试点 1 个食堂，用数据说话（整改前后差评率对比）；日报 PDF 导出适配传统晨会习惯；不做流程强推，先做辅助决策 |
| **R6** | 大模型输出幻觉——整改建议不靠谱（如建议给 10 元盒饭加海参） | 高 | 低 | 四层防线：成本约束卡过滤、SOP 锚定、置信度阈值（<0.75 推人工）、固定模板限制输出格式。Phase 1 试点期人工抽查所有整改单 |
| **R7** | 硬件采购周期长，GPU 服务器未到位 | 中 | 中 | Phase 1 允许无 GPU CPU 模式（仅限试点）；同步走采购流程；AutoDL 云端 GPU 临时过渡 |

---

### 9.6 团队配置建议

| 角色 | 人数 | 职责 | 参与阶段 |
|---|---|---|---|
| **后端工程师**（Python/FastAPI） | 1-2 | Controller-Service-DAO 开发、RabbitMQ/Celery 集成、API 开发 | Phase 1-3 |
| **AI 工程师**（LangChain/LangGraph） | 1 | Agent 工作流开发、Prompt 调优、RAG 检索优化 | Phase 1-3 |
| **前端工程师**（Vue3/Element Plus） | 1 | 四个核心页面开发、ECharts 可视化、文件上传交互 | Phase 1-2 |
| **DevOps/运维** | 0.5（兼职） | Docker 部署、CI/CD、监控告警、生产运维 | Phase 2-3 |
| **食堂业务对接人** | 1（食堂方） | SOP 数据提供、试点反馈、验收确认 | Phase 1-3 |

---

### 9.7 上线 Checklist

| 检查项 | 阶段 | 说明 |
|---|---|---|
| 所有单元测试通过 | Phase 1 末 | 核心节点（Cleansing / Routing / Conflict）覆盖率 > 80% |
| 端到端集成测试通过 | Phase 1 末 | 10 条真实评价手动验证全链路 |
| 安全扫描无高危漏洞 | Phase 2 末 | 依赖项 CVE 扫描 + 端口暴露审计 |
| 数据备份脚本就绪 | Phase 2 末 | MySQL 每日自动备份 + Milvus 定期快照 |
| 操作手册交付 | Phase 3 末 | 含截图的操作手册（上传评价、查看日报、修改配置、录入 SOP） |
| 管理员培训完成 | Phase 3 末 | 食堂管理员可独立完成日常操作 |
| 7×24 稳定性监控就绪 | Phase 3 末 | Flower + RabbitMQ Management + 结构化日志接入 |
