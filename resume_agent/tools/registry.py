from __future__ import annotations

from typing import Iterable, Mapping

from resume_agent.tools.base import (
    FunctionTool,
    ToolContext,
    ToolExecutionError,
    ToolPermission,
    ToolResult,
)
from resume_agent.tools.permissions import PermissionPolicy


class ToolRegistryError(RuntimeError):
    """Raised when a tool registry operation is invalid."""


class ToolRegistry:
    def __init__(self, permission_policy: PermissionPolicy | None = None) -> None:
        self._tools: dict[str, FunctionTool] = {}
        self.permission_policy = permission_policy or PermissionPolicy()

    def register(self, tool: FunctionTool) -> None:
        if tool.name in self._tools:
            raise ToolRegistryError(f"duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> FunctionTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolRegistryError(f"unknown tool: {name}") from exc

    def available_tools(self, allowed_permissions: Iterable[ToolPermission]) -> list[FunctionTool]:
        allowed = set(allowed_permissions)
        return sorted(
            [tool for tool in self._tools.values() if tool.permission in allowed],
            key=lambda tool: tool.name,
        )

    def model_schemas(self, allowed_permissions: Iterable[ToolPermission]) -> list[dict]:
        return [tool.model_schema() for tool in self.available_tools(allowed_permissions)]

    def execute(
        self,
        name: str,
        input_data: Mapping,
        context: ToolContext,
        allowed_permissions: Iterable[ToolPermission],
    ) -> ToolResult:
        tool = self.get(name)
        if tool.permission not in set(allowed_permissions):
            raise ToolExecutionError(f"tool {name} is not allowed for current permissions")
        self.permission_policy.check_before(tool, input_data, context)
        result = tool.call(input_data, context)
        self.permission_policy.check_after(tool, input_data, context, result)
        return _truncate_result(result, tool.max_result_size)


def _truncate_result(result: ToolResult, max_size: int) -> ToolResult:
    if isinstance(result.content, str) and len(result.content) > max_size:
        metadata = dict(result.metadata)
        metadata["truncated"] = True
        metadata["original_size"] = len(result.content)
        return ToolResult(content=result.content[:max_size], metadata=metadata)
    return result
