from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from resume_agent.tools.base import FunctionTool, ToolExecutionError, ToolPermission, ToolResult
from resume_agent.tools.tool_runtime import resolve_path


def create_quality_tools(repo_root: Path) -> list[FunctionTool]:
    root = Path(repo_root).resolve()
    return [
        FunctionTool(
            name="check_truthfulness",
            description=(
                "Check resume content for empty/placeholder fields. "
                "Scans latex/resume_modules.json for empty strings and drafts/resume.md for XX markers."
            ),
            input_schema={
                "type": "object",
                "required": ["project_dir"],
                "properties": {"project_dir": {"type": "string"}},
            },
            read_only=False,
            permission=ToolPermission.WORKSPACE_WRITE,
            handler=lambda input_data, context: _check_truthfulness(root, input_data),
        ),
        FunctionTool(
            name="check_ats",
            description="Check JD keyword coverage in latex/resume.tex.",
            input_schema={
                "type": "object",
                "required": ["project_dir"],
                "properties": {"project_dir": {"type": "string"}},
            },
            read_only=False,
            permission=ToolPermission.WORKSPACE_WRITE,
            handler=lambda input_data, context: _check_ats(root, input_data),
        ),
    ]


def _check_truthfulness(repo_root: Path, input_data: Mapping[str, Any]) -> ToolResult:
    project_dir = resolve_path(repo_root, str(input_data["project_dir"]))
    modules_path = project_dir / "latex" / "resume_modules.json"
    resume_md_path = project_dir / "drafts" / "resume.md"

    findings: list[str] = []

    if modules_path.is_file():
        try:
            modules = json.loads(modules_path.read_text(encoding="utf-8-sig"))
            empty_fields = _find_empty_values(modules)
            if empty_fields:
                findings.append(f"Empty fields in resume_modules.json: {', '.join(empty_fields[:10])}")
        except (json.JSONDecodeError, OSError) as exc:
            findings.append(f"Cannot read resume_modules.json: {exc}")

    if resume_md_path.is_file():
        content = resume_md_path.read_text(encoding="utf-8-sig")
        xx_markers = sorted(set(re.findall(r"\bXX\b", content)))
        if xx_markers:
            findings.append(f"Unresolved XX placeholders in resume.md: {len(xx_markers)} found")

    report = {
        "status": "pass" if not findings else "warn",
        "findings": findings,
        "notes": [] if not findings else findings,
    }
    report_path = project_dir / "checks" / "truthfulness_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return ToolResult(content={"status": report["status"], "outputs": {"truthfulness_report": str(report_path)}})


def _find_empty_values(obj: Any, path: str = "") -> list[str]:
    empty: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "quality_constraints":
                continue
            child = f"{path}.{key}" if path else key
            empty.extend(_find_empty_values(value, child))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            empty.extend(_find_empty_values(item, f"{path}[{i}]"))
    elif isinstance(obj, str) and obj == "":
        empty.append(path)
    return empty


def _check_ats(repo_root: Path, input_data: Mapping[str, Any]) -> ToolResult:
    project_dir = resolve_path(repo_root, str(input_data["project_dir"]))
    tex_path = project_dir / "latex" / "resume.tex"
    spec_lock = project_dir / "strategy" / "spec_lock.json"
    if not tex_path.is_file():
        raise ToolExecutionError(f"missing LaTeX resume: {tex_path}")
    resume_text = tex_path.read_text(encoding="utf-8-sig").lower()
    keywords: list[str] = []
    if spec_lock.is_file():
        try:
            data = json.loads(spec_lock.read_text(encoding="utf-8-sig"))
            raw_keywords = data.get("priority_keywords", [])
            if isinstance(raw_keywords, list):
                keywords = [str(item) for item in raw_keywords]
        except json.JSONDecodeError:
            keywords = []
    covered = [kw for kw in keywords if kw.lower() in resume_text]
    missing = [kw for kw in keywords if kw.lower() not in resume_text]
    report = {
        "status": "pass" if not missing else "warn",
        "covered_keywords": covered,
        "missing_keywords": missing,
    }
    report_path = project_dir / "checks" / "ats_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return ToolResult(content={"status": report["status"], "outputs": {"ats_report": str(report_path)}})

