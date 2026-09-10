"""LangGraph 工作流 (v4.0)

两级管线：
- 分片级（固定线路）: 提取专家单独跑，产出结构化 facts。不查库、不出方案。
  实现在 pipeline.process_chunk()，是一条直链，不需要建图。
- 菜品级（动态编排）: Supervisor ⇄ Worker，由 Supervisor 决定委派谁、是否打回、何时收工。

图的结构刻意保持「星形」：所有 Worker 干完都回到 supervisor 重新决策 ——
决策依据（审核意见、调用次数、黑板状态）只有回到中枢时才拿得到，
任何把 Worker 直接串起来的固定边都会让「打回重做」变得不可能。
"""
from langgraph.graph import StateGraph, END

from app.agents import (
    analyst_node,
    auditor_node,
    extractor_node,
    prescriber_node,
    reporter_node,
    retriever_node,
    supervisor_node,
)
from app.state import AgentState

# Worker 节点注册表：新增 Worker 只需在这里加一行
WORKER_NODES = {
    "extractor": extractor_node,
    "analyst": analyst_node,
    "auditor": auditor_node,
    "retriever": retriever_node,
    "prescriber": prescriber_node,
    "reporter": reporter_node,
}

ROUTE_FINISH = "FINISH"

# 图递归上限：一轮 Supervisor + 一个 Worker = 2 个 superstep。
# Supervisor 自身的 MAX_STEPS（10）才是真正的业务护栏，这里只负责别让 LangGraph
# 默认的 25 先撞上，抛出一条没人接的 GraphRecursionError。
RECURSION_LIMIT = 40


def build_supervisor_workflow() -> StateGraph:
    """Supervisor-Worker 编排图"""
    wf = StateGraph(AgentState)

    wf.add_node("supervisor", supervisor_node)
    for name, fn in WORKER_NODES.items():
        wf.add_node(name, fn)

    wf.set_entry_point("supervisor")
    wf.add_conditional_edges(
        "supervisor",
        lambda state: state["next_worker"],
        {**{name: name for name in WORKER_NODES}, ROUTE_FINISH: END},
    )

    # 所有 Worker 干完都交回中枢重新决策 —— 包括 reporter。
    # 这样「必须过 reporter 才允许 FINISH」的护栏才落得下：结束与否由中枢判定，
    # 而不是由 reporter 直接连 END 绕过。出了报告仍被打回重做的场景也才可能有。
    for name in WORKER_NODES:
        wf.add_edge(name, "supervisor")

    return wf


# Supervisor-Worker 工作流（主用）
supervisor_workflow = build_supervisor_workflow().compile()
