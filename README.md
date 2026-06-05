# 🍽️ 食堂品控智能 Agent 系统

基于 **LangGraph + Milvus + LLM** 的菜品质量智能分析平台，自动聚合顾客评价、生成 AI 改进建议，并通过向量库沉淀品控经验，形成自进化闭环。

---

## 🏗️ 架构总览

```
┌─────────────┐     ┌──────────────┐     ┌───────────────┐
│   Frontend   │────▶│   Backend     │────▶│    Agent       │
│  Vue 3 :3000 │     │ FastAPI :8000 │     │ FastAPI :8001  │
└─────────────┘     └──────┬───────┘     └───────┬───────┘
                           │                      │
                    ┌──────▼───────┐      ┌───────▼───────┐
                    │   RabbitMQ   │      │    Milvus     │
                    │  (Celery)    │      │  (向量库)     │
                    └──────┬───────┘      └───────────────┘
                           │
                    ┌──────▼───────┐
                    │    Redis     │
                    │  (任务队列)  │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │    MySQL     │
                    │  (业务数据)  │
                    └──────────────┘
```

| 组件 | 技术栈 |
|------|--------|
| 前端 | Vue 3 + Element Plus + ECharts |
| 后端 | FastAPI + SQLAlchemy + Celery |
| Agent | LangGraph + LangChain + Milvus |
| LLM | 阿里云 DashScope (qwen-plus) |
| Embedding | 阿里云 DashScope (text-embedding-v4) |
| 消息队列 | RabbitMQ + Redis |
| 数据库 | MySQL 8.0 |
| 向量库 | Milvus 2.4 (双集合: gold + standard) |

---

## 🔄 详细流程

### 一、数据导入 → 分析 → 沉淀（全自动）

```
用户上传 CSV/Excel
       │
       ▼
┌──────────────────────────────────────────────────────┐
│  POST /api/v1/upload/preview                         │
│  ETLService.preview_file()                           │
│  ├─ chardet 自动检测编码 (utf-8 → gb18030 → gbk)      │
│  ├─ csv.Sniffer 嗅探分隔符 (\t , | ;)                 │
│  ├─ 列名映射 (支持中文别名: 评价内容→raw_text)          │
│  └─ 返回 {header, rows, total, errors} 供前端预览      │
└──────────────────────────────────────────────────────┘
       │ 用户勾选行 → 点确认
       ▼
┌──────────────────────────────────────────────────────┐
│  POST /api/v1/upload/confirm                         │
│  ETLService.import_selected()                        │
│  ├─ 解析选中行 → Review ORM 对象                      │
│  ├─ reviewed_at 为空时自动补 datetime.now()            │
│  └─ db.flush() → MySQL Review 表                     │
└──────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────┐
│  process_new_reviews()                               │
│  ├─ 情感分析: 关键词计数 (正面26词 / 负面38词)          │
│  ├─ 维度提取: 口味/卫生/分量/温度/口感/价格/服务/安全   │
│  ├─ 风险评分: 安全/卫生=5, 口感=3, 紧急词=5            │
│  └─ 菜品匹配: Dish.name 精确匹配 → 子串包含匹配         │
└──────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────┐
│  get_dish_review_groups()                            │
│  └─ 按 dish_id 聚合 → {dish_name, reviews[]}          │
└──────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────┐
│  push_dish_batch() → Redis List                      │
│  process_dish_batch.delay() → RabbitMQ               │
└──────────────────────────────────────────────────────┘
       │
       ▼  ═══════════ Celery Worker 异步消费 ═══════════
       │
┌──────────────────────────────────────────────────────┐
│  POST http://127.0.0.1:8001/agent/analyze_dish       │
│  ┌────────────────────────────────────────────────┐  │
│  │  节点① keyword_aggregation                      │  │
│  │  ├─ 统计情感分布 (正面/负面/中性)                │  │
│  │  ├─ 投诉维度按加权频次排序                       │  │
│  │  └─ 输出: keyword_summary（自然语言摘要）         │  │
│  └────────────────────────────────────────────────┘  │
│                       ↓                               │
│  ┌────────────────────────────────────────────────┐  │
│  │  节点② rag_reranked                            │  │
│  │  ├─ 向量化菜品名 → 搜索 gold_collection (k=3)    │  │
│  │  ├─ 向量化菜品名 → 搜索 standard_collection (k=3)│  │
│  │  ├─ 加权排序: GOLD×0.7 + STANDARD×0.3           │  │
│  │  └─ 输出: reranked_knowledge (历史经验上下文)     │  │
│  └────────────────────────────────────────────────┘  │
│                       ↓                               │
│  ┌────────────────────────────────────────────────┐  │
│  │  节点③ llm_fusion                              │  │
│  │  ├─ 组装 Prompt: 菜品 + 关键词 + 评价样本 + 经验 │  │
│  │  ├─ 调用 DashScope qwen-plus (temperature=0.3)  │  │
│  │  └─ 输出: 【一句话摘要】+ 【改进建议】            │  │
│  └────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────┘
       │
       ├──→ MySQL Diagnosis 表 (summary + corrective_action)
       │
       └──→ Milvus standard_collection
            (原生 OpenAI embedding → 1024维向量写入)
            供后续 RAG 检索复用
```

### 二、智能问答（RAG 双库检索）

```
用户提问: "红烧肉为什么差评多？"
       │
       ▼
  Frontend → Backend /api/v1/chat/query (SSE 透传)
       │
       ▼
  Agent /agent/chat
       │
       ├─ search_with_score("gold_collection", question, k=2)
       │     └─ 原生 OpenAI embedding → pymilvus.search(metric=IP)
       │
       ├─ search_with_score("standard_collection", question, k=2)
       │
       ├─ 加权合并排序:
       │     gold   × 0.7  (🏅金标 — 管理层认证的标杆经验)
       │     standard × 0.3  (📋普通 — 历史自动沉淀经验)
       │     └─ 取 top-4 加权分最高的作为 LLM 上下文
       │
       └─ LLM 流式生成
             ├─ system: 品控顾问角色 + 检索到的历史经验
             ├─ user: 用户问题
             └─ SSE 逐字流式返回前端
```

### 三、自进化闭环（金标飞升）

```
AI 分析结果写入 standard_collection（普通经验）
       │
       │  品控经理在首页摘要表中点击 👍点赞
       │
       ▼
  Backend /api/v1/config/promote (透传)
       │
       ▼
  Agent /agent/promote
       │
       ├─ 从 standard_collection 按 decision_id 精确查询
       ├─ 写入 gold_collection（可人工修改内容后重新向量化）
       └─ 从 standard_collection 删除原记录

  结果: 被飞升的经验在后续 RAG 检索中获得 0.7 高权重
        管理层认证的方案会优先推荐给 LLM 作为决策依据
```

### 四、日报生成（定时任务）

```
Celery Beat 每小时触发
       │
       ▼
  generate_daily_summary()
       │
       ├─ 查询当日有效评价 (WHERE date(reviewed_at) = today)
       ├─ 计算: 总评价数 / 好评率 / 中性率 / 差评率
       ├─ 统计红榜 TOP3 (好评最多菜品)
       ├─ 统计黑榜 TOP3 (差评最多菜品)
       └─ 写入 MySQL DailySummary 缓存表

  首页仪表盘 → 优先读 DailySummary (cached) → 未命中则实时查询
```

---

## 📸 界面预览

### 首页仪表盘
![首页](canteen-agent/picture/首页.png)

### AI 核心改进摘要
![核心摘要](canteen-agent/picture/核心摘要.png)

### 智能问答（RAG 检索）
![智能问答](canteen-agent/picture/智能问答.png)

### 关键词权重配置
![关键词权重](canteen-agent/picture/关键词权重.png)

---

## ⚡ 快速启动

### 1. 环境要求

- Python 3.11+
- Node.js 18+
- MySQL 8.0、Redis 7、RabbitMQ 3.12、Milvus 2.4（可部署在远程服务器，本项目默认指向 `192.168.10.20`）

### 2. 安装依赖

```bash
# 后端
cd backend
pip install -r requirements.txt

# Agent 微服务
cd ../agent
pip install -r requirements.txt

# 前端
cd ../frontend
npm install
```

### 3. 配置环境变量

复制 `.env.example` 为 `.env`，修改数据库/Redis/RabbitMQ/Milvus 连接地址和 LLM API Key。

### 4. 初始化数据库和 Milvus

```bash
# 启动 Backend 自动建表（首次启动）
cd backend
uvicorn app.main:app --port 8000

# 创建 Milvus 向量集合（仅需一次）
cd ../agent
python init_milvus.py
```

### 5. 启动全部服务（4 个终端）

```powershell
# 终端 1: Backend
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 终端 2: Agent 微服务
cd agent
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload

# 终端 3: Celery Worker（Windows 必须加 --pool=solo）
cd backend
celery -A app.tasks.celery_app worker --loglevel=info --pool=solo

# 终端 4: 前端
cd frontend
npm run dev
```

访问 http://localhost:3000 进入系统。

---

## 📊 功能模块

| 模块 | 路径 | 说明 |
|------|------|------|
| 首页仪表盘 | `/` | 全局情绪指数饼图、红黑榜 TOP3、AI 改进摘要表 |
| 菜品详情 | `/dish/:id` | 单菜品评价趋势 & AI 诊断报告 |
| 数据导入 | `/agent` 页面上传 | 两段式：预览 → 勾选 → 确认 → 自动入队分析 |
| 智能问答 | `/chat` | 基于 Milvus 双库 RAG 的品控对话 |
| 系统配置 | `/agent` 页面配置 | 敏感词、RAG 参数、关键词权重 |

---

## 🔧 Windows 注意事项

- Celery Worker 必须加 `--pool=solo`，Windows 不支持 prefork
- 路径用反斜杠 `\` 或正斜杠 `/` 均可
- 远程服务（MySQL/Redis/RabbitMQ/Milvus）确保防火墙已放行对应端口

---

## 🐳 Docker 部署

```bash
docker-compose up -d
```

包含全部服务：MySQL、Redis、RabbitMQ、Milvus、Backend、Celery Worker、Celery Beat、Agent、Frontend。

---

## 📁 项目结构

```
canteen-agent/
├── agent/                  # Agent 微服务 (LangGraph + Milvus)
│   ├── app/
│   │   ├── nodes/          # 工作流节点 (keyword / rag / llm)
│   │   ├── prompts/        # LLM Prompt 模板
│   │   ├── utils/          # Milvus 连接 / LLM 工具
│   │   └── workflow.py     # LangGraph 工作流编排
│   └── init_milvus.py      # Milvus 集合初始化脚本
├── backend/                # 主后端 (FastAPI)
│   └── app/
│       ├── api/v1/         # REST API (dashboard / dishes / chat / upload / config)
│       ├── models/         # SQLAlchemy ORM 模型
│       ├── services/       # ETL + 评价处理
│       └── tasks/          # Celery 任务 + Redis 队列
├── frontend/               # Vue 3 前端
│   └── src/
│       ├── views/          # 页面组件
│       ├── api/            # API 封装
│       └── stores/         # Pinia 状态管理
├── scripts/                # 种子数据 / SQL
├── picture/                # 项目截图
├── docker-compose.yml      # Docker 编排
└── .env                    # 环境变量
```
