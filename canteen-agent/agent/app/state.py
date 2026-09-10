"""Agent 状态定义（TypedDict）—— v4.0 Supervisor-Worker

关于 reducer：这里**故意不使用** `Annotated[list, operator.add]`。

带 reducer 的字段一旦被某个节点用 `return {**state, ...}` 整体返回，旧值会被
再累加一遍（agents_used 指数膨胀）。本项目的约定是「谁写谁负责」：
- `agents_used` / `attempts` / `steps` 由 supervisor 独占写入，返回完整新值；
- `facts` / `analysis` / `audit` 等黑板字段由对应 Worker 独占写入，返回增量 dict。

因此所有节点一律只返回自己负责的键，不要 `{**state}` 整体返回。
"""
from typing import TypedDict, List, Dict, Any
import uuid


def new_decision_id() -> str:
    return f"DEC-{uuid.uuid4().hex[:12].upper()}"


class AgentState(TypedDict, total=False):
    # === 输入字段 ===
    dish_name: str
    dish_id: str
    reviews: List[Dict]
    keyword_weights: Dict[str, float]

    # === NER 提取结果 (v3.0) ===
    ner_results: List[Dict]

    # === 信号融合 (v3.0) ===
    keyword_summary: str
    conflict_analysis: List[Dict]
    should_trigger_improvement: bool

    # === 知识检索 ===
    gold_context: str
    standard_context: str
    reranked_knowledge: str
    multi_kb_results: Dict[str, Any]

    # === 置信度评估 (v3.0) ===
    confidence_score: float
    confidence_action: str
    confidence_factors: Dict[str, float]

    # === 输出字段 ===
    improvement_summary: str
    improvement_detail: str
    decision_id: str
    human_review_required: bool

    # === Supervisor 路由 (v3.0 兼容，线性工作流仍在用) ===
    workflow_stage: str

    # === Supervisor-Worker 编排 (v4.0) ===
    task: str                      # 交给 Supervisor 的任务描述
    plan: List[str]                # 开局规划（粗意向）
    next_worker: str               # 本轮委派对象
    instructions: Dict[str, str]   # 定向指令：{worker_name: instruction}
    route_reason: str              # 路由理由（可观测性）
    steps: int                     # 已走轮数（护栏）
    max_steps: int                 # 轮数上限
    attempts: Dict[str, int]       # 各 Worker 已调用次数（护栏）
    agents_used: List[str]         # 调用轨迹
    review_notes: List[str]        # 审核员最近一次的打回意见
    report_ok: bool                # reporter 是否产出了可交付报告（False=拒发，需人工复核）
    retrieved: bool                # retriever 是否已执行过（成功/失败都算，防重复路由）
    retrieval_ok: bool             # 检索是否成功（False=知识库不可用）
    improvement_revision: int      # 整改单版本号（每次 prescriber 产出 +1，用于判断终审是否过期）

    # === 黑板：各 Worker 独占写入 ===
    facts: Dict[str, Any]          # A 提取专家：结构化事实
    analysis: Dict[str, Any]       # B 分析专家：冲突/根因结论
    audit: Dict[str, Any]          # C 审核员：analysis 预审 {passed, score, issues, warnings, scope}
    report_audit: Dict[str, Any]   # C 审核员：整改单终审 {passed, score, issues, warnings, scope}
