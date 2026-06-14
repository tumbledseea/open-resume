from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from resume_agent.artifacts.store import (
    diff_artifact,
    rollback_artifact,
    snapshot_artifacts,
)
from resume_agent.tools.base import FunctionTool, ToolPermission, ToolResult
from resume_agent.tools.tool_runtime import resolve_path


def create_artifact_tools(repo_root: Path) -> list[FunctionTool]:
    root = Path(repo_root).resolve()
    return [
        FunctionTool(
            name="snapshot_artifacts",
            description=(
                "Snapshot current resume project artifacts before a risky edit. "
                "Writes project/versions/<version_id>/metadata.json and copied artifacts."
            ),
            input_schema={
                "type": "object",
                "required": ["project_dir"],
                "properties": {
                    "project_dir": {"type": "string"},
                    "paths": {"type": "array"},
                    "reason": {"type": "string"},
                },
            },
            read_only=False,
            permission=ToolPermission.WORKSPACE_WRITE,
            handler=lambda input_data, context: _snapshot_artifacts(root, input_data),
        ),
        FunctionTool(
            name="diff_artifact",
            description="Show a unified diff between a versioned artifact snapshot and the current file.",
            input_schema={
                "type": "object",
                "required": ["project_dir", "version_id", "path"],
                "properties": {
                    "project_dir": {"type": "string"},
                    "version_id": {"type": "string"},
                    "path": {"type": "string"},
                },
            },
            read_only=True,
            permission=ToolPermission.READ,
            handler=lambda input_data, context: _diff_artifact(root, input_data),
        ),
        FunctionTool(
            name="rollback_artifact",
            description="Restore one project artifact from a previous snapshot version.",
            input_schema={
                "type": "object",
                "required": ["project_dir", "version_id", "path"],
                "properties": {
                    "project_dir": {"type": "string"},
                    "version_id": {"type": "string"},
                    "path": {"type": "string"},
                },
            },
            read_only=False,
            permission=ToolPermission.WORKSPACE_WRITE,
            handler=lambda input_data, context: _rollback_artifact(root, input_data),
        ),
    ]


def _snapshot_artifacts(repo_root: Path, input_data: Mapping[str, Any]) -> ToolResult:
    project_dir = resolve_path(repo_root, str(input_data["project_dir"]))
    raw_paths = input_data.get("paths")
    paths = [str(item) for item in raw_paths] if isinstance(raw_paths, list) else None
    snapshot = snapshot_artifacts(
        project_dir=project_dir,
        paths=paths,
        reason=str(input_data.get("reason") or ""),
    )
    return ToolResult(
        content={
            "status": "ok",
            "tool": "snapshot_artifacts",
            "version_id": snapshot.version_id,
            "files": list(snapshot.files),
            "outputs": {
                "version": str(snapshot.version_dir.resolve()),
                "metadata": str(snapshot.metadata_path.resolve()),
            },
        }
    )


def _diff_artifact(repo_root: Path, input_data: Mapping[str, Any]) -> ToolResult:
    project_dir = resolve_path(repo_root, str(input_data["project_dir"]))
    result = diff_artifact(
        project_dir=project_dir,
        version_id=str(input_data["version_id"]),
        path=str(input_data["path"]),
    )
    return ToolResult(content={"status": "ok", "tool": "diff_artifact", **result})


def _rollback_artifact(repo_root: Path, input_data: Mapping[str, Any]) -> ToolResult:
    project_dir = resolve_path(repo_root, str(input_data["project_dir"]))
    result = rollback_artifact(
        project_dir=project_dir,
        version_id=str(input_data["version_id"]),
        path=str(input_data["path"]),
    )
    return ToolResult(content={"status": "ok", "tool": "rollback_artifact", **result})

