"""工具系统 — 自动注册所有工具到 ToolRegistry"""
from app.tools.base import ToolRegistry, ToolResult, BaseTool, get_tool_registry
from app.tools.kb_search import KnowledgeBaseSearchTool
from app.tools.dish_info import DishInfoTool
from app.tools.sop_lookup import SOPLookupTool
from app.tools.entity_extract import EntityExtractionTool
from app.tools.fact_check import FactCheckTool
from app.tools.similar_cases import SimilarCasesTool
from app.tools.confidence_calc import ConfidenceCalcTool
from app.tools.output_validator import OutputValidatorTool


def register_all_tools() -> ToolRegistry:
    """注册所有工具到全局 ToolRegistry"""
    registry = get_tool_registry()

    registry.register(KnowledgeBaseSearchTool())
    registry.register(DishInfoTool())
    registry.register(SOPLookupTool())
    registry.register(EntityExtractionTool())
    registry.register(FactCheckTool())
    registry.register(SimilarCasesTool())
    registry.register(ConfidenceCalcTool())
    registry.register(OutputValidatorTool())

    print(f"[Tools] 已注册 {len(registry.get_all())} 个工具")
    return registry


__all__ = [
    "ToolRegistry", "ToolResult", "BaseTool", "get_tool_registry",
    "register_all_tools",
]
