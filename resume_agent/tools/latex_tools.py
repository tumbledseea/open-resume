from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Mapping

from resume_agent.tools.base import FunctionTool, ToolExecutionError, ToolPermission, ToolResult
from resume_agent.tools.llm_runtime import complete_json
from resume_agent.tools.tool_runtime import resolve_path, run_script, script_result, scripts_dir


def create_latex_tools(repo_root: Path) -> list[FunctionTool]:
    root = Path(repo_root).resolve()
    return [
        FunctionTool(
            name="render_latex",
            description=(
                "Render latex/resume_modules.json -> latex/resume.tex using the Jinja2 renderer "
                "matching the template_id in resume_modules.json (default: red_card). "
                "Call this AFTER generate_resume_modules."
            ),
            input_schema={
                "type": "object",
                "required": ["project_dir"],
                "properties": {
                    "project_dir": {"type": "string"},
                    "template_id": {
                        "type": "string",
                        "description": "Override template (e.g. red_card, teal_clean, minimal_bw). Defaults to template_id in resume_modules.json.",
                    },
                    "repair_attempts": {"type": "integer"},
                    "one_page_attempts": {"type": "integer"},
                },
            },
            read_only=False,
            permission=ToolPermission.WORKSPACE_WRITE,
            handler=lambda input_data, context: _render_latex(root, input_data),
        ),
        FunctionTool(
            name="compile_pdf",
            description="Compile latex/resume.tex into exports/resume.pdf with XeLaTeX.",
            input_schema={
                "type": "object",
                "required": ["project_dir"],
                "properties": {"project_dir": {"type": "string"}},
            },
            read_only=False,
            permission=ToolPermission.EXPORT,
            handler=lambda input_data, context: _compile_pdf(root, input_data),
        ),
    ]


def _render_latex(repo_root: Path, input_data: Mapping[str, Any]) -> ToolResult:
    project_dir = resolve_path(repo_root, str(input_data["project_dir"]))
    modules_path = project_dir / "latex" / "resume_modules.json"
    if not modules_path.is_file():
        raise ToolExecutionError(f"resume_modules.json not found at {modules_path}. Call generate_resume_modules first.")

    # Determine template_id: explicit arg > resume_modules.json > default
    override_tid = str(input_data.get("template_id") or "").strip()
    if override_tid:
        template_id = override_tid
    else:
        try:
            modules_data = json.loads(modules_path.read_text(encoding="utf-8"))
            template_id = str(modules_data.get("template_id") or "red_card").strip()
        except Exception:
            template_id = "red_card"
    if not template_id:
        template_id = "red_card"

    renderers_dir = scripts_dir(repo_root).parent / "scripts" / "renderers"
    renderer_script = renderers_dir / f"render_{template_id}.py"
    if not renderer_script.is_file():
        # fallback to red_card if unknown template_id
        renderer_script = renderers_dir / "render_red_card.py"
        template_id = "red_card"

    tex_path = project_dir / "latex" / "resume.tex"
    result = run_script(
        repo_root,
        [
            str(renderer_script),
            "--modules",
            str(modules_path),
            "--output",
            str(tex_path),
        ],
    )
    return script_result(
        "render_latex",
        result,
        {
            "resume_tex": tex_path,
            "resume_cls": project_dir / "latex" / f"{template_id}.cls",
        },
    )


def _compile_pdf(repo_root: Path, input_data: Mapping[str, Any]) -> ToolResult:
    project_dir = resolve_path(repo_root, str(input_data["project_dir"]))
    repair_attempts = _non_negative_int(input_data.get("repair_attempts"), default=1)
    one_page_attempts = _non_negative_int(input_data.get("one_page_attempts"), default=1)
    repair_state: dict[str, Any] = {"attempted": False, "attempts": 0, "summaries": []}

    result = _run_pdf_with_latex_repair(repo_root, project_dir, repair_attempts, repair_state)
    one_page_state, result = _ensure_one_page(repo_root, project_dir, result, one_page_attempts)
    tool_result = script_result(
        "compile_pdf",
        result,
        {
            "resume_pdf": project_dir / "exports" / "resume.pdf",
            "resume_tex_export": project_dir / "exports" / "resume.tex",
            "export_quality": project_dir / "checks" / "export_quality.json",
        },
    )
    content = dict(tool_result.content)
    content["latex_repair"] = repair_state
    content["one_page"] = one_page_state
    return ToolResult(content=content, metadata=tool_result.metadata)


def _run_pdf_with_latex_repair(
    repo_root: Path,
    project_dir: Path,
    repair_attempts: int,
    repair_state: dict[str, Any],
) -> subprocess.CompletedProcess[str]:
    last_error: ToolExecutionError | None = None
    for attempt in range(repair_attempts + 1):
        try:
            return run_script(repo_root, ["render_pdf.py", "--project", str(project_dir)])
        except ToolExecutionError as exc:
            last_error = exc
            if attempt >= repair_attempts or not _repair_tex_after_compile_error(project_dir, str(exc), repair_state):
                raise
    raise last_error or ToolExecutionError("LaTeX compilation failed")


def _repair_tex_after_compile_error(project_dir: Path, error: str, repair_state: dict[str, Any]) -> bool:
    if complete_json is None or not _is_repairable_latex_error(project_dir, error):
        return False
    tex_path = project_dir / "latex" / "resume.tex"
    if not tex_path.is_file():
        return False
    current_tex = tex_path.read_text(encoding="utf-8-sig")
    log_excerpt = _latex_log_excerpt(project_dir)
    system = (
        "You are a LaTeX repair assistant for a resume template. "
        "Fix only syntax/escaping/template issues. Do not invent resume facts. Return JSON only."
    )
    user = (
        "LaTeX compilation failed.\n\nerror:\n"
        + error
        + "\n\nlog_excerpt:\n"
        + log_excerpt
        + "\n\ncurrent resume.tex:\n"
        + current_tex
        + '\n\nOutput format: {"resume_tex":"<full repaired tex>","summary":"<what changed>"}'
    )
    try:
        repaired = complete_json(system, user, temperature=0.1, retries=1)
    except Exception:
        return False
    repaired_tex = _tex_from_llm(repaired)
    if not repaired_tex:
        return False
    tex_path.write_text(repaired_tex.rstrip() + "\n", encoding="utf-8")
    repair_state["attempted"] = True
    repair_state["attempts"] = int(repair_state.get("attempts", 0)) + 1
    repair_state.setdefault("summaries", []).append(str(repaired.get("summary") or "Repaired LaTeX after compile error."))
    return True


def _ensure_one_page(
    repo_root: Path,
    project_dir: Path,
    result: subprocess.CompletedProcess[str],
    one_page_attempts: int,
) -> tuple[dict[str, Any], subprocess.CompletedProcess[str]]:
    pdf_path = project_dir / "exports" / "resume.pdf"
    page_count = _count_pdf_pages(pdf_path)
    state: dict[str, Any] = {
        "status": "pass" if 0 < page_count <= 1 else "fail",
        "initial_page_count": page_count,
        "page_count": page_count,
        "one_page": 0 < page_count <= 1,
        "compaction_attempted": False,
        "attempts": 0,
        "summaries": [],
    }
    if 0 < page_count <= 1:
        _write_export_quality(project_dir, page_count, "pass")
        return state, result

    for _ in range(one_page_attempts):
        if page_count <= 1:
            break
        if not _compact_tex_for_one_page(project_dir, page_count, state):
            break
        result = run_script(repo_root, ["render_pdf.py", "--project", str(project_dir)])
        page_count = _count_pdf_pages(pdf_path)
        state["page_count"] = page_count
        state["status"] = "pass" if 0 < page_count <= 1 else "fail"
        state["one_page"] = 0 < page_count <= 1
        if state["one_page"]:
            _write_export_quality(project_dir, page_count, "pass")
            return state, result

    _write_export_quality(project_dir, page_count, "fail", note="one-page gate failed")
    raise ToolExecutionError(f"one-page gate failed: compiled PDF has {page_count} pages")


def _compact_tex_for_one_page(project_dir: Path, page_count: int, state: dict[str, Any]) -> bool:
    if complete_json is None:
        return False
    tex_path = project_dir / "latex" / "resume.tex"
    if not tex_path.is_file():
        return False
    current_tex = tex_path.read_text(encoding="utf-8-sig")
    system = (
        "You are a one-page resume compaction assistant. "
        "Shorten or tighten only the LaTeX resume content while preserving truthful facts. Return JSON only."
    )
    user = (
        f"The compiled resume is {page_count} pages, but the target is one-page A4.\n\n"
        "Current resume.tex:\n"
        + current_tex
        + '\n\nOutput format: {"resume_tex":"<full compacted tex>","summary":"<what changed>"}'
    )
    try:
        compacted = complete_json(system, user, temperature=0.1, retries=1)
    except Exception:
        return False
    compacted_tex = _tex_from_llm(compacted)
    if not compacted_tex:
        return False
    tex_path.write_text(compacted_tex.rstrip() + "\n", encoding="utf-8")
    state["compaction_attempted"] = True
    state["attempts"] = int(state.get("attempts", 0)) + 1
    state.setdefault("summaries", []).append(str(compacted.get("summary") or "Compacted LaTeX for one page."))
    return True


def _count_pdf_pages(pdf_path: Path) -> int:
    if not pdf_path.is_file():
        return 0
    try:
        import fitz  # type: ignore

        with fitz.open(pdf_path) as doc:
            return int(doc.page_count)
    except Exception:
        pass
    try:
        result = subprocess.run(["pdfinfo", str(pdf_path)], capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if line.startswith("Pages:"):
                    return int(line.split(":", 1)[1].strip())
    except Exception:
        pass
    try:
        raw = pdf_path.read_bytes()
        return raw.count(b"/Type /Page") - raw.count(b"/Type /Pages")
    except Exception:
        return 0


def _write_export_quality(project_dir: Path, page_count: int, status: str, note: str = "") -> None:
    report = {
        "gates": {
            "export": {
                "status": status,
                "pdf": str((project_dir / "exports" / "resume.pdf").resolve()),
                "backend": "xelatex",
                "page_count": page_count,
                "one_page": status == "pass" and page_count <= 1,
            }
        }
    }
    if note:
        report["gates"]["export"]["note"] = note
    report_path = project_dir / "checks" / "export_quality.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _is_repairable_latex_error(project_dir: Path, error: str) -> bool:
    if _latex_log_excerpt(project_dir):
        return True
    markers = ("undefined control sequence", "latex error", "emergency stop", "missing", "! ")
    lowered = error.lower()
    return any(marker in lowered for marker in markers)


def _latex_log_excerpt(project_dir: Path) -> str:
    candidates = [
        project_dir / "exports" / "resume.log",
        project_dir / "latex" / "resume.log",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        critical = [line for line in lines if line.startswith("!") or "LaTeX Error" in line]
        selected = critical[-20:] if critical else lines[-40:]
        return "\n".join(selected)
    return ""


def _tex_from_llm(value: Any) -> str:
    if not isinstance(value, Mapping):
        return ""
    raw = value.get("resume_tex") or value.get("tex") or value.get("latex")
    if not isinstance(raw, str):
        return ""
    text = raw.strip()
    return text if "\\begin" in text and "\\end" in text else ""


def _non_negative_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, parsed)
