from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Mapping

from resume_agent.tools.base import FunctionTool, ToolPermission, ToolResult
from resume_agent.tools.tool_runtime import resolve_project_dir, run_script, script_result


def create_source_tools(repo_root: Path) -> list[FunctionTool]:
    root = Path(repo_root).resolve()
    return [
        FunctionTool(
            name="import_pdf_source",
            description=(
                "Convert a PDF file (existing resume in PDF form) to Markdown "
                "and write it to profile/profile.md for normalization."
            ),
            input_schema={
                "type": "object",
                "required": ["source_path"],
                "properties": {
                    "source_path": {"type": "string", "description": "Path to the PDF file"},
                    "project_dir": {"type": "string"},
                },
            },
            read_only=False,
            permission=ToolPermission.READ,
            handler=lambda input_data, context: _run_source2md(root, input_data, "pdf2md.py"),
        ),
        FunctionTool(
            name="import_docx_source",
            description="Convert a DOCX/Office file to Markdown and write it to profile/profile.md.",
            input_schema={
                "type": "object",
                "required": ["source_path"],
                "properties": {
                    "source_path": {"type": "string"},
                    "project_dir": {"type": "string"},
                },
            },
            read_only=False,
            permission=ToolPermission.READ,
            handler=lambda input_data, context: _run_source2md(root, input_data, "doc2md.py"),
        ),
        FunctionTool(
            name="import_excel_source",
            description="Convert an Excel file to Markdown and write it to profile/profile.md.",
            input_schema={
                "type": "object",
                "required": ["source_path"],
                "properties": {
                    "source_path": {"type": "string"},
                    "project_dir": {"type": "string"},
                },
            },
            read_only=False,
            permission=ToolPermission.READ,
            handler=lambda input_data, context: _run_source2md(root, input_data, "excel2md.py"),
        ),
        FunctionTool(
            name="import_pptx_source",
            description="Convert a PowerPoint file to Markdown and write it to profile/profile.md.",
            input_schema={
                "type": "object",
                "required": ["source_path"],
                "properties": {
                    "source_path": {"type": "string"},
                    "project_dir": {"type": "string"},
                },
            },
            read_only=False,
            permission=ToolPermission.READ,
            handler=lambda input_data, context: _run_source2md(root, input_data, "ppt2md.py"),
        ),
        FunctionTool(
            name="import_url_source",
            description="Fetch a URL (web page) and write its Markdown conversion to profile/profile.md.",
            input_schema={
                "type": "object",
                "required": ["url"],
                "properties": {
                    "url": {"type": "string"},
                    "project_dir": {"type": "string"},
                },
            },
            read_only=False,
            permission=ToolPermission.NETWORK,
            handler=lambda input_data, context: _run_source2md(root, input_data, "web2md.py", url_field="url"),
        ),
    ]


def _run_source2md(
    repo_root: Path,
    input_data: Mapping[str, Any],
    script_name: str,
    url_field: str | None = None,
) -> ToolResult:
    project_dir = resolve_project_dir(repo_root, input_data)

    src_name = script_name.replace(".py", "")
    args = [f"source2md/{script_name}"]

    if url_field:
        url = str(input_data[url_field])
        args.extend([url, "-o"])
        out_md = project_dir / "profile" / "profile.md"
        args.append(str(out_md))
    else:
        source_path = str(input_data["source_path"])
        args.append(source_path)
        out_md = project_dir / "profile" / "profile.md"
        args.extend(["-o", str(out_md)])

    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "profile").mkdir(parents=True, exist_ok=True)

    result = run_script(repo_root, args)
    if not out_md.is_file():
        if result.stdout and Path(result.stdout.strip()).is_file():
            shutil.copy2(Path(result.stdout.strip()), out_md)
        else:
            out_md.write_text(
                f"# Imported via {src_name}\n\n"
                "Content could not be automatically extracted into Markdown. "
                "Please review the original file manually.\n",
                encoding="utf-8",
            )
    return script_result(f"import_{src_name}", result, {"profile_md": out_md})

