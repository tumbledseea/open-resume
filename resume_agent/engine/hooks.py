from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from resume_agent.engine.trace import TraceLogger
from resume_agent.tools.base import ToolContext, ToolPermission, ToolResult
from resume_agent.tools.registry import ToolRegistry


POST_TOOL_HOOKS: dict[str, tuple[str, ...]] = {
    "generate_resume_modules": ("check_truthfulness",),
    "render_latex": ("check_truthfulness", "check_ats"),
    "revise_resume_section": ("check_truthfulness",),
    "revise_resume_from_match_report": ("check_truthfulness", "match_analysis"),
    "compile_pdf": (),
}


@dataclass
class PostToolHookResult:
    tool_results: list[ToolResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def run_post_tool_hooks(
    tool_name: str,
    original_input: Mapping,
    registry: ToolRegistry,
    context: ToolContext,
    allowed_permissions: set[ToolPermission],
    trace: TraceLogger | None = None,
) -> PostToolHookResult:
    result = PostToolHookResult()
    for hook_name in POST_TOOL_HOOKS.get(tool_name, ()):
        hook_input = _hook_input(original_input, context)
        if trace:
            trace.record(
                "post_tool_hook_call",
                {
                    "source_tool": tool_name,
                    "name": hook_name,
                    "input": hook_input,
                },
            )
        try:
            hook_result = registry.execute(hook_name, hook_input, context, allowed_permissions)
        except Exception as exc:  # noqa: BLE001
            warning = f"post hook {hook_name} after {tool_name} failed: {exc}"
            result.warnings.append(warning)
            if trace:
                trace.record(
                    "post_tool_hook_error",
                    {
                        "source_tool": tool_name,
                        "name": hook_name,
                        "warning": warning,
                    },
                )
            continue
        result.tool_results.append(hook_result)
        if trace:
            trace.record(
                "post_tool_hook_result",
                {
                    "source_tool": tool_name,
                    "name": hook_name,
                    "result": hook_result.content,
                },
            )
    return result


def _hook_input(original_input: Mapping, context: ToolContext) -> dict[str, str]:
    project_dir = original_input.get("project_dir") or context.metadata.get("project_dir")
    if project_dir:
        return {"project_dir": str(project_dir)}
    if context.workspace is not None:
        return {"project_dir": str(context.workspace)}
    return {}
