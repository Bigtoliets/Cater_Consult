# 🍽️ 食堂品控智能 Agent 系统

基于 **LangGraph + Milvus + LLM** 的菜品质量智能分析平台：自动聚合顾客评价 →
多智能体诊断 → 生成整改单 → 向量库沉淀经验 → 效果追踪后自动飞升金标，形成自进化闭环。

---

## 🏗️ 架构总览

```
┌─────────────┐     ┌──────────────┐     ┌───────────────┐
│   Frontend   │────▶│   Backend     │────▶│     Agent      │
│  Vue 3 :3000 │     │ FastAPI :8000 │     │ FastAPI :8001  │
└─────────────┘     └───┬──────┬───┘     └───────┬───────┘
                        │      │                 │
              ┌─────────▼──┐  ┌▼──────────────┐  │
              │   MySQL    │  │     Redis      │  │
              │ 业务数据    │  │ Stream + 锁    │  │
              └────────────┘  └───────┬────────┘  │
                                      │           │
                              ┌───────▼───────────▼──┐
                              │  agent-consumer       │
                              │  Redis Stream 消费组   │
                              └───────────┬──────────┘
                                          │
                                   ┌──────▼──────┐
                                   │   Milvus     │
                                   │  五库向量    │
                                   └─────────────┘
```

| 组件 | 技术栈 |
|------|--------|
| 前端 | Vue 3 + Element Plus + ECharts |
| 主后端 | FastAPI + SQLAlchemy(async) + APScheduler（内嵌，无 Celery） |
| Agent 微服务 | FastAPI + LangGraph + LangChain + pymilvus |
| 分析消费者 | 独立进程 `python -m app.consumer`，Redis Stream 消费组，多开即并发 |
| LLM / Embedding | 任意 OpenAI 兼容接口（默认 `gpt-4o` / `text-embedding-3-small`） |
| 消息队列 | Redis Stream（无 RabbitMQ） |
| 数据库 / 向量库 | MySQL 8.0 / Milvus 2.4（五集合） |

---

## 🚀 核心链路

```
评论进入 MySQL（外部系统写入 / SQL 导入）
  │
  ├─ ① 自动同步（APScheduler，默认每 5 分钟；也可点页面按钮或 POST /api/v1/sync）
  │     取 synced_at IS NULL 的评论
  ├─ ② 预处理（词典）：情感分析 + 维度提取 + 风险评分 + 菜品匹配 → label_source=dict
  │     risk_level ≥ 5 → 立即推 CRITICAL 告警
  ├─ ③ 按菜品聚合 → 每 80 条分片 → XADD agent:dish:stream（按风险降序）
  └─ ④ 最后才标记 synced_at（先入队后标记，入队失败不丢评论）
        │
        └── [agent-consumer] 消费分片
              ├─ 分片级：提取专家 → facts（LLM NER，失败降级词典），结果按菜品聚合
              ├─ 最后一片 → 菜品级 Supervisor-Worker 编排
              │     supervisor ⇄ {extractor, analyst, auditor, retriever, prescriber, reporter}
              │     两段式审核：analysis 预审 + report 终审（审的是要交付的整改单）
              ├─ POST backend /api/v1/internal/diagnosis
              │     ├─ 写 diagnoses（含诊断轨迹：冲突分析 + 两段审核 + 调用轨迹）
              │     ├─ 回写评论精判标签（label_source=llm）
              │     └─ human_review_required → 推 WARNING 告警
              └─ 写 Milvus standard_collection（经验沉淀，仅在有可交付报告时）
        │
        └── APScheduler：日报（1h）、效果追踪（24h，有效→自动飞升金标）
```

**两段式审核**：`audit` 审分析结论有没有事实支撑，`report_audit` 审最终整改单
（幻觉、绝对化表述、步骤是否可执行）。终审不过会打回 prescriber 重写并带上审核意见；
重写预算用完则带「需人工复核」标记收口。

**五库检索**：`sop` / `pattern` / `cycle` / `gold` / `standard`，加权合并后作为整改单的上下文。

问答链路另有一层**会话记忆**：短期记忆（滑动窗口 + 压缩摘要）拼进当轮消息链，
长期记忆（Q/A 摘要）写 `memory_collection` 并按会话过滤 —— 既不串会话，
也不混进上面这五个品控知识库。

---

## 📸 界面预览

### 首页仪表盘
![首页](picture/首页.png)

### AI 核心改进摘要
![核心摘要](picture/核心摘要.png)

### 智能问答（RAG 检索）
![智能问答](picture/智能问答.png)

### 关键词权重配置
![关键词权重](picture/关键词权重.png)

---

## ⚡ 快速启动

### 1. 环境要求

- Python 3.11+ / Node.js 18+
- MySQL 8.0、Redis 7、Milvus 2.4（可用 `docker-compose.yml` 一并拉起）

### 2. 安装依赖

```bash
cd backend && pip install -r requirements.txt
cd ../agent && pip install -r requirements.txt
cd ../frontend && npm install
```

### 3. 配置环境变量

复制 `.env.example` 为 `.env`，修改 MySQL / Redis / Milvus 地址与 LLM Key。
关键项：`AUTO_SYNC_INTERVAL_MINUTES`（自动同步间隔，0=关闭）、`CONSUMER_CONCURRENCY`。

### 4. 初始化

```bash
# 建库 + 建表 + 种子数据（幂等，可重复执行）
cd backend && python init_db.py

# 创建 Milvus 向量集合（仅需一次）
cd ../agent && python init_milvus.py
```

### 5. 启动全部服务（4 个终端）

```powershell
# 终端 1: Backend（API + 推送 + 定时任务）
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 终端 2: Agent 分析消费者（可多开，同一消费组自动分片）
cd agent
python -m app.consumer --consumer c1

# 终端 3: Agent 微服务（ReAct 问答 / 调试端点）
cd agent
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload

# 终端 4: 前端
cd frontend
npm run dev
```

访问 http://localhost:3000 进入系统。

---

## 📊 功能模块

| 模块 | 路径 | 说明 |
|------|------|------|
| 首页仪表盘 | `/` | 全局情绪指数、红黑榜 TOP3、AI 改进摘要表、金标飞升 |
| 菜品详情 | `/dish/:id` | 单菜品评价趋势、AI 诊断报告、下发 / 驳回 |
| 智能问答 | `/chat` | ReAct（原生 function calling）+ 工具 + 记忆 + 幻觉防护；每步 checkpoint，断线凭 turn_id 续跑 |
| 系统配置 | `/agent` | 同步触发、敏感词、关键词权重、推送规则 |

---

## 🔧 Windows 注意事项

- 定时任务已改为 APScheduler 内嵌在 backend 进程，**不再需要 Celery**（`--pool=solo` 那套已废弃）
- 路径用反斜杠 `\` 或正斜杠 `/` 均可
- 远程基础设施（MySQL / Redis / Milvus）确保防火墙已放行对应端口
- 离线自测脚本直接跑 `python agent/tests/xxx.py`（会自己 reconfigure stdout 编码，避免 GBK 报错）

---

## 🐳 Docker 部署

```bash
docker compose up -d
# 首次部署灌种子数据（幂等）
docker compose exec backend python init_db.py
```

包含：MySQL、Redis、Milvus（+etcd/minio）、Backend、Agent、Agent Consumer、Frontend。
**建表与种子数据以 SQLAlchemy 模型为唯一事实来源**（`backend/init_db.py`），
不再维护手工 SQL 建表脚本。

---

## 📁 项目结构

```
canteen-agent/
├── agent/                        # Agent 微服务 + 分析消费者
│   ├── app/
│   │   ├── consumer.py           # Redis Stream 消费：分片分析 → 菜品级合并 → 回调写库
│   │   ├── pipeline.py           # 两级管线：分片级 facts / 菜品级 Supervisor-Worker
│   │   ├── queue.py              # 消费侧 Redis 客户端（聚合、锁、死信）
│   │   ├── workflow.py           # LangGraph 星形图（supervisor ⇄ workers）
│   │   ├── agents/               # 六个 Worker + Supervisor
│   │   ├── nodes/                # NER / 信号融合 / 置信度 / LLM 整改单
│   │   ├── react/ tools/ memory/ # ReAct 问答引擎、8 个工具、三层记忆
│   │   ├── chat/                 # turn checkpoint（Redis）、并发锁、结构化追踪日志
│   │   ├── prompts/              # Supervisor / ReAct / 整改单 Prompt
│   │   └── utils/                # LLM、Milvus、五库检索、幻觉检测
│   ├── tests/                    # 离线自测（护栏 / 交付契约 / 端到端）
│   └── init_milvus.py            # Milvus 集合初始化
├── backend/                      # 主后端
│   ├── app/
│   │   ├── api/v1/               # dashboard / dishes / config / chat / sync / shops / internal
│   │   ├── services/             # 同步、预处理、效果追踪
│   │   ├── tasks/                # Redis 生产侧 + APScheduler 定时任务
│   │   ├── push/                 # 企微 / 钉钉 / 邮件 dispatcher
│   │   └── models/               # SQLAlchemy ORM（建表的唯一事实来源）
│   ├── init_db.py                # 建库 + 建表 + 种子数据
│   └── tests/                    # 离线自测（效果追踪窗口逻辑）
├── frontend/                     # Vue 3 前端
├── picture/                      # 项目截图
└── docker-compose.yml            # 全栈编排
```
