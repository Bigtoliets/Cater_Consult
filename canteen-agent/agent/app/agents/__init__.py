"""多Agent 协同模块 (v4.0 Supervisor-Worker)

模拟后厨品控团队，Supervisor 只调度不干活，Worker 各司其职：

- Supervisor  决策中枢：规划 / 委派 / 把关，工具注册表为空
- extractor   提取专家（A）：LLM 语义提取 → 结构化事实
- analyst     分析专家（B）：冲突检测 + 根因推理
- auditor     审核员（C）：一致性校验，防幻觉，不通过就打回
- retriever   检索专家：五库并行检索（简单客诉可被跳过）
- prescriber  处方专家：整改单 + 置信度
- reporter    报告专家：范式化输出

所有节点一律只返回自己负责的键，不返回 {**state}（见 state.py 的约定）。
"""
from app.agents.supervisor import supervisor_node, rule_fallback
from app.agents.extractor import extractor_node
from app.agents.analyst import analyst_node
from app.agents.auditor import auditor_node
from app.agents.retriever import retriever_node
from app.agents.prescriber import prescriber_node
from app.agents.reporter import reporter_node

__all__ = [
    "supervisor_node", "rule_fallback",
    "extractor_node", "analyst_node", "auditor_node",
    "retriever_node", "prescriber_node", "reporter_node",
]
