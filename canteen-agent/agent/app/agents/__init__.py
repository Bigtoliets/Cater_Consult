"""多Agent 协同模块 (v3.0 新增)

模拟后厨品控团队工作流:
- Classifier: 评价分类 + NER 实体提取
- Diagnostician: 多维度信号融合 + 冲突检测
- Retriever: 五维知识库并行检索
- Prescriber: 整改方案生成 + 置信度评估
- Reporter: 报告范式化
- Supervisor: 决策路由 + 异常升级

当前作为 Supervisor 模式的包装层, 各 Agent 委托给现有 nodes/ 实现.
未来可独立拆分为微服务.
"""
from app.agents.supervisor import supervisor_node, rule_router
from app.agents.classifier import classifier_node
from app.agents.diagnostician import diagnostician_node
from app.agents.retriever import retriever_node
from app.agents.prescriber import prescriber_node
from app.agents.reporter import reporter_node

__all__ = [
    "supervisor_node", "rule_router",
    "classifier_node", "diagnostician_node",
    "retriever_node", "prescriber_node",
    "reporter_node",
]
