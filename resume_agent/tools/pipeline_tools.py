"""Pipeline preflight and resolve_target_job tools."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Mapping

from resume_agent.tools.base import FunctionTool, ToolExecutionError, ToolPermission, ToolResult
from resume_agent.tools.tool_runtime import resolve_path

# Late imports to avoid circular dependencies — accessed via module reference so monkeypatch works
import resume_agent.tools.jd_tools as _jd_tools
import resume_agent.tools.job_hunt_tools as _job_hunt_tools


def create_pipeline_tools(repo_root: Path) -> list[FunctionTool]:
    root = Path(repo_root).resolve()
    return [
        FunctionTool(
            name="pipeline_preflight",
            description=(
                "Check all preconditions before starting the resume generation pipeline. "
                "Validates profile file, JD source, LLM config, network permission, "
                "and output directory writability. Returns status=ok or status=needs_user_input."
            ),
            input_schema={
                "type": "object",
                "required": ["project_dir"],
                "properties": {
                    "project_dir": {"type": "string"},
                    "profile_file": {"type": "string"},
                    "jd_text": {"type": "string"},
                    "jd_url": {"type": "string"},
                    "search_query": {"type": "string"},
                    "company": {"type": "string"},
                    "role": {"type": "string"},
                    "allow_network": {"type": "boolean"},
                    "compile_pdf": {"type": "boolean"},
                },
            },
            read_only=True,
            permission=ToolPermission.READ,
            handler=lambda input_data, context: _pipeline_preflight(root, input_data),
        ),
        FunctionTool(
            name="resolve_target_job",
            description=(
                "Unified entry point to get a JD into jd/jd_raw.md. "
                "Accepts jd_text (direct paste), jd_url (crawl), or search_query/company/role (search then crawl). "
                "Returns status=ok with selected job info, or status=needs_user_input if search returns multiple ambiguous results."
            ),
            input_schema={
                "type": "object",
                "required": ["project_dir"],
                "properties": {
                    "project_dir": {"type": "string"},
                    "jd_text": {"type": "string"},
                    "jd_url": {"type": "string"},
                    "search_query": {"type": "string"},
                    "company": {"type": "string"},
                    "role": {"type": "string"},
                    "location": {"type": "string"},
                    "auto_select": {
                        "type": "boolean",
                        "description": "Auto-select top search result instead of asking user (default false)",
                    },
                    "enable_boss": {"type": "boolean"},
                },
            },
            read_only=False,
            permission=ToolPermission.WORKSPACE_WRITE,
            handler=lambda input_data, context: _resolve_target_job(root, input_data),
        ),
    ]


# ── pipeline_preflight ────────────────────────────────────────────────────────

def _pipeline_preflight(repo_root: Path, input_data: Mapping[str, Any]) -> ToolResult:
    project_dir = resolve_path(repo_root, str(input_data["project_dir"]))
    profile_file = str(input_data.get("profile_file") or "").strip()
    jd_text = str(input_data.get("jd_text") or "").strip()
    jd_url = str(input_data.get("jd_url") or "").strip()
    search_query = str(input_data.get("search_query") or "").strip()
    company = str(input_data.get("company") or "").strip()
    role = str(input_data.get("role") or "").strip()
    allow_network = bool(input_data.get("allow_network", False))
    compile_pdf = bool(input_data.get("compile_pdf", True))

    issues: list[str] = []
    warnings: list[str] = []
    checks: dict[str, str] = {}

    # 1. project_dir writable
    try:
        project_dir.mkdir(parents=True, exist_ok=True)
        test_file = project_dir / ".preflight_write_test"
        test_file.write_text("ok")
        test_file.unlink()
        checks["project_dir"] = "ok"
    except OSError as exc:
        issues.append(f"project_dir not writable: {exc}")
        checks["project_dir"] = "error"

    # 2. profile_file
    if profile_file:
        pf = Path(profile_file)
        if not pf.is_absolute():
            pf = repo_root / pf
        if not pf.is_file():
            issues.append(f"profile_file not found: {pf}")
            checks["profile_file"] = "missing"
        elif pf.stat().st_size == 0:
            issues.append(f"profile_file is empty: {pf}")
            checks["profile_file"] = "empty"
        else:
            checks["profile_file"] = "ok"
    else:
        # Check if profile already exists in project_dir
        existing = project_dir / "profile" / "profile.json"
        if existing.is_file():
            checks["profile_file"] = "already_imported"
        else:
            issues.append("No profile_file provided and no existing profile/profile.json found")
            checks["profile_file"] = "missing"

    # 3. JD source
    has_jd_text = bool(jd_text)
    has_jd_url = bool(jd_url)
    has_search = bool(search_query or company or role)
    existing_jd = (project_dir / "jd" / "jd_raw.md").is_file()

    if has_jd_text or has_jd_url or existing_jd:
        checks["jd_source"] = "ok"
    elif has_search:
        if not allow_network:
            issues.append("search_query/company/role provided but allow_network=False — cannot search without network")
            checks["jd_source"] = "needs_network"
        else:
            checks["jd_source"] = "search_required"
    else:
        issues.append("No JD source: provide jd_text, jd_url, or search_query/company/role")
        checks["jd_source"] = "missing"

    # 4. Network permission
    if allow_network:
        checks["network"] = "allowed"
    else:
        checks["network"] = "disabled"
        if has_jd_url:
            issues.append("jd_url provided but allow_network=False — set allow_network=true to fetch")

    # 5. LLM config
    llm_key = (
        os.environ.get("OPENAI_API_KEY")
        or os.environ.get("API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
        or ""
    ).strip()
    if llm_key:
        checks["llm"] = "configured"
    else:
        warnings.append("No LLM API key found — LLM-dependent tools (analyze_jd, generate_resume_modules) will fail")
        checks["llm"] = "missing"

    # 6. LaTeX (for compile_pdf)
    if compile_pdf:
        xelatex = shutil.which("xelatex") or shutil.which("pdflatex") or shutil.which("latexmk")
        if xelatex:
            checks["latex"] = "available"
        else:
            warnings.append("xelatex not found — compile_pdf will be skipped or fail")
            checks["latex"] = "unavailable"
    else:
        checks["latex"] = "skipped"

    status = "needs_user_input" if issues else "ok"
    return ToolResult(content={
        "status": status,
        "tool": "pipeline_preflight",
        "checks": checks,
        "issues": issues,
        "warnings": warnings,
        "ready": not issues,
    })


# ── resolve_target_job ────────────────────────────────────────────────────────

def _resolve_target_job(repo_root: Path, input_data: Mapping[str, Any]) -> ToolResult:
    project_dir = resolve_path(repo_root, str(input_data["project_dir"]))
    jd_text = str(input_data.get("jd_text") or "").strip()
    jd_url = str(input_data.get("jd_url") or "").strip()
    search_query = str(input_data.get("search_query") or "").strip()
    company = str(input_data.get("company") or "").strip()
    role = str(input_data.get("role") or "").strip()
    location = str(input_data.get("location") or "").strip()
    auto_select = bool(input_data.get("auto_select", False))
    enable_boss = bool(input_data.get("enable_boss", False))

    # Path 1: direct JD text
    if jd_text:
        return _resolve_from_text(repo_root, project_dir, jd_text, company, role)

    # Path 2: direct JD URL
    if jd_url:
        return _resolve_from_url(repo_root, project_dir, jd_url, company, role, enable_boss)

    # Path 3: search then crawl
    query = search_query or " ".join(filter(None, [role, company])).strip()
    if query:
        return _resolve_from_search(
            repo_root, project_dir, query, company, role, location,
            auto_select=auto_select, enable_boss=enable_boss,
        )

    raise ToolExecutionError(
        "resolve_target_job requires at least one of: jd_text, jd_url, search_query, or company+role"
    )


def _resolve_from_text(
    repo_root: Path, project_dir: Path, jd_text: str, company: str, role: str
) -> ToolResult:
    result = _jd_tools._add_jd_text(repo_root, {
        "project_dir": str(project_dir),
        "company": company or "Unknown",
        "role": role or "Unknown Role",
        "text": jd_text,
    })
    return ToolResult(content={
        "status": "ok",
        "tool": "resolve_target_job",
        "source": "jd_text",
        "company": company,
        "role": role,
        "outputs": result.content.get("outputs", {}),
    })


def _resolve_from_url(
    repo_root: Path, project_dir: Path, jd_url: str, company: str, role: str, enable_boss: bool
) -> ToolResult:
    try:
        result = _job_hunt_tools._crawl_job_info(repo_root, {
            "project_dir": str(project_dir),
            "url": jd_url,
            "company": company,
            "role": role,
            "enable_boss": enable_boss,
        })
        return ToolResult(content={
            "status": "ok",
            "tool": "resolve_target_job",
            "source": "jd_url",
            "company": result.content.get("company", company),
            "role": result.content.get("role", role),
            "job_id": result.content.get("job_id", ""),
            "outputs": result.content.get("outputs", {}),
        })
    except ToolExecutionError:
        # Fallback: fetch_jd_url (simpler, no job index)
        result = _jd_tools._fetch_jd_url(repo_root, {
            "project_dir": str(project_dir),
            "url": jd_url,
            "company": company or "Unknown",
            "role": role or "Unknown Role",
        })
        return ToolResult(content={
            "status": "ok",
            "tool": "resolve_target_job",
            "source": "jd_url_fallback",
            "company": company,
            "role": role,
            "outputs": result.content.get("outputs", {}),
        })


def _resolve_from_search(
    repo_root: Path,
    project_dir: Path,
    query: str,
    company: str,
    role: str,
    location: str,
    *,
    auto_select: bool,
    enable_boss: bool,
) -> ToolResult:
    # Step 1: search
    search_result = _job_hunt_tools._search_jobs(repo_root, {
        "project_dir": str(project_dir),
        "query": query,
        "location": location,
        "limit": 10,
        "enable_boss": enable_boss,
    })
    jobs_path = Path(search_result.content["outputs"]["jobs_index"])
    jobs = [json.loads(line) for line in jobs_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    if not jobs:
        raise ToolExecutionError(f"search_jobs returned no results for query: {query!r}")

    # Filter by company if provided
    if company:
        company_lower = company.casefold()
        company_matches = [j for j in jobs if company_lower in str(j.get("company", "")).casefold()]
        if company_matches:
            jobs = company_matches

    # If exactly 1 candidate or auto_select: pick top result and crawl
    top = jobs[0]
    if len(jobs) == 1 or auto_select:
        return _crawl_top_result(repo_root, project_dir, top, enable_boss)

    # Multiple results: ask user to choose unless top result is clearly dominant
    top_score = int(top.get("match_score", 0))
    second_score = int(jobs[1].get("match_score", 0)) if len(jobs) > 1 else 0
    if top_score > 0 and top_score >= second_score + 20:
        # Clear winner — auto-select
        return _crawl_top_result(repo_root, project_dir, top, enable_boss)

    # Ambiguous — surface candidates and ask user to choose
    candidates = [
        {
            "job_id": j.get("job_id", ""),
            "company": j.get("company", ""),
            "role": j.get("role", ""),
            "platform": j.get("platform", ""),
            "salary": j.get("salary", ""),
            "location": j.get("location", ""),
            "match_score": j.get("match_score", 0),
            "jd_url": j.get("jd_url", ""),
        }
        for j in jobs[:5]
    ]
    return ToolResult(content={
        "status": "needs_user_input",
        "tool": "resolve_target_job",
        "source": "search",
        "message": (
            f"Found {len(jobs)} job postings for {query!r}. "
            "Please select one by calling resolve_target_job again with jd_url, "
            "or call select_job with job_id and then crawl_job_info."
        ),
        "candidates": candidates,
    })


def _crawl_top_result(
    repo_root: Path, project_dir: Path, job: dict[str, Any], enable_boss: bool
) -> ToolResult:
    jd_url = str(job.get("jd_url") or "")
    job_id = str(job.get("job_id") or "")

    if not jd_url and not job_id:
        # No URL to crawl — write what we have from search snippet
        jd_text = str(job.get("jd_text") or job.get("source_raw") or "")
        if not jd_text:
            raise ToolExecutionError("Top search result has no JD text or URL to crawl")
        result = _jd_tools._add_jd_text(repo_root, {
            "project_dir": str(project_dir),
            "company": str(job.get("company") or "Unknown"),
            "role": str(job.get("role") or "Unknown Role"),
            "text": jd_text,
        })
        return ToolResult(content={
            "status": "ok",
            "tool": "resolve_target_job",
            "source": "search_snippet",
            "company": str(job.get("company", "")),
            "role": str(job.get("role", "")),
            "job_id": job_id,
            "outputs": result.content.get("outputs", {}),
        })

    crawl_input: dict[str, Any] = {
        "project_dir": str(project_dir),
        "enable_boss": enable_boss,
    }
    if jd_url:
        crawl_input["url"] = jd_url
    if job_id:
        crawl_input["job_id"] = job_id

    result = _job_hunt_tools._crawl_job_info(repo_root, crawl_input)
    return ToolResult(content={
        "status": "ok",
        "tool": "resolve_target_job",
        "source": "search_crawl",
        "company": result.content.get("company", str(job.get("company", ""))),
        "role": result.content.get("role", str(job.get("role", ""))),
        "job_id": result.content.get("job_id", job_id),
        "outputs": result.content.get("outputs", {}),
    })
