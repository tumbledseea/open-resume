from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from resume_agent.tools.base import FunctionTool, ToolExecutionError, ToolPermission, ToolResult
from resume_agent.tools.llm_runtime import complete_json
from resume_agent.tools.tool_runtime import resolve_path


def create_match_tools(repo_root: Path) -> list[FunctionTool]:
    root = Path(repo_root).resolve()
    return [
        FunctionTool(
            name="match_analysis",
            description=(
                "Analyze how well the current resume matches the JD. "
                "Reads jd/jd_analysis.md, strategy/spec_lock.json, and latex/resume_modules.json; "
                "writes checks/match_report.json."
            ),
            input_schema={
                "type": "object",
                "required": ["project_dir"],
                "properties": {
                    "project_dir": {"type": "string"},
                    "use_semantic_alignment": {"type": "boolean"},
                },
            },
            read_only=False,
            permission=ToolPermission.WORKSPACE_WRITE,
            handler=lambda input_data, context: _match_analysis(root, input_data),
        ),
        FunctionTool(
            name="compare_match_reports",
            description=(
                "Compare the current checks/match_report.json with a version snapshot and "
                "write checks/match_trend.json with score and keyword deltas."
            ),
            input_schema={
                "type": "object",
                "required": ["project_dir"],
                "properties": {
                    "project_dir": {"type": "string"},
                    "baseline_version_id": {"type": "string"},
                },
            },
            read_only=False,
            permission=ToolPermission.WORKSPACE_WRITE,
            handler=lambda input_data, context: _compare_match_reports(root, input_data),
        )
    ]


def _match_analysis(repo_root: Path, input_data: Mapping[str, Any]) -> ToolResult:
    project_dir = resolve_path(repo_root, str(input_data["project_dir"]))
    jd_analysis_path = project_dir / "jd" / "jd_analysis.md"
    modules_path = project_dir / "latex" / "resume_modules.json"
    spec_lock_path = project_dir / "strategy" / "spec_lock.json"

    if not jd_analysis_path.is_file():
        raise ToolExecutionError(f"missing JD analysis: {jd_analysis_path}")
    if not modules_path.is_file():
        raise ToolExecutionError(f"missing resume modules: {modules_path}")

    jd_text = jd_analysis_path.read_text(encoding="utf-8-sig")
    jd_data = _extract_json_object(jd_text)
    modules = json.loads(modules_path.read_text(encoding="utf-8-sig"))
    spec = _read_json_object(spec_lock_path) if spec_lock_path.is_file() else {}
    use_semantic_alignment = input_data.get("use_semantic_alignment", True) is not False

    keywords = _unique_strings(
        _string_list(jd_data.get("keywords"))
        + _string_list(jd_data.get("tools_and_technologies"))
        + _string_list(spec.get("priority_keywords"))
    )
    requirements = _unique_strings(
        _string_list(jd_data.get("key_requirements"))
        + _string_list(jd_data.get("hard_requirements"))
        + _string_list(jd_data.get("preferred_requirements"))
        + _string_list(jd_data.get("resume_implications"))
    )

    resume_text = _flatten_text(modules)
    covered = [keyword for keyword in keywords if _contains_keyword(resume_text, keyword)]
    missing = [keyword for keyword in keywords if keyword not in covered]
    coverage_rate = round(len(covered) / len(keywords), 2) if keywords else 0.0
    exact_match_score = int(round(coverage_rate * 100))
    section_scores = _section_scores(modules, keywords)
    semantic = _semantic_alignment(
        requirements,
        modules,
        missing,
        section_scores,
        use_llm=use_semantic_alignment,
    )
    semantic_score = semantic["semantic_score"]
    overall_score = (
        int(round((exact_match_score * 0.6) + (semantic_score * 0.4)))
        if semantic["source"] == "llm"
        else exact_match_score
    )

    report = {
        "status": "pass" if overall_score >= 75 else "warn",
        "overall_score": overall_score,
        "exact_match_score": exact_match_score,
        "semantic_score": semantic_score,
        "semantic_alignment": semantic["semantic_alignment"],
        "semantic_summary": semantic["semantic_summary"],
        "keyword_coverage": {
            "covered": covered,
            "missing": missing,
            "coverage_rate": coverage_rate,
        },
        "section_scores": section_scores,
        "skill_gaps": _skill_gaps(missing),
        "experience_alignment": _experience_alignment(requirements, modules),
        "suggestions": _suggestions(missing, semantic["semantic_alignment"]),
        "inputs": {
            "jd_analysis": str(jd_analysis_path.resolve()),
            "resume_modules": str(modules_path.resolve()),
            "spec_lock": str(spec_lock_path.resolve()) if spec_lock_path.is_file() else "",
        },
    }

    report_path = project_dir / "checks" / "match_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return ToolResult(
        content={
            "status": report["status"],
            "tool": "match_analysis",
            "overall_score": report["overall_score"],
            "semantic_score": report["semantic_score"],
            "outputs": {"match_report": str(report_path.resolve())},
        }
    )


def _compare_match_reports(repo_root: Path, input_data: Mapping[str, Any]) -> ToolResult:
    project_dir = resolve_path(repo_root, str(input_data["project_dir"]))
    current_path = project_dir / "checks" / "match_report.json"
    if not current_path.is_file():
        raise ToolExecutionError(f"missing current match report: {current_path}")

    baseline_version_id = str(input_data.get("baseline_version_id") or "").strip()
    if not baseline_version_id:
        baseline_version_id = _latest_match_report_version(project_dir)
    baseline_path = project_dir / "versions" / baseline_version_id / "checks" / "match_report.json"
    if not baseline_path.is_file():
        raise ToolExecutionError(f"missing baseline match report: {baseline_path}")

    baseline = _read_json_object(baseline_path)
    current = _read_json_object(current_path)
    baseline_covered = _coverage_list(baseline, "covered")
    current_covered = _coverage_list(current, "covered")
    baseline_missing = _coverage_list(baseline, "missing")
    current_missing = _coverage_list(current, "missing")
    baseline_score = _score(baseline)
    current_score = _score(current)
    newly_covered = [keyword for keyword in current_covered if keyword not in baseline_covered]
    regressed = [keyword for keyword in baseline_covered if keyword not in current_covered]
    still_missing = [keyword for keyword in current_missing if keyword in baseline_missing or keyword not in newly_covered]

    trend = {
        "baseline": {
            "version_id": baseline_version_id,
            "overall_score": baseline_score,
            "match_report": str(baseline_path.resolve()),
        },
        "current": {
            "overall_score": current_score,
            "match_report": str(current_path.resolve()),
        },
        "delta": {
            "overall_score": current_score - baseline_score,
            "newly_covered_keywords": newly_covered,
            "regressed_keywords": regressed,
            "still_missing_keywords": still_missing,
        },
        "summary": _trend_summary(baseline_score, current_score, newly_covered, regressed, still_missing),
    }

    trend_path = project_dir / "checks" / "match_trend.json"
    trend_path.parent.mkdir(parents=True, exist_ok=True)
    trend_path.write_text(json.dumps(trend, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return ToolResult(
        content={
            "status": "ok",
            "tool": "compare_match_reports",
            "baseline_version_id": baseline_version_id,
            "delta": trend["delta"],
            "outputs": {"match_trend": str(trend_path.resolve())},
        }
    )


def _extract_json_object(text: str) -> dict[str, Any]:
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    raw = fence.group(1) if fence else text
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _semantic_alignment(
    requirements: list[str],
    modules: Mapping[str, Any],
    missing_keywords: list[str],
    section_scores: Mapping[str, int],
    use_llm: bool,
) -> dict[str, Any]:
    if not use_llm or complete_json is None or not requirements:
        exact_score = _score_from_sections(section_scores)
        return {
            "source": "deterministic",
            "semantic_score": exact_score,
            "semantic_alignment": _experience_alignment(requirements, modules),
            "semantic_summary": "LLM semantic alignment unavailable; using deterministic requirement token overlap.",
        }

    system = (
        "你是简历-JD 语义匹配评估器。判断 JD 要求是否被简历中的真实证据覆盖，"
        "允许识别简称、同义词和上下位概念，但不得编造简历没有的事实。只输出 JSON。"
    )
    user = (
        "semantic alignment task\n\n"
        "JD requirements:\n"
        + json.dumps(requirements, ensure_ascii=False, indent=2)
        + "\n\nExact-missing keywords:\n"
        + json.dumps(missing_keywords, ensure_ascii=False, indent=2)
        + "\n\nResume modules:\n"
        + json.dumps(modules, ensure_ascii=False, indent=2)
        + "\n\nOutput format: "
        '{"semantic_alignment":[{"jd_requirement":"...","resume_evidence":"...",'
        '"match":"strong|medium|weak|missing","score":0,"section":"projects",'
        '"reason":"..."}],"semantic_score":0,"semantic_summary":"..."}'
    )

    try:
        result = complete_json(system, user, temperature=0.1, retries=1)
    except Exception:
        result = {}
    return _normalize_semantic_result(result, requirements, modules, section_scores)


def _normalize_semantic_result(
    result: Any,
    requirements: list[str],
    modules: Mapping[str, Any],
    section_scores: Mapping[str, int],
) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        result = {}
    raw_alignment = result.get("semantic_alignment")
    alignment: list[dict[str, Any]] = []
    if isinstance(raw_alignment, list):
        for item in raw_alignment:
            if not isinstance(item, Mapping):
                continue
            score = _clamp_score(item.get("score"))
            match = str(item.get("match") or _match_label(score))
            alignment.append(
                {
                    "jd_requirement": str(item.get("jd_requirement") or ""),
                    "resume_evidence": str(item.get("resume_evidence") or item.get("evidence") or ""),
                    "match": match,
                    "score": score,
                    "section": str(item.get("section") or ""),
                    "reason": str(item.get("reason") or ""),
                }
            )

    if not alignment:
        fallback = _experience_alignment(requirements, modules)
        alignment = [
            {
                "jd_requirement": item["jd_requirement"],
                "resume_evidence": item["evidence"],
                "match": item["match"],
                "score": {"strong": 85, "medium": 60, "missing": 0}.get(item["match"], 0),
                "section": "",
                "reason": "deterministic token overlap fallback",
            }
            for item in fallback
        ]

    raw_score = result.get("semantic_score")
    semantic_score = _clamp_score(raw_score) if raw_score is not None else _average_score(alignment)
    return {
        "source": "llm" if result else "deterministic",
        "semantic_score": semantic_score if alignment else _score_from_sections(section_scores),
        "semantic_alignment": alignment,
        "semantic_summary": str(result.get("semantic_summary") or "Semantic alignment generated from available resume evidence."),
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _flatten_text(value: Any) -> str:
    if isinstance(value, Mapping):
        return "\n".join(_flatten_text(item) for item in value.values())
    if isinstance(value, list):
        return "\n".join(_flatten_text(item) for item in value)
    return "" if value is None else str(value)


def _contains_keyword(text: str, keyword: str) -> bool:
    return keyword.casefold() in text.casefold()


def _section_scores(modules: Mapping[str, Any], keywords: list[str]) -> dict[str, int]:
    scores: dict[str, int] = {}
    for module in modules.get("modules", []):
        if not isinstance(module, Mapping):
            continue
        module_id = str(module.get("module_id") or "")
        if not module_id:
            continue
        text = _flatten_text(module)
        matched = [keyword for keyword in keywords if _contains_keyword(text, keyword)]
        scores[module_id] = int(round((len(matched) / len(keywords)) * 100)) if keywords else 0
    return scores


def _skill_gaps(missing: list[str]) -> list[dict[str, str]]:
    return [
        {
            "skill": keyword,
            "importance": "high" if index < 3 else "medium",
            "suggestion": f"如果真实具备 {keyword} 经验，在项目或技能部分补充可追溯证据。",
        }
        for index, keyword in enumerate(missing)
    ]


def _experience_alignment(requirements: list[str], modules: Mapping[str, Any]) -> list[dict[str, str]]:
    resume_text = _flatten_text(modules)
    alignment: list[dict[str, str]] = []
    for requirement in requirements[:8]:
        tokens = _requirement_tokens(requirement)
        matched = [token for token in tokens if _contains_keyword(resume_text, token)]
        if len(matched) >= 2:
            match = "strong"
        elif matched:
            match = "medium"
        else:
            match = "missing"
        alignment.append(
            {
                "jd_requirement": requirement,
                "evidence": ", ".join(matched) if matched else "",
                "match": match,
            }
        )
    return alignment


def _requirement_tokens(requirement: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[A-Za-z][A-Za-z0-9/+.#-]*|[\u4e00-\u9fff]{2,}", requirement)
        if len(token.strip()) >= 2
    ]


def _suggestions(missing: list[str], semantic_alignment: list[dict[str, Any]] | None = None) -> list[str]:
    if not missing:
        return ["当前简历已覆盖 JD 的主要关键词，下一步可优化证据强度和量化结果。"]
    semantic_text = "\n".join(
        str(item.get("jd_requirement", "")) + "\n" + str(item.get("resume_evidence", ""))
        for item in semantic_alignment or []
        if str(item.get("match", "")).lower() in {"strong", "medium"}
    )
    semantically_covered = [keyword for keyword in missing if _contains_keyword(semantic_text, keyword)]
    return [
        (
            f"{keyword} 虽未精确出现，但已被语义证据覆盖；建议补充标准表述以提升 ATS 命中。"
            if keyword in semantically_covered
            else f"补充 {keyword} 的真实项目、实习或技能证据；没有事实依据时不要硬写。"
        )
        for keyword in missing
    ]


def _score_from_sections(section_scores: Mapping[str, int]) -> int:
    if not section_scores:
        return 0
    return int(round(sum(section_scores.values()) / len(section_scores)))


def _average_score(items: list[dict[str, Any]]) -> int:
    scores = [_clamp_score(item.get("score")) for item in items]
    return int(round(sum(scores) / len(scores))) if scores else 0


def _clamp_score(value: Any) -> int:
    try:
        score = int(round(float(value)))
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, score))


def _match_label(score: int) -> str:
    if score >= 80:
        return "strong"
    if score >= 50:
        return "medium"
    if score > 0:
        return "weak"
    return "missing"


def _latest_match_report_version(project_dir: Path) -> str:
    versions_dir = project_dir / "versions"
    if not versions_dir.is_dir():
        raise ToolExecutionError("no artifact versions found for match report comparison")
    candidates = [
        path.parent.name
        for path in sorted(versions_dir.glob("*/checks/match_report.json"))
        if path.is_file()
    ]
    if not candidates:
        raise ToolExecutionError("no versioned match_report.json found")
    return candidates[-1]


def _coverage_list(report: Mapping[str, Any], key: str) -> list[str]:
    coverage = report.get("keyword_coverage")
    if not isinstance(coverage, Mapping):
        return []
    values = coverage.get(key)
    if not isinstance(values, list):
        return []
    return [str(value) for value in values]


def _score(report: Mapping[str, Any]) -> int:
    return _clamp_score(report.get("overall_score"))


def _trend_summary(
    baseline_score: int,
    current_score: int,
    newly_covered: list[str],
    regressed: list[str],
    still_missing: list[str],
) -> str:
    delta = current_score - baseline_score
    direction = "提升" if delta >= 0 else "下降"
    parts = [f"匹配度从 {baseline_score} 到 {current_score}，{direction} {abs(delta)} 分。"]
    if newly_covered:
        parts.append("新增覆盖：" + "、".join(newly_covered) + "。")
    if regressed:
        parts.append("回退关键词：" + "、".join(regressed) + "。")
    if still_missing:
        parts.append("仍缺失：" + "、".join(still_missing) + "。")
    return "".join(parts)
