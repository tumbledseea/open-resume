from __future__ import annotations

from pathlib import Path

from resume_agent.tools.base import FunctionTool
from resume_agent.tools.artifact_tools import create_artifact_tools
from resume_agent.tools.jd_tools import create_jd_tools
from resume_agent.tools.job_hunt_tools import create_job_hunt_tools
from resume_agent.tools.latex_tools import create_latex_tools
from resume_agent.tools.llm_runtime import LLMConfigError, complete_json
from resume_agent.tools.match_tools import create_match_tools
from resume_agent.tools.memory_tools import create_memory_tools
from resume_agent.tools.pipeline_tools import create_pipeline_tools
from resume_agent.tools.profile_tools import create_profile_tools
from resume_agent.tools.quality_tools import create_quality_tools
from resume_agent.tools.registry import ToolRegistry
from resume_agent.tools.resume_section_tools import create_resume_section_tools
from resume_agent.tools.resume_tools import create_resume_tools
from resume_agent.tools.source_tools import create_source_tools
from resume_agent.tools.strategy_tools import create_strategy_tools
from resume_agent.tools.tool_runtime import default_repo_root


def create_builtin_registry(
    repo_root: Path | str | None = None,
    *,
    include_mcp: bool = True,
) -> ToolRegistry:
    """Create a ToolRegistry populated with all built-in tools.

    When *include_mcp* is True (the default), tools discovered from
    configured MCP servers are also registered.  MCP tools are gated behind
    ``ToolPermission.NETWORK``, so they only appear when the caller passes
    ``--allow-network``.  A broken or unreachable MCP server is silently
    skipped — it never blocks the agent from starting.
    """
    root = Path(repo_root).resolve() if repo_root is not None else default_repo_root()
    registry = ToolRegistry()
    for tool in _builtin_tools(root):
        registry.register(tool)

    if include_mcp:
        _register_mcp_tools(registry, root)

    return registry


def _register_mcp_tools(registry: ToolRegistry, repo_root: Path) -> None:
    try:
        from resume_agent.mcp.registry import load_mcp_tools
    except ImportError:
        return
    try:
        mcp_tools = load_mcp_tools(str(repo_root))
    except Exception:
        # MCP server failure is non-fatal — agent works fine without them.
        return
    for tool in mcp_tools:
        try:
            registry.register(tool)
        except Exception:
            pass  # duplicate name or other register error — skip


def _builtin_tools(repo_root: Path) -> list[FunctionTool]:
    tools: list[FunctionTool] = []
    for provider in (
        create_source_tools,
        create_profile_tools,
        create_pipeline_tools,
        create_jd_tools,
        create_job_hunt_tools,
        create_strategy_tools,
        create_resume_tools,
        create_resume_section_tools,
        create_latex_tools,
        create_quality_tools,
        create_match_tools,
        create_artifact_tools,
        create_memory_tools,
    ):
        tools.extend(provider(repo_root))
    return tools


__all__ = [
    "LLMConfigError",
    "complete_json",
    "create_builtin_registry",
]
