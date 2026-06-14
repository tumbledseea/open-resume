from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping

from resume_agent.schema.jd_analysis import (
    JDAnalysisValidationError,
    normalize_jd_analysis,
    validate_jd_analysis,
)
from resume_agent.tools.base import FunctionTool, ToolExecutionError, ToolPermission, ToolResult
from resume_agent.tools.llm_runtime import complete_json
from resume_agent.tools.tool_runtime import resolve_path, run_script, script_result


def create_jd_tools(repo_root: Path) -> list[FunctionTool]:
    root = Path(repo_root).resolve()
    return [
        FunctionTool(
            name="add_jd_text",
            description="Write a pasted job description into project/jd/jd_raw.md.",
            input_schema={
                "type": "object",
                "required": ["project_dir", "company", "role", "text"],
                "properties": {
                    "project_dir": {"type": "string"},
                    "company": {"type": "string"},
                    "role": {"type": "string"},
                    "text": {"type": "string"},
                },
            },
            read_only=False,
            permission=ToolPermission.WORKSPACE_WRITE,
            handler=lambda input_data, context: _add_jd_text(root, input_data),
        ),
        FunctionTool(
            name="fetch_jd_url",
            description="Fetch a JD URL and write project/jd/jd_raw.md.",
            input_schema={
                "type": "object",
                "required": ["project_dir", "url", "company", "role"],
                "properties": {
                    "project_dir": {"type": "string"},
                    "url": {"type": "string"},
                    "company": {"type": "string"},
                    "role": {"type": "string"},
                },
            },
            read_only=False,
            permission=ToolPermission.NETWORK,
            handler=lambda input_data, context: _fetch_jd_url(root, input_data),
        ),
        FunctionTool(
            name="analyze_jd",
            description="Analyze project/jd/jd_raw.md into project/jd/jd_analysis.md.",
            input_schema={
                "type": "object",
                "required": ["project_dir"],
                "properties": {"project_dir": {"type": "string"}},
            },
            read_only=False,
            permission=ToolPermission.WORKSPACE_WRITE,
            handler=lambda input_data, context: _analyze_jd(root, input_data),
        ),
    ]


def _add_jd_text(repo_root: Path, input_data: Mapping[str, Any]) -> ToolResult:
    project_dir = resolve_path(repo_root, str(input_data["project_dir"]))
    result = run_script(
        repo_root,
        [
            "job_manager.py",
            "add-text",
            "--project",
            str(project_dir),
            "--company",
            str(input_data["company"]),
            "--role",
            str(input_data["role"]),
            "--text",
            str(input_data["text"]),
        ],
    )
    return script_result("add_jd_text", result, {"jd_raw": project_dir / "jd" / "jd_raw.md"})


def _fetch_jd_url(repo_root: Path, input_data: Mapping[str, Any]) -> ToolResult:
    project_dir = resolve_path(repo_root, str(input_data["project_dir"]))
    result = run_script(
        repo_root,
        [
            "job_manager.py",
            "fetch-url",
            "--project",
            str(project_dir),
            "--url",
            str(input_data["url"]),
            "--company",
            str(input_data["company"]),
            "--role",
            str(input_data["role"]),
        ],
    )
    return script_result("fetch_jd_url", result, {"jd_raw": project_dir / "jd" / "jd_raw.md"})


def _analyze_jd(repo_root: Path, input_data: Mapping[str, Any]) -> ToolResult:
    project_dir = resolve_path(repo_root, str(input_data["project_dir"]))
    raw_path = project_dir / "jd" / "jd_raw.md"
    if not raw_path.is_file():
        raise ToolExecutionError(f"missing JD raw file: {raw_path}")
    raw_text = raw_path.read_text(encoding="utf-8-sig")

    analysis, analysis_metadata = _analyze_jd_structured(raw_text)

    output = project_dir / "jd" / "jd_analysis.md"
    md = "# JD Analysis\n\n> 由AI分析的岗位画像\n\n```json\n"
    md += json.dumps(analysis, ensure_ascii=False, indent=2) + "\n```\n\n"
    md += "## 分析总结\n\n" + analysis.get("analysis_summary", "") + "\n\n"
    md += "## 核心要求\n\n"
    for i, req in enumerate(analysis.get("key_requirements", []), 1):
        md += f"{i}. {req}\n"
    md += "\n## 加分项\n\n"
    for i, item in enumerate(analysis.get("nice_to_have", []), 1):
        md += f"{i}. {item}\n"
    output.write_text(md, encoding="utf-8")

    return ToolResult(
        content={
            "status": "ok",
            "tool": "analyze_jd",
            "analysis_mode": analysis_metadata["analysis_mode"],
            "schema_validated": True,
            "schema_repaired": analysis_metadata["schema_repaired"],
            "outputs": {"jd_analysis": str(output.resolve())},
        }
    )


def _analyze_jd_structured(raw_text: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if complete_json is None:
        return _validated_regex_analysis(raw_text), {
            "analysis_mode": "regex",
            "schema_repaired": False,
        }

    system = """你是JD分析专家。从岗位描述中提取关键信息，输出JSON。
字段:
- company: 公司名
- role: 岗位名
- keywords: 核心技术关键词列表（20个以内）
- key_requirements: 核心要求列表（6个以内）
- nice_to_have: 加分项列表
- analysis_summary: 一段分析总结（中文，100字以内）

要求:
- keywords、key_requirements、nice_to_have 必须是字符串数组
- confidence_score 如果输出，必须是 0 到 100 的数字
- 只输出 JSON 对象，不要输出 markdown。"""

    try:
        result = complete_json(system, raw_text)
    except Exception as exc:
        print(f"[warn] LLM JD analysis failed ({exc}); falling back to regex", file=sys.stderr)
        return _validated_regex_analysis(raw_text), {
            "analysis_mode": "regex",
            "schema_repaired": False,
        }

    try:
        validate_jd_analysis(result)
    except JDAnalysisValidationError as exc:
        repaired = _repair_jd_analysis(result, exc, raw_text)
        try:
            validate_jd_analysis(repaired)
        except JDAnalysisValidationError as repair_exc:
            raise ToolExecutionError(
                "JD analysis schema validation failed after repair: "
                + str(repair_exc)
            ) from repair_exc
        return normalize_jd_analysis(repaired), {
            "analysis_mode": "llm",
            "schema_repaired": True,
        }

    return normalize_jd_analysis(result), {
        "analysis_mode": "llm",
        "schema_repaired": False,
    }


def _repair_jd_analysis(
    original_result: Any,
    validation_error: JDAnalysisValidationError,
    raw_text: str,
) -> Mapping[str, Any]:
    if complete_json is None:
        raise ToolExecutionError("LLM JD analysis repair unavailable")

    repair_system = (
        "你是 JD analysis JSON 修复器。修复给定 JSON，使其严格符合 schema。"
        "只输出 JSON 对象，不要输出 markdown。"
    )
    repair_user = (
        "schema validation errors:\n"
        + "\n".join(f"- {message}" for message in validation_error.messages)
        + "\n\nrequired fields:\n"
        + "- company: string\n"
        + "- role: string\n"
        + "- keywords: string[] max 20\n"
        + "- key_requirements: string[] max 8\n"
        + "- nice_to_have: string[] max 8\n"
        + "- analysis_summary: string\n"
        + "- confidence_score: optional number from 0 to 100\n"
        + "\n\nraw JD text:\n"
        + raw_text
        + "\n\ninvalid model output:\n"
        + json.dumps(original_result, ensure_ascii=False, indent=2)
    )
    try:
        repaired = complete_json(repair_system, repair_user, temperature=0, retries=1)
    except Exception as exc:
        raise ToolExecutionError(f"LLM JD analysis repair failed: {exc}") from exc
    if not isinstance(repaired, Mapping):
        raise ToolExecutionError("LLM JD analysis repair must return a JSON object")
    return repaired


def _validated_regex_analysis(raw_text: str) -> dict[str, Any]:
    analysis = _analyze_jd_regex(raw_text)
    validate_jd_analysis(analysis)
    return normalize_jd_analysis(analysis)


def _analyze_jd_regex(raw_text: str) -> dict[str, Any]:
    keywords = _extract_jd_keywords(raw_text)
    company = _md_value(raw_text, "Company")
    role = _md_value(raw_text, "Role")
    summary_parts = []
    if role and role != "XX":
        summary_parts.append(f"岗位为{role}")
    if keywords:
        summary_parts.append("关注" + "、".join(keywords[:6]))
    analysis_summary = "，".join(summary_parts) + "。" if summary_parts else "岗位要求已从原始JD中提取。"
    return {
        "company": company,
        "role": role,
        "mode": "targeted",
        "keywords": keywords,
        "key_requirements": _extract_requirement_lines(raw_text)[:6],
        "nice_to_have": [],
        "analysis_summary": analysis_summary,
        "confidence_score": 60,
        "hard_requirements": _extract_requirement_lines(raw_text)[:6],
        "preferred_requirements": [],
        "tools_and_technologies": keywords,
        "business_domain": [],
        "resume_implications": ["Prioritize evidence that matches the JD keywords."],
        "risks_or_gaps": [],
    }


def _extract_jd_keywords(text: str) -> list[str]:
    candidates = [
        "Python", "RAG", "AI Agent", "Agent", "工具调用",
        "OpenAI", "LaTeX", "SQL", "机器学习", "深度学习",
        "数据分析", "后端",
    ]
    folded = text.lower()
    return [item for item in candidates if item.lower() in folded]


def _extract_requirement_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip().lstrip("-*0123456789.、)） ").strip()
        if not line:
            continue
        if any(term in line for term in ("负责", "熟悉", "掌握", "要求", "经验", "优先")):
            lines.append(line)
    return lines


def _md_value(text: str, key: str, default: str = "XX") -> str:
    match = re.search(rf"(?im)^\s*-\s*{re.escape(key)}\s*:\s*(.+)$", text)
    return match.group(1).strip() if match else default
