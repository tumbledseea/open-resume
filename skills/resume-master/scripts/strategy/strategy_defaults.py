#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


SECTION_ORDER = ["basic_info", "education", "skills", "projects", "internships", "awards"]
DEFAULT_LAYOUT = "橙色背景简历"


def md_value(text: str, key: str, default: str = "XX") -> str:
    m = re.search(rf"(?im)^-\s*{re.escape(key)}\s*:\s*(.+)$", text)
    if not m:
        return default
    value = m.group(1).strip()
    return value or default


def parse_json_block(text: str) -> dict[str, object]:
    match = re.search(r"```json\s*(.*?)```", text, re.S | re.I)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def parse_jd_analysis(jd_analysis: str) -> dict[str, object]:
    data = parse_json_block(jd_analysis)
    if data:
        return data
    return {
        "company": md_value(jd_analysis, "Company"),
        "role": md_value(jd_analysis, "Role"),
        "mode": "targeted",
        "keywords": [part.strip() for part in md_value(jd_analysis, "Keywords", "").split(",") if part.strip()],
    }


def create_spec_lock(data: dict[str, object]) -> dict[str, object]:
    keywords = data.get("keywords", [])
    if isinstance(keywords, str):
        keywords = [part.strip() for part in keywords.split(",") if part.strip()]
    if not isinstance(keywords, list):
        keywords = []

    return {
        "language": "zh-CN",
        "mode": str(data.get("mode") or "targeted"),
        "resume_type": "visual_svg",
        "layout": DEFAULT_LAYOUT,
        "template_svg": f"templates/layouts/{DEFAULT_LAYOUT}/template.svg",
        "design_spec": f"templates/layouts/{DEFAULT_LAYOUT}/design_spec.md",
        "page_limit": 1,
        "target_company": str(data.get("company") or "XX"),
        "target_role": str(data.get("role") or "XX"),
        "priority_keywords": [str(item) for item in keywords],
        "canvas": {
            "width": 1280,
            "height": 2000,
            "viewBox": "0 0 1280 2000",
            "format": "single-page-svg-resume",
        },
        "safe_area": {
            "x_min": 50,
            "x_max": 1230,
            "y_min": 40,
            "y_max": 1965,
        },
        "font_roles": {
            "title": '"Source Han Serif SC", "Noto Serif CJK SC", "Songti SC", SimSun, serif',
            "body": '"Microsoft YaHei", "PingFang SC", Arial, sans-serif',
            "section": '"Source Han Serif SC", "Noto Serif CJK SC", "Songti SC", SimSun, serif',
        },
        "section_order": SECTION_ORDER,
        "max_lines_per_section": {
            "summary": 3,
            "education": 3,
            "skills": 3,
            "projects": 8,
            "internships": 6,
            "awards": 4,
            "other": 3,
        },
        "placeholder_policy": {
            "missing_value": "",
            "unresolved_placeholders_forbidden": True,
            "preserve_resume_md": True,
            "semantic_resume_path": "exports/resume.md",
        },
        "overflow_policy": {
            "strategy": "truncate_with_report",
            "line_wrap_chars": 42,
            "line_height": 30,
            "report_path": "checks/layout_quality.json",
        },
        "quality_gates": [
            "placeholder",
            "overflow",
            "truthfulness",
            "export",
        ],
    }


def create_spec_lock_md(spec_lock: dict[str, object]) -> str:
    sections = " -> ".join(str(item) for item in spec_lock["section_order"])
    keywords = ", ".join(str(item) for item in spec_lock["priority_keywords"])
    return (
        "# Spec Lock\n\n"
        "> Compatibility summary. Machine-readable contract is `spec_lock.json`.\n\n"
        f"- Language: {spec_lock['language']}\n"
        f"- Mode: {spec_lock['mode']}\n"
        f"- Resume Type: {spec_lock['resume_type']}\n"
        f"- Layout: {spec_lock['layout']}\n"
        f"- Page Limit: {spec_lock['page_limit']}\n"
        f"- Target Company: {spec_lock['target_company']}\n"
        f"- Target Role: {spec_lock['target_role']}\n"
        f"- Priority Keywords: {keywords}\n"
        f"- Section Order: {sections}\n"
        "- Placeholder Policy: unresolved placeholders forbidden\n"
    )


def create_strategy_md(spec_lock: dict[str, object]) -> str:
    keywords = ", ".join(str(item) for item in spec_lock["priority_keywords"]) or "role-relevant skills"
    return (
        "# Resume Strategy\n\n"
        f"## Target\n{spec_lock['target_company']} - {spec_lock['target_role']}\n\n"
        "## Positioning\n"
        f"Highlight hands-on experience that aligns with {keywords}.\n\n"
        "## Selected Layout\n"
        f"{spec_lock['layout']}\n\n"
        "## Machine Contract\n"
        "Use `strategy/spec_lock.json` as the only machine-readable lock file for writing and rendering.\n"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create default resume strategy and spec lock (md)")
    parser.add_argument("--project", default=None, help="Project directory (single-JD mode)")
    parser.add_argument("--job-dir", default=None, help="Job subdirectory (multi-JD mode)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.job_dir:
            base_path = Path(args.job_dir).resolve()
        elif args.project:
            base_path = Path(args.project).resolve()
        else:
            raise ValueError("Either --project or --job-dir is required")
        jd_analysis_path = base_path / "jd" / "jd_analysis.md"
        if not jd_analysis_path.is_file():
            raise FileNotFoundError(f"Missing JD analysis file: {jd_analysis_path}")
        jd_analysis = jd_analysis_path.read_text(encoding="utf-8-sig")
        jd_data = parse_jd_analysis(jd_analysis)
        spec_lock = create_spec_lock(jd_data)
        strategy_dir = base_path / "strategy"
        strategy_dir.mkdir(parents=True, exist_ok=True)
        (strategy_dir / "spec_lock.json").write_text(
            json.dumps(spec_lock, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (strategy_dir / "resume_strategy.md").write_text(create_strategy_md(spec_lock), encoding="utf-8")
        print((strategy_dir / "resume_strategy.md").resolve())
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
