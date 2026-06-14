from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping


class ToolPermission(str, Enum):
    READ = "read"
    WORKSPACE_WRITE = "workspace_write"
    NETWORK = "network"
    EXPORT = "export"
    SENSITIVE_WRITE = "sensitive_write"
    DELETE = "delete"


class ToolValidationError(ValueError):
    """Raised when a tool input does not match its schema."""


class ToolExecutionError(RuntimeError):
    """Raised when a tool cannot be executed safely or successfully."""


@dataclass(frozen=True)
class ToolContext:
    workspace: Path | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    content: Any
    metadata: Mapping[str, Any] = field(default_factory=dict)


ToolHandler = Callable[[Mapping[str, Any], ToolContext], Any]


@dataclass(frozen=True)
class FunctionTool:
    name: str
    description: str
    input_schema: Mapping[str, Any]
    read_only: bool
    permission: ToolPermission
    handler: ToolHandler
    max_result_size: int = 20_000

    def __post_init__(self) -> None:
        if not self.name:
            raise ToolValidationError("tool name is required")
        if not self.description:
            raise ToolValidationError(f"description is required for tool {self.name}")

    def validate(self, input_data: Mapping[str, Any]) -> None:
        schema_type = self.input_schema.get("type")
        if schema_type == "object" and not isinstance(input_data, Mapping):
            raise ToolValidationError(f"{self.name} expects object input")

        required = self.input_schema.get("required", [])
        for field_name in required:
            if field_name not in input_data:
                raise ToolValidationError(f"{self.name} missing required field: {field_name}")

        properties = self.input_schema.get("properties", {})
        for field_name, field_schema in properties.items():
            if field_name not in input_data:
                continue
            expected_type = field_schema.get("type") if isinstance(field_schema, Mapping) else None
            if expected_type and not _matches_json_type(input_data[field_name], expected_type):
                raise ToolValidationError(f"{self.name} field {field_name} must be {expected_type}")

    def call(self, input_data: Mapping[str, Any], context: ToolContext) -> ToolResult:
        self.validate(input_data)
        value = self.handler(input_data, context)
        if isinstance(value, ToolResult):
            return value
        return ToolResult(content=value)

    def model_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": dict(self.input_schema),
            },
        }


def _matches_json_type(value: Any, expected_type: str) -> bool:
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "object":
        return isinstance(value, Mapping)
    return True
