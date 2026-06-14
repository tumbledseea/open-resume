from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from resume_agent.engine.intent_router import RoutedIntent
from resume_agent.engine.state import ResumeSessionState
from resume_agent.tools.base import ToolContext, ToolPermission
from resume_agent.tools.registry import ToolRegistry


@dataclass(frozen=True)
class ContextPack:
    data: dict[str, Any]
    tool_context: ToolContext


def build_context_pack(
    message: str,
    state: ResumeSessionState,
    intent: RoutedIntent,
    registry: ToolRegistry,
    allowed_permissions: set[ToolPermission],
    profile_content: str = "",
) -> ContextPack:
    """Build the context pack for a single engine turn.

    The context pack holds two layers:
    - ``data`` — shipped to the LLM as part of the user message (dynamic).
    - ``tool_context`` — injected into every tool's ``handler(input_data, context)``
      so tools never rely on the LLM to supply paths.
    """
    static_section = ""
    if profile_content:
        static_section = (
            "[Static Context — User Profile Content]\n"
            "This is the user's uploaded profile file. "
            "It is the ONLY source of truth for the candidate's background. "
            "Do not invent facts not present here.\n"
            + profile_content
        )

    project_dir_str = str(state.project_dir)
    profile_file_str = str(state.profile_file) if state.profile_file else ""

    return ContextPack(
        data={
            "message": message,
            "intent": intent.name,
            "stage": state.stage.value,
            "project_dir": project_dir_str,
            "profile_file": profile_file_str,
            "company": state.company,
            "role": state.role,
            "available_tools": [tool.name for tool in registry.available_tools(allowed_permissions)],
            "artifact_state": _build_artifact_state(state.project_dir),
            "static_context": static_section,
            "rules": [
                "Do not invent resume facts that are not in the static context.",
                "Write artifacts to the project workspace.",
                "Pipeline order: import_profile → normalize_profile → add_jd_text/analyze_jd "
                "→ build_resume_strategy → generate_resume_modules → render_latex → compile_pdf.",
                "generate_resume_modules writes BOTH drafts/resume.md (editable Markdown) "
                "AND latex/resume_modules.json (structured data for template1 renderer).",
                "render_latex converts resume_modules.json → resume.tex using template1 Jinja2 renderer. "
                "Do NOT write LaTeX directly.",
                "For resume revisions, prefer revise_resume_from_match_report when checks/match_report.json exists; "
                "otherwise use read_resume_section + revise_resume_section. Section edits snapshot "
                "latex/resume_modules.json and return a diff for review.",
                "For match scoring, use match_analysis with use_semantic_alignment=true when the user asks "
                "for JD-resume fit, semantic alignment, or role adaptation. Use compare_match_reports after "
                "a new match report if the user wants before/after improvement.",
                "For job hunt, use search_jobs to build jobs/jobs.jsonl first. If a job needs full detail, "
                "use crawl_job_info with url or job_id to fetch the posting and write jd/jd_raw.md. "
                "When the user chooses a role from the existing index, use select_job to write "
                "jobs/selected_job.json and jd/jd_raw.md for the downstream JD pipeline.",
                "ONE-PAGE RULE: The final resume PDF MUST fit on exactly one A4 page at 10pt font. "
                "Keep content concise; use compact bullet points; prioritize relevance over quantity.",
                "Your project directory is fixed at: " + project_dir_str,
                "Your profile file (if provided) is fixed at: " + profile_file_str,
            ],
        },
        tool_context=ToolContext(
            workspace=Path(state.project_dir),
            metadata={
                "project_dir": project_dir_str,
                "profile_file": profile_file_str,
                "allow_network": ToolPermission.NETWORK in allowed_permissions,
            },
        ),
    )


def _build_artifact_state(project_dir: Path) -> dict[str, dict[str, Any]]:
    artifacts = {
        "profile_md": "profile/profile.md",
        "profile_json": "profile/profile.json",
        "fact_index": "profile/fact_index.json",
        "jobs_index": "jobs/jobs.jsonl",
        "job_details": "jobs/job_details",
        "selected_job": "jobs/selected_job.json",
        "jd_raw": "jd/jd_raw.md",
        "jd_analysis": "jd/jd_analysis.md",
        "resume_strategy": "strategy/resume_strategy.md",
        "spec_lock": "strategy/spec_lock.json",
        "resume_md": "drafts/resume.md",
        "resume_modules": "latex/resume_modules.json",
        "resume_tex": "latex/resume.tex",
        "template_class": "latex/template1.cls",
        "resume_pdf": "exports/resume.pdf",
        "truthfulness_report": "checks/truthfulness_report.json",
        "ats_report": "checks/ats_report.json",
        "match_report": "checks/match_report.json",
        "match_trend": "checks/match_trend.json",
        "export_quality": "checks/export_quality.json",
        "state": "state.json",
    }
    state: dict[str, dict[str, Any]] = {}
    for name, relative in artifacts.items():
        path = project_dir / relative
        exists = path.exists() if name == "job_details" else path.is_file()
        state[name] = {
            "exists": exists,
            "path": str(path.resolve()),
            "size": path.stat().st_size if exists and path.is_file() else 0,
        }
    state["versions"] = _build_versions_state(project_dir)
    return state


def _build_versions_state(project_dir: Path) -> dict[str, Any]:
    versions_dir = project_dir / "versions"
    metadata_paths = sorted(versions_dir.glob("*/metadata.json")) if versions_dir.is_dir() else []
    latest = metadata_paths[-1] if metadata_paths else None
    return {
        "exists": versions_dir.is_dir(),
        "path": str(versions_dir.resolve()),
        "count": len(metadata_paths),
        "latest_version_id": latest.parent.name if latest else "",
        "latest_metadata": str(latest.resolve()) if latest else "",
    }
