from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping

from resume_agent.artifacts.store import diff_artifact, snapshot_artifacts
from resume_agent.schema.resume_modules import ResumeModulesValidationError, validate_resume_modules
from resume_agent.tools.base import FunctionTool, ToolExecutionError, ToolPermission, ToolResult
from resume_agent.tools.llm_runtime import complete_json
from resume_agent.tools.tool_runtime import resolve_path


SECTION_MODULE_IDS = {"summary", "education", "experience", "projects", "awards", "skills", "certifications"}


def create_resume_section_tools(repo_root: Path) -> list[FunctionTool]:
    root = Path(repo_root).resolve()
    return [
        FunctionTool(
            name="read_resume_section",
            description="Read one section from latex/resume_modules.json without modifying artifacts.",
            input_schema={
                "type": "object",
                "required": ["project_dir", "section"],
                "properties": {
                    "project_dir": {"type": "string"},
                    "section": {"type": "string"},
                },
            },
            read_only=True,
            permission=ToolPermission.READ,
            handler=lambda input_data, context: _read_resume_section(root, input_data),
        ),
        FunctionTool(
            name="write_resume_section",
            description=(
                "Replace one section in latex/resume_modules.json. "
                "Snapshots the previous file, validates schema, writes the new modules, and returns a diff."
            ),
            input_schema={
                "type": "object",
                "required": ["project_dir", "section", "content"],
                "properties": {
                    "project_dir": {"type": "string"},
                    "section": {"type": "string"},
                    "content": {"type": "object"},
                },
            },
            read_only=False,
            permission=ToolPermission.WORKSPACE_WRITE,
            handler=lambda input_data, context: _write_resume_section(root, input_data),
        ),
        FunctionTool(
            name="revise_resume_section",
            description=(
                "Use AI to revise only one resume section in latex/resume_modules.json. "
                "Snapshots the previous file, validates schema, writes the revised section, and returns a diff."
            ),
            input_schema={
                "type": "object",
                "required": ["project_dir", "section", "instruction"],
                "properties": {
                    "project_dir": {"type": "string"},
                    "section": {"type": "string"},
                    "instruction": {"type": "string"},
                },
            },
            read_only=False,
            permission=ToolPermission.WORKSPACE_WRITE,
            handler=lambda input_data, context: _revise_resume_section(root, input_data),
        ),
        FunctionTool(
            name="revise_resume_from_match_report",
            description=(
                "Use checks/match_report.json to choose the weakest resume section, then revise only "
                "that section with AI. Snapshots, validates, writes, and returns a diff."
            ),
            input_schema={
                "type": "object",
                "required": ["project_dir"],
                "properties": {
                    "project_dir": {"type": "string"},
                    "instruction": {
                        "type": "string",
                        "description": (
                            "Optional guidance for the rewrite. If omitted, a default instruction "
                            "is derived from the match_report's missing keywords and gaps."
                        ),
                    },
                    "section": {"type": "string"},
                },
            },
            read_only=False,
            permission=ToolPermission.WORKSPACE_WRITE,
            handler=lambda input_data, context: _revise_resume_from_match_report(root, input_data),
        ),
    ]


def _read_resume_section(repo_root: Path, input_data: Mapping[str, Any]) -> ToolResult:
    project_dir = resolve_path(repo_root, str(input_data["project_dir"]))
    section_name = _normalize_section(str(input_data["section"]))
    modules = _load_modules(project_dir)
    section = _get_section(modules, section_name)
    return ToolResult(
        content={
            "status": "ok",
            "tool": "read_resume_section",
            "section_name": section_name,
            "section": section,
        }
    )


def _write_resume_section(repo_root: Path, input_data: Mapping[str, Any]) -> ToolResult:
    project_dir = resolve_path(repo_root, str(input_data["project_dir"]))
    section_name = _normalize_section(str(input_data["section"]))
    content = input_data["content"]
    if not isinstance(content, Mapping):
        raise ToolExecutionError("write_resume_section content must be an object")
    return _write_section_content(
        repo_root=repo_root,
        project_dir=project_dir,
        section_name=section_name,
        section_content=dict(content),
        reason=f"before write_resume_section:{section_name}",
        tool_name="write_resume_section",
    )


def _revise_resume_section(repo_root: Path, input_data: Mapping[str, Any]) -> ToolResult:
    if complete_json is None:
        raise ToolExecutionError("LLM client unavailable for section revision")

    project_dir = resolve_path(repo_root, str(input_data["project_dir"]))
    section_name = _normalize_section(str(input_data["section"]))
    instruction = str(input_data["instruction"])
    modules = _load_modules(project_dir)
    section = _get_section(modules, section_name)

    system = (
        "你是简历局部改写助手。你只能改写用户指定的 resume_modules section，"
        "不得改动其他 section，不得编造用户没有提供的事实。只输出 JSON 对象。"
    )
    user = (
        "section_name:\n"
        + section_name
        + "\n\ninstruction:\n"
        + instruction
        + "\n\ncurrent_section:\n"
        + json.dumps(section, ensure_ascii=False, indent=2)
        + "\n\nfull_resume_modules_for_context:\n"
        + json.dumps(modules, ensure_ascii=False, indent=2)
        + "\n\nOutput format: {\"section\": <revised section object>}"
    )

    try:
        result = complete_json(system, user, temperature=0.2, retries=1)
    except Exception as exc:
        raise ToolExecutionError(f"LLM section revision failed: {exc}") from exc

    revised = _section_from_llm_result(result)
    return _write_section_content(
        repo_root=repo_root,
        project_dir=project_dir,
        section_name=section_name,
        section_content=revised,
        reason=f"before revise_resume_section:{section_name}",
        tool_name="revise_resume_section",
    )


def _default_revision_instruction(section_name: str, missing_keywords: list[str]) -> str:
    """Build a default revision instruction from match-report gaps for automated runs."""
    if missing_keywords:
        kw = "、".join(str(k) for k in missing_keywords[:12])
        return (
            f"在不编造事实的前提下，优化「{section_name}」部分，"
            f"尽量自然地覆盖以下岗位关键词与能力点：{kw}。"
            "若现有经历确实无法支撑某关键词，则跳过该词，不得虚构。"
        )
    return (
        f"在不编造事实的前提下，提升「{section_name}」部分与目标岗位的匹配度，"
        "强化与岗位职责相关的成果与量化指标表达。"
    )


def _revise_resume_from_match_report(repo_root: Path, input_data: Mapping[str, Any]) -> ToolResult:
    if complete_json is None:
        raise ToolExecutionError("LLM client unavailable for match-report-driven section revision")

    project_dir = resolve_path(repo_root, str(input_data["project_dir"]))
    modules = _load_modules(project_dir)
    report_path = project_dir / "checks" / "match_report.json"
    if not report_path.is_file():
        raise ToolExecutionError(f"match_report.json not found at {report_path}")
    match_report = _load_match_report(report_path)
    explicit_section = str(input_data.get("section") or "").strip()
    section_name = (
        _normalize_section(explicit_section)
        if explicit_section
        else _target_section_from_match_report(match_report, modules)
    )
    section = _get_section(modules, section_name)
    missing_keywords = _missing_keywords(match_report)

    # instruction is optional: in automated pipeline mode no human/LLM provides one,
    # so derive a default from the match_report gaps.
    instruction = str(input_data.get("instruction") or "").strip()
    if not instruction:
        instruction = _default_revision_instruction(section_name, missing_keywords)

    system = (
        "你是简历匹配度驱动的局部改写助手。你只能改写选中的 resume_modules section，"
        "优先补足 match_report 中的岗位缺口；不得编造没有事实依据的经历。只输出 JSON 对象。"
    )
    user = (
        "match_report driven revision\n\n"
        "section_name:\n"
        + section_name
        + "\n\ninstruction:\n"
        + instruction
        + "\n\nmissing_keywords:\n"
        + json.dumps(missing_keywords, ensure_ascii=False, indent=2)
        + "\n\nmatch_report:\n"
        + json.dumps(match_report, ensure_ascii=False, indent=2)
        + "\n\ncurrent_section:\n"
        + json.dumps(section, ensure_ascii=False, indent=2)
        + "\n\nfull_resume_modules_for_context:\n"
        + json.dumps(modules, ensure_ascii=False, indent=2)
        + "\n\nOutput format: {\"section\": <revised section object>}"
    )

    try:
        result = complete_json(system, user, temperature=0.2, retries=1)
    except Exception as exc:
        raise ToolExecutionError(f"LLM match-report-driven section revision failed: {exc}") from exc

    revised = _section_from_llm_result(result)
    write_result = _write_section_content(
        repo_root=repo_root,
        project_dir=project_dir,
        section_name=section_name,
        section_content=revised,
        reason=f"before revise_resume_from_match_report:{section_name}",
        tool_name="revise_resume_from_match_report",
    )
    content = dict(write_result.content)
    content["match_report"] = {
        "target_section": section_name,
        "missing_keywords": missing_keywords,
        "overall_score": match_report.get("overall_score", 0),
        "path": str(report_path.resolve()),
    }
    return ToolResult(content=content)


def _write_section_content(
    repo_root: Path,
    project_dir: Path,
    section_name: str,
    section_content: dict[str, Any],
    reason: str,
    tool_name: str,
) -> ToolResult:
    modules_path = _modules_path(project_dir)
    modules = _load_modules(project_dir)
    updated = _replace_section(modules, section_name, section_content)

    try:
        validate_resume_modules(repo_root, updated)
    except ResumeModulesValidationError as exc:
        raise ToolExecutionError("resume section update failed schema validation: " + str(exc)) from exc

    snapshot = snapshot_artifacts(
        project_dir=project_dir,
        paths=["latex/resume_modules.json"],
        reason=reason,
    )
    modules_path.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    diff = diff_artifact(project_dir, snapshot.version_id, "latex/resume_modules.json")
    section = _get_section(updated, section_name)
    return ToolResult(
        content={
            "status": "ok",
            "tool": tool_name,
            "section_name": section_name,
            "section": section,
            "snapshot": {
                "version_id": snapshot.version_id,
                "metadata": str(snapshot.metadata_path.resolve()),
                "files": list(snapshot.files),
            },
            "diff": diff,
            "outputs": {"resume_modules": str(modules_path.resolve())},
        }
    )


def _load_modules(project_dir: Path) -> dict[str, Any]:
    modules_path = _modules_path(project_dir)
    if not modules_path.is_file():
        raise ToolExecutionError(f"resume_modules.json not found at {modules_path}")
    data = json.loads(modules_path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ToolExecutionError("resume_modules.json must contain a JSON object")
    return data


def _modules_path(project_dir: Path) -> Path:
    return project_dir / "latex" / "resume_modules.json"


def _normalize_section(value: str) -> str:
    section = value.strip().lower()
    if section == "project":
        section = "projects"
    if section in {"work", "internship", "internships"}:
        section = "experience"
    if section not in SECTION_MODULE_IDS and section not in {"header", "quality_constraints"}:
        raise ToolExecutionError(f"unknown resume section: {value}")
    return section


def _get_section(modules: Mapping[str, Any], section_name: str) -> Any:
    if section_name in {"header", "quality_constraints"}:
        return copy.deepcopy(modules.get(section_name, {}))
    for module in modules.get("modules", []):
        if isinstance(module, Mapping) and module.get("module_id") == section_name:
            return copy.deepcopy(dict(module))
    raise ToolExecutionError(f"resume section not found: {section_name}")


def _replace_section(
    modules: Mapping[str, Any],
    section_name: str,
    section_content: Mapping[str, Any],
) -> dict[str, Any]:
    updated = copy.deepcopy(dict(modules))
    if section_name in {"header", "quality_constraints"}:
        updated[section_name] = dict(section_content)
        return updated

    normalized_content = dict(section_content)
    normalized_content["module_id"] = section_name
    normalized_content.setdefault("title", _default_title(section_name))
    normalized_content.setdefault("items", [])

    module_list = updated.get("modules")
    if not isinstance(module_list, list):
        raise ToolExecutionError("resume_modules.modules must be an array")

    for index, module in enumerate(module_list):
        if isinstance(module, Mapping) and module.get("module_id") == section_name:
            module_list[index] = normalized_content
            return updated
    module_list.append(normalized_content)
    return updated


def _default_title(section_name: str) -> str:
    return {
        "summary": "个人总结",
        "education": "教育经历",
        "experience": "实习/工作经历",
        "projects": "项目经历",
        "awards": "荣誉奖项/证书",
        "skills": "技能",
        "certifications": "证书",
    }.get(section_name, section_name)


def _section_from_llm_result(result: Any) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        raise ToolExecutionError("LLM section revision must return a JSON object")
    raw_section = result.get("section", result)
    if not isinstance(raw_section, Mapping):
        raise ToolExecutionError("LLM section revision must return section as an object")
    return dict(raw_section)


def _load_match_report(path: Path) -> dict[str, Any]:
    try:
        report = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ToolExecutionError(f"cannot read match_report.json: {exc}") from exc
    if not isinstance(report, dict):
        raise ToolExecutionError("match_report.json must contain a JSON object")
    return report


def _target_section_from_match_report(report: Mapping[str, Any], modules: Mapping[str, Any]) -> str:
    section_scores = report.get("section_scores")
    existing_sections = {
        str(module.get("module_id"))
        for module in modules.get("modules", [])
        if isinstance(module, Mapping) and module.get("module_id")
    }
    if isinstance(section_scores, Mapping):
        candidates: list[tuple[int, str]] = []
        for section, score in section_scores.items():
            section_name = str(section)
            if section_name not in existing_sections or section_name not in SECTION_MODULE_IDS:
                continue
            try:
                numeric = int(round(float(score)))
            except (TypeError, ValueError):
                continue
            candidates.append((numeric, section_name))
        if candidates:
            return sorted(candidates, key=lambda item: (item[0], _section_priority(item[1])))[0][1]

    for fallback in ("projects", "experience", "skills", "summary"):
        if fallback in existing_sections:
            return fallback
    raise ToolExecutionError("cannot choose a resume section from match_report.json")


def _section_priority(section_name: str) -> int:
    return {
        "projects": 0,
        "experience": 1,
        "skills": 2,
        "summary": 3,
        "education": 4,
        "awards": 5,
        "certifications": 6,
    }.get(section_name, 99)


def _missing_keywords(report: Mapping[str, Any]) -> list[str]:
    coverage = report.get("keyword_coverage")
    if isinstance(coverage, Mapping) and isinstance(coverage.get("missing"), list):
        return [str(item) for item in coverage["missing"]]
    gaps = report.get("skill_gaps")
    if isinstance(gaps, list):
        return [
            str(item.get("skill"))
            for item in gaps
            if isinstance(item, Mapping) and item.get("skill")
        ]
    return []
