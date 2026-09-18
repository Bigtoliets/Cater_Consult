# 🍽️ 食堂品控智能 Agent 系统

以**菜品为单位**的食堂品控平台：把顾客评价自动聚合成结构化事实，由多智能体
（Supervisor-Worker）定位根因、产出可执行的整改单，经验沉淀进向量库形成可检索资产，
并用整改后的差评率变化自动验证方案、飞升金标 —— 形成闭环。

> 📄 详细文档：
> [canteen-agent/README.md](canteen-agent/README.md)（启动与结构）
> · [canteen-agent/项目结构与运行流程.md](canteen-agent/项目结构与运行流程.md)（逐层流程与 API）
> · [食堂品控Agent系统设计方案.md](食堂品控Agent系统设计方案.md)（产品设计）

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
| 主后端 | FastAPI + SQLAlchemy(async) + APScheduler（内嵌定时任务） |
| Agent | LangGraph + LangChain + Milvus + OpenAI 兼容 LLM |
| 分析消费者 | 独立进程，Redis Stream 消费组，多开即并发 |
| 存储 | MySQL 8.0（业务） + Redis 7（队列/锁） + Milvus（向量） |

---

## 🔄 核心链路

```
评论进入 MySQL
  │
  ├─ ① 自动同步（默认每 5 分钟 / 也可手动触发）
  ├─ ② 预处理：情感分析 + 维度提取 + 风险评分 + 菜品匹配
  │     食安级（risk≥5）立即推 CRITICAL 告警
  ├─ ③ 按菜品分片入队（Redis Stream，按风险降序）
  │
  ├─ ④ agent-consumer 消费
  │     ├─ 分片级：LLM NER 抽结构化事实（失败降级词典）
  │     └─ 菜品级：Supervisor ⇄ Worker 星形编排
  │           supervisor 决定下一步 / 打回 / 收工
  │           extractor · analyst · auditor · retriever · prescriber · reporter
  │           两段式审核：分析结论预审 + 整改单终审（审真正要交付的文本）
  │
  ├─ ⑤ 回调 backend：写 diagnoses + 回写评论精判标签 + 需复核时推 WARNING
  └─ ⑥ 沉淀 Milvus → 效果追踪（3/7/14 天差评率）→ 有效则自动飞升金标
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

```bash
# 1) 基础设施（MySQL / Redis / Milvus）
cd canteen-agent && docker compose up -d

# 2) 建库 + 建表 + 种子数据（幂等）
cd backend && python init_db.py

# 3) Milvus 向量集合（仅一次）
cd ../agent && python init_milvus.py

# 4) 四个进程：Backend / 分析消费者 / Agent 微服务 / 前端
cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
cd agent   && python -m app.consumer --consumer c1
cd agent   && uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
cd frontend && npm run dev
```

访问 http://localhost:3000 进入系统；环境变量见 `canteen-agent/.env.example`。

---

## 📊 功能模块

| 模块 | 路径 | 说明 |
|------|------|------|
| 首页仪表盘 | `/` | 全局情绪指数、红黑榜 TOP3、AI 改进摘要表、金标飞升 |
| 菜品详情 | `/dish/:id` | 单菜品评价趋势、AI 诊断报告、下发 / 驳回 |
| 智能问答 | `/chat` | ReAct（原生 function calling）+ 8 个工具 + 记忆 + 幻觉防护；每步 checkpoint，断线凭 turn_id 续跑 |
| 系统配置 | `/agent` | 同步触发、敏感词、关键词权重、推送规则 |

---

## 🐳 Docker 部署

```bash
cd canteen-agent
docker compose up -d
docker compose exec backend python init_db.py   # 首次灌种子数据（幂等）
```

包含：MySQL、Redis、Milvus（+etcd/minio）、Backend、Agent、Agent Consumer、Frontend。

---

## 📁 项目结构

```
Cater_Consult/
├── canteen-agent/
│   ├── agent/        # Agent 微服务 + 分析消费者（Supervisor-Worker / ReAct / 工具 / 记忆）
│   ├── backend/      # 主后端（API / 同步 / 推送 / 定时任务 / ORM）
│   ├── frontend/     # Vue 3 前端
│   ├── picture/      # 界面截图
│   └── docker-compose.yml
├── 食堂品控Agent系统设计方案.md
└── README.md
```

---

## 🔧 Windows 注意事项

- 定时任务已改为 APScheduler 内嵌在 backend 进程，**不再需要 Celery / RabbitMQ**
- 远程基础设施（MySQL / Redis / Milvus）确保防火墙放行对应端口
- 离线自测脚本：`python canteen-agent/agent/tests/test_supervisor_routing.py` 等，无需 DB / Redis / LLM
