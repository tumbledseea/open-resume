#!/usr/bin/env python
"""Render template5 LaTeX from structured resume modules."""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from jsonschema import Draft7Validator


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent.parent
TEMPLATE_ROOT = SKILL_ROOT / "examples" / "orange_warm"
LATEX_ROOT = TEMPLATE_ROOT / "latex"
SCHEMA_PATH = SKILL_ROOT / "schemas" / "resume_modules.schema.json"
CLASS_PATH = LATEX_ROOT / "orange_warm.cls"
MODULE_ORDER = ["education", "experience", "projects", "awards"]
REQUIRED_MODULES = set(MODULE_ORDER)

LATEX_ESCAPE_MAP = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}"
}


def latex_escape(value: Any) -> str:
    text = "" if value is None else str(value)
    return "".join(LATEX_ESCAPE_MAP.get(char, char) for char in text)


def escape_tree(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: escape_tree(item) for key, item in value.items()}
    if isinstance(value, list):
        return [escape_tree(item) for item in value]
    if isinstance(value, str) or value is None:
        return latex_escape(value)
    return value


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_modules(data: dict[str, Any]) -> None:
    schema = load_json(SCHEMA_PATH)
    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda error: error.path)
    if errors:
        messages = []
        for error in errors:
            location = ".".join(str(part) for part in error.path) or "<root>"
            messages.append(f"{location}: {error.message}")
        raise ValueError("resume_modules.json failed schema validation: " + "; ".join(messages))

    module_ids = {module["module_id"] for module in data.get("modules", [])}
    missing = sorted(REQUIRED_MODULES - module_ids)
    if missing:
        raise ValueError("resume_modules.json missing required modules: " + ", ".join(missing))


def normalize_bullets(raw_bullets: Any) -> list[dict[str, str]]:
    bullets: list[dict[str, str]] = []
    if not isinstance(raw_bullets, list):
        return bullets

    for bullet in raw_bullets:
        if isinstance(bullet, str):
            bullets.append({"label": "", "text": bullet})
        elif isinstance(bullet, dict):
            bullets.append({
                "label": str(bullet.get("label", "") or ""),
                "text": str(bullet.get("text", "") or ""),
            })
    return [bullet for bullet in bullets if bullet["text"]]


def normalize_modules(data: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(data)
    header = normalized.setdefault("header", {})
    contact_parts = []
    if header.get("phone"):
        contact_parts.append(f"电话：{header['phone']}")
    if header.get("email"):
        contact_parts.append(f"邮箱：{header['email']}")
    if header.get("location"):
        contact_parts.append(f"现居城市：{header['location']}")
    if header.get("website"):
        contact_parts.append(f"网站：{header['website']}")
    header["contact_line"] = " | ".join(contact_parts)
    header.setdefault("photo", "")

    for module in normalized.get("modules", []):
        for item in module.get("items", []):
            item.setdefault("badges", [])
            item.setdefault("details", [])
            item.setdefault("bullets", [])
            item["bullets"] = normalize_bullets(item.get("bullets"))
            for field in (
                "school",
                "time",
                "major",
                "degree",
                "college",
                "study_type",
                "location",
                "organization",
                "role",
                "project",
                "name",
            ):
                item.setdefault(field, "")

    return normalized


def render_latex(data: dict[str, Any]) -> str:
    normalized = normalize_modules(data)
    escaped = escape_tree(normalized)
    modules_by_id = {
        module["module_id"]: module
        for module in escaped.get("modules", [])
    }
    env = Environment(
        loader=FileSystemLoader(str(LATEX_ROOT)),
        undefined=StrictUndefined,
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("main.tex.j2")
    return template.render(
        header=escaped["header"],
        modules_by_id=modules_by_id,
        module_order=MODULE_ORDER,
    )


def render_to_output(modules_path: Path, output_path: Path) -> tuple[Path, Path]:
    data = load_json(modules_path)
    validate_modules(data)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tex = render_latex(data)
    output_path.write_text(tex, encoding="utf-8")
    cls_output = output_path.parent / "orange_warm.cls"
    shutil.copy2(CLASS_PATH, cls_output)
    return output_path, cls_output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render template5 LaTeX from resume modules")
    parser.add_argument("--modules", required=True, help="Path to resume_modules.json")
    output_group = parser.add_mutually_exclusive_group(required=True)
    output_group.add_argument("--output", help="Output resume.tex path")
    output_group.add_argument("--project", help="Project directory; writes latex/resume.tex")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    modules_path = Path(args.modules).resolve()
    output_path = Path(args.output).resolve() if args.output else Path(args.project).resolve() / "latex" / "resume.tex"

    try:
        tex_path, cls_path = render_to_output(modules_path, output_path)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"tex={tex_path}")
    print(f"class={cls_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
