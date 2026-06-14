from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from resume_agent.tools.base import FunctionTool, ToolPermission, ToolResult
from resume_agent.tools.tool_runtime import resolve_path, run_script, script_result


def create_strategy_tools(repo_root: Path) -> list[FunctionTool]:
    root = Path(repo_root).resolve()
    return [
        FunctionTool(
            name="build_resume_strategy",
            description="Build strategy/resume_strategy.md and strategy/spec_lock.json from JD analysis.",
            input_schema={
                "type": "object",
                "required": ["project_dir"],
                "properties": {"project_dir": {"type": "string"}},
            },
            read_only=False,
            permission=ToolPermission.WORKSPACE_WRITE,
            handler=lambda input_data, context: _build_resume_strategy(root, input_data),
        ),
    ]


def _build_resume_strategy(repo_root: Path, input_data: Mapping[str, Any]) -> ToolResult:
    project_dir = resolve_path(repo_root, str(input_data["project_dir"]))
    result = run_script(repo_root, ["strategy/strategy_defaults.py", "--project", str(project_dir)])
    return script_result(
        "build_resume_strategy",
        result,
        {
            "resume_strategy": project_dir / "strategy" / "resume_strategy.md",
            "spec_lock": project_dir / "strategy" / "spec_lock.json",
        },
    )

