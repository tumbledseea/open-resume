from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Mapping

from resume_agent.artifacts.store import (
    diff_artifact,
    snapshot_artifacts,
)
from resume_agent.schema.resume_modules import (
    ResumeModulesValidationError,
    validate_resume_modules,
)
from resume_agent.tools.base import (
    FunctionTool,
    ToolContext,
    ToolExecutionError,
    ToolPermission,
    ToolResult,
)
from resume_agent.tools.llm_runtime import complete_json
from resume_agent.tools.tool_runtime import resolve_path


def create_resume_tools(repo_root: Path) -> list[FunctionTool]:
    root = Path(repo_root).resolve()
    return [
        FunctionTool(
            name="generate_resume_modules",
            description=(
                "Generate resume content from profile + JD analysis + strategy. "
                "Reads profile/profile.json, jd/jd_analysis.md, strategy/spec_lock.json "
                "and calls AI to produce latex/resume_modules.json (structured data) "
                "and drafts/resume.md (editable Markdown). "
                "Call this AFTER normalize_profile, analyze_jd, and build_resume_strategy."
            ),
            input_schema={"type": "object", "properties": {}},
            read_only=False,
            permission=ToolPermission.WORKSPACE_WRITE,
            handler=lambda input_data, context: _generate_resume_modules(root, context),
        ),
    ]


def _generate_resume_modules(repo_root: Path, context: ToolContext) -> ToolResult:
    project_dir_str = context.metadata.get("project_dir", "")
    if not project_dir_str:
        raise ToolExecutionError("generate_resume_modules requires project_dir in context metadata")
    project_dir = resolve_path(repo_root, project_dir_str)

    profile_path = project_dir / "profile" / "profile.json"
    jd_analysis_path = project_dir / "jd" / "jd_analysis.md"
    spec_path = project_dir / "strategy" / "spec_lock.json"

    if not profile_path.is_file():
        raise ToolExecutionError(f"profile.json not found at {profile_path}. Call normalize_profile first.")
    if not jd_analysis_path.is_file():
        raise ToolExecutionError(f"jd_analysis.md not found at {jd_analysis_path}. Call analyze_jd first.")

    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    jd_analysis = jd_analysis_path.read_text(encoding="utf-8-sig")

    keywords = ""
    if spec_path.is_file():
        spec = json.loads(spec_path.read_text(encoding="utf-8-sig"))
        keywords = ", ".join(spec.get("priority_keywords", []))

    if complete_json is None:
        raise ToolExecutionError("LLM client unavailable for resume generation")

    system = (
        "你是简历撰写专家。根据候选人画像和岗位JD，生成一页A4中文简历。\n\n"
        "输出JSON对象，包含两个字段：\n"
        '1. "resume_md": 纯文本Markdown简历\n'
        '2. "resume_modules": 结构化数据，用于template1 LaTeX渲染\n\n'
        "规则：\n"
        "- 只使用profile中明确存在的事实，绝不编造\n"
        "- 突出与JD关键词相关的经历\n"
        "- 每条经历用bullet point，结果导向，量化成果\n"
        "- 控制在一页A4以内\n"
        "- 语言：中文\n\n"
        "resume_modules需遵循template1格式：\n"
        "- header: {name, phone, email, location, photo('')}\n"
        "- modules: 数组，每项{module_id, title, items[]}\n"
        "  - education: {school, badges[], time, major, degree, college, study_type, location, details[]}\n"
        "  - experience: {organization, time, role, project, bullets[{label, text}]}\n"
        "  - projects: {name, role, time, bullets[字符串]}\n"
        "  - awards: {name, time}\n"
        "- quality_constraints: {page_limit: 1, max_experience_bullets: 3, max_project_bullets: 3, max_awards: 5}"
    )
    if keywords:
        system += "\n\nJD关键词：" + keywords

    user = (
        "候选人画像：\n" + json.dumps(profile, ensure_ascii=False, indent=2)
        + "\n\nJD分析：\n" + jd_analysis
    )

    try:
        result = complete_json(system, user, temperature=0.3, retries=2)
    except Exception as exc:
        raise ToolExecutionError(f"LLM resume generation failed: {exc}") from exc

    resume_md = _resume_md(result)
    modules = _resume_modules(result)
    modules.setdefault("template_id", "template1")
    modules.setdefault("language", "zh-CN")

    try:
        validate_resume_modules(repo_root, modules)
    except ResumeModulesValidationError as exc:
        repaired = _repair_resume_modules(
            original_result=result,
            validation_error=exc,
            profile=profile,
            jd_analysis=jd_analysis,
            keywords=keywords,
        )
        resume_md = _resume_md(repaired, fallback=resume_md)
        modules = _resume_modules(repaired)
        modules.setdefault("template_id", "template1")
        modules.setdefault("language", "zh-CN")
        try:
            validate_resume_modules(repo_root, modules)
        except ResumeModulesValidationError as repair_exc:
            raise ToolExecutionError(
                "resume_modules schema validation failed after repair: "
                + str(repair_exc)
            ) from repair_exc

    resume_md_path = project_dir / "drafts" / "resume.md"
    modules_path = project_dir / "latex" / "resume_modules.json"
    existing_outputs = [
        relative
        for relative, path in (
            ("drafts/resume.md", resume_md_path),
            ("latex/resume_modules.json", modules_path),
        )
        if path.is_file()
    ]
    snapshot = None
    if existing_outputs:
        snapshot = snapshot_artifacts(
            project_dir=project_dir,
            paths=existing_outputs,
            reason="before generate_resume_modules",
        )

    drafts_dir = project_dir / "drafts"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    resume_md_path.write_text(resume_md, encoding="utf-8")

    exports_dir = project_dir / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(resume_md_path, exports_dir / "resume.md")

    latex_dir = project_dir / "latex"
    latex_dir.mkdir(parents=True, exist_ok=True)
    modules_path.write_text(json.dumps(modules, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    snapshot_payload = None
    diffs: list[dict[str, Any]] = []
    if snapshot is not None:
        snapshot_payload = {
            "version_id": snapshot.version_id,
            "metadata": str(snapshot.metadata_path.resolve()),
            "files": list(snapshot.files),
        }
        diffs = [
            diff_artifact(project_dir, snapshot.version_id, relative)
            for relative in existing_outputs
        ]

    return ToolResult(
        content={
            "status": "ok",
            "tool": "generate_resume_modules",
            "outputs": {
                "resume_modules": str(modules_path.resolve()),
                "resume_md": str(resume_md_path.resolve()),
            },
            "snapshot": snapshot_payload,
            "diffs": diffs,
        }
    )


def _resume_md(result: Any, fallback: str = "") -> str:
    if not isinstance(result, Mapping):
        return fallback
    value = result.get("resume_md", fallback)
    return value if isinstance(value, str) else str(value)


def _resume_modules(result: Any) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        raise ToolExecutionError("LLM resume generation must return a JSON object")

    modules = result.get("resume_modules")
    if modules is None and {"template_id", "modules"}.issubset(result.keys()):
        modules = result
    if not isinstance(modules, Mapping):
        raise ToolExecutionError("LLM resume generation must return resume_modules as an object")
    return dict(modules)


def _repair_resume_modules(
    original_result: Any,
    validation_error: ResumeModulesValidationError,
    profile: Mapping[str, Any],
    jd_analysis: str,
    keywords: str,
) -> Mapping[str, Any]:
    repair_system = (
        "你是 resume_modules JSON 修复器。修复给定 JSON，使其严格符合 "
        "template1 resume_modules schema，并保留原始简历事实。"
        "只输出 JSON 对象，字段包含 resume_md 和 resume_modules。"
    )
    repair_user = (
        "schema validation errors:\n"
        + "\n".join(f"- {message}" for message in validation_error.messages)
        + "\n\nrequired template1 modules: education, experience, projects, awards"
        + "\n\ncandidate profile:\n"
        + json.dumps(profile, ensure_ascii=False, indent=2)
        + "\n\nJD analysis:\n"
        + jd_analysis
        + ("\n\nJD keywords:\n" + keywords if keywords else "")
        + "\n\ninvalid model output:\n"
        + json.dumps(original_result, ensure_ascii=False, indent=2)
    )
    try:
        repaired = complete_json(repair_system, repair_user, temperature=0, retries=1)
    except Exception as exc:
        raise ToolExecutionError(f"LLM resume_modules repair failed: {exc}") from exc
    if not isinstance(repaired, Mapping):
        raise ToolExecutionError("LLM resume_modules repair must return a JSON object")
    return repaired
