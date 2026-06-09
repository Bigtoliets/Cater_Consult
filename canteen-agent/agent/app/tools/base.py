"""工具系统 — 标准化Tool接口 + ToolRegistry (v4.0)

每个Tool:
- 有明确的 name/description/parameters schema (供LLM理解)
- 有 execute 方法 (实际执行)
- 有 validate_result 方法 (幻觉防护)
- 有 fallback 方法 (降级兜底)
- 返回统一 ToolResult 格式
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
import json


@dataclass
class ToolResult:
    """统一的工具返回格式"""
    success: bool
    data: Any = None
    error: str = ""
    source: str = ""           # 数据来源 (用于引用)
    confidence: float = 1.0    # 结果置信度
    metadata: dict = field(default_factory=dict)

    def format_for_llm(self) -> str:
        """格式化为LLM可理解的字符串"""
        if not self.success:
            return f"[工具错误] {self.error}"

        source_tag = f" (来源: {self.source})" if self.source else ""
        conf_tag = f" [置信度: {self.confidence:.0%}]" if self.confidence < 1.0 else ""

        if isinstance(self.data, str):
            return f"{self.data}{source_tag}{conf_tag}"
        elif isinstance(self.data, (list, dict)):
            return json.dumps(self.data, ensure_ascii=False, indent=2) + source_tag + conf_tag
        return str(self.data) + source_tag + conf_tag


class BaseTool(ABC):
    """所有工具的抽象基类"""

    @property
    @abstractmethod
    def name(self) -> str:
        """工具唯一标识"""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """工具描述 (供LLM理解何时使用)"""
        ...

    @property
    @abstractmethod
    def parameters(self) -> dict:
        """参数schema (JSON Schema格式)"""
        ...

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """执行工具"""
        ...

    async def validate_result(self, result: ToolResult) -> ToolResult:
        """验证结果有效性 (子类可重写)"""
        return result

    async def fallback(self, **kwargs) -> ToolResult:
        """降级兜底"""
        return ToolResult(success=False, error=f"{self.name}: 降级不可用")

    def get_schema_for_llm(self) -> dict:
        """生成供LLM function calling使用的schema"""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


class ToolRegistry:
    """工具注册中心 — 管理所有可用工具"""

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool):
        """注册工具"""
        self._tools[tool.name] = tool
        print(f"[ToolRegistry] 注册工具: {tool.name}")

    def get(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def get_all(self) -> list[BaseTool]:
        return list(self._tools.values())

    def get_schemas_for_llm(self) -> list[dict]:
        """获取所有工具的schema (供LLM function calling)"""
        return [t.get_schema_for_llm() for t in self._tools.values()]

    def get_tool_descriptions(self) -> str:
        """格式化为Prompt可用的工具描述"""
        lines = []
        for tool in self._tools.values():
            params_desc = json.dumps(tool.parameters.get("properties", {}), ensure_ascii=False)
            lines.append(f"- **{tool.name}**: {tool.description}")
            lines.append(f"  参数: {params_desc}")
        return "\n".join(lines)

    async def execute_tool(self, name: str, **kwargs) -> ToolResult:
        """执行指定工具 + 验证 + 降级"""
        tool = self._tools.get(name)
        if not tool:
            return ToolResult(success=False, error=f"未知工具: {name}")

        try:
            result = await tool.execute(**kwargs)
            # 验证
            result = await tool.validate_result(result)
            return result
        except Exception as e:
            # 降级
            print(f"[ToolRegistry] {name} 执行失败: {e}")
            try:
                return await tool.fallback(**kwargs)
            except Exception:
                return ToolResult(success=False, error=str(e))


# 全局单例
_tool_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    global _tool_registry
    if _tool_registry is None:
        _tool_registry = ToolRegistry()
    return _tool_registry
