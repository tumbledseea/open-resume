from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from resume_agent.tools.base import FunctionTool, ToolContext, ToolExecutionError, ToolPermission, ToolResult


_WRITE_PERMISSIONS = {
    ToolPermission.WORKSPACE_WRITE,
    ToolPermission.EXPORT,
    ToolPermission.SENSITIVE_WRITE,
    ToolPermission.DELETE,
}
_PATH_FIELD_NAMES = {
    "path",
    "paths",
    "file",
    "files",
    "output",
    "outputs",
    "output_path",
    "target",
    "target_path",
}
_PATH_FIELD_SUFFIXES = ("_path", "_paths", "_file", "_files", "_dir", "_dirs")
_SKIP_PATH_FIELD_NAMES = {"project_dir", "profile_file", "url", "jd_url"}


@dataclass(frozen=True)
class PermissionPolicy:
    """Runtime safety checks layered on top of coarse ToolPermission filtering."""

    def check_before(self, tool: FunctionTool, input_data: Mapping[str, Any], context: ToolContext) -> None:
        if tool.permission == ToolPermission.NETWORK and context.metadata.get("allow_network") is not True:
            raise ToolExecutionError(f"network approval required for tool {tool.name}")
        if tool.permission == ToolPermission.DELETE:
            raise ToolExecutionError("delete permission is denied by default")
        if tool.permission == ToolPermission.SENSITIVE_WRITE:
            if context.metadata.get("allow_sensitive_write") is not True or input_data.get("confirm_sensitive_write") is not True:
                raise ToolExecutionError(f"sensitive write approval required for tool {tool.name}")
        if tool.permission in _WRITE_PERMISSIONS:
            project_dir = _project_dir(input_data, context)
            if project_dir is not None:
                _check_path_inputs(project_dir, input_data)

    def check_after(
        self,
        tool: FunctionTool,
        input_data: Mapping[str, Any],
        context: ToolContext,
        result: ToolResult,
    ) -> None:
        if tool.permission not in _WRITE_PERMISSIONS:
            return
        project_dir = _project_dir(input_data, context)
        if project_dir is None:
            return
        outputs = _outputs(result)
        for name, value in outputs.items():
            for path in _iter_path_values(value):
                _assert_inside_project(project_dir, path, field=f"outputs.{name}")


def _project_dir(input_data: Mapping[str, Any], context: ToolContext) -> Path | None:
    raw = input_data.get("project_dir") or context.metadata.get("project_dir")
    if raw:
        return Path(str(raw)).resolve()
    if context.workspace is not None:
        return Path(context.workspace).resolve()
    return None


def _check_path_inputs(project_dir: Path, value: Any, key_path: str = "") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            child_key = f"{key_path}.{key_text}" if key_path else key_text
            if key_text in _SKIP_PATH_FIELD_NAMES:
                continue
            if _is_path_field(key_text):
                for raw_path in _iter_path_values(item):
                    _assert_inside_project(project_dir, raw_path, field=child_key)
            elif isinstance(item, (Mapping, list, tuple)):
                _check_path_inputs(project_dir, item, child_key)
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _check_path_inputs(project_dir, item, f"{key_path}[{index}]")


def _is_path_field(key: str) -> bool:
    normalized = key.strip().lower()
    return normalized in _PATH_FIELD_NAMES or normalized.endswith(_PATH_FIELD_SUFFIXES)


def _iter_path_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        result: list[str] = []
        for item in value:
            result.extend(_iter_path_values(item))
        return result
    if isinstance(value, Mapping):
        result: list[str] = []
        for item in value.values():
            result.extend(_iter_path_values(item))
        return result
    if isinstance(value, (str, Path)):
        text = str(value).strip()
        if not text or "://" in text:
            return []
        return [text]
    return []


def _assert_inside_project(project_dir: Path, raw_path: str, field: str) -> None:
    path = Path(raw_path)
    resolved = path.resolve() if path.is_absolute() else (project_dir / path).resolve()
    try:
        resolved.relative_to(project_dir)
    except ValueError as exc:
        raise ToolExecutionError(f"{field} path is outside project: {raw_path}") from exc


def _outputs(result: ToolResult) -> Mapping[str, Any]:
    if not isinstance(result.content, Mapping):
        return {}
    outputs = result.content.get("outputs", {})
    return outputs if isinstance(outputs, Mapping) else {}
