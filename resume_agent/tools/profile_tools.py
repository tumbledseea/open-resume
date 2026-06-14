from __future__ import annotations

import shutil
from pathlib import Path

from resume_agent.tools.base import (
    FunctionTool,
    ToolContext,
    ToolExecutionError,
    ToolPermission,
    ToolResult,
)
from resume_agent.tools.tool_runtime import resolve_path, run_script, script_result


def create_profile_tools(repo_root: Path) -> list[FunctionTool]:
    root = Path(repo_root).resolve()
    return [
        FunctionTool(
            name="read_user_profile",
            description=(
                "Read the user's uploaded profile file content. "
                "The file path is fixed by the engine."
            ),
            input_schema={"type": "object", "properties": {}},
            read_only=True,
            permission=ToolPermission.READ,
            handler=lambda input_data, context: _read_user_profile(context),
        ),
        FunctionTool(
            name="import_profile",
            description="Copy the user's uploaded profile file into the project's profile/profile.md.",
            input_schema={"type": "object", "properties": {}},
            read_only=False,
            permission=ToolPermission.WORKSPACE_WRITE,
            handler=lambda input_data, context: _import_profile(root, context),
        ),
        FunctionTool(
            name="normalize_profile",
            description=(
                "Extract structured facts from project's profile/profile.md "
                "into profile.json and fact_index.json. "
                "The project profile path is fixed by the engine."
            ),
            input_schema={"type": "object", "properties": {}},
            read_only=False,
            permission=ToolPermission.WORKSPACE_WRITE,
            handler=lambda input_data, context: _normalize_profile(root, context),
        ),
    ]


def _read_user_profile(context: ToolContext) -> ToolResult:
    profile_file = context.metadata.get("profile_file", "")
    if not profile_file:
        return ToolResult(content={"status": "no_profile", "content": ""})
    path = Path(profile_file)
    if not path.is_file():
        return ToolResult(content={"status": "not_found", "path": str(path), "content": ""})
    content = path.read_text(encoding="utf-8-sig")
    return ToolResult(
        content={
            "status": "ok",
            "path": str(path),
            "filename": path.name,
            "content": content,
            "length": len(content),
        }
    )


def _import_profile(repo_root: Path, context: ToolContext) -> ToolResult:
    profile_file = context.metadata.get("profile_file", "")
    project_dir = context.metadata.get("project_dir", "")

    if not profile_file:
        raise ToolExecutionError("No profile file was provided. Pass --profile-file on the CLI.")

    src = Path(profile_file)
    if not src.is_file():
        raise ToolExecutionError(f"Profile file not found: {src}")

    dst = resolve_path(repo_root, str(project_dir)) / "profile" / "profile.md"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)

    return ToolResult(
        content={
            "status": "ok",
            "tool": "import_profile",
            "source": str(src),
            "outputs": {"profile_md": str(dst.resolve())},
        }
    )


def _normalize_profile(repo_root: Path, context: ToolContext) -> ToolResult:
    project_dir_str = context.metadata.get("project_dir", "")
    if not project_dir_str:
        raise ToolExecutionError("normalize_profile requires project_dir in context metadata")
    project_dir = resolve_path(repo_root, project_dir_str)
    profile_md = project_dir / "profile" / "profile.md"
    if not profile_md.is_file():
        raise ToolExecutionError(f"profile.md not found at {profile_md}. Call import_profile first.")
    result = run_script(
        repo_root,
        ["source_to_profile/llm_normalize_profile.py", "--profile-md", str(profile_md)],
    )
    return script_result(
        "normalize_profile",
        result,
        {
            "profile_json": profile_md.with_name("profile.json"),
            "fact_index": profile_md.with_name("fact_index.json"),
        },
    )

