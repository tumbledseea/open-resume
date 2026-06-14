#!/usr/bin/env python
"""Normalize free-text profile markdown into profile.json + fact_index.json.

Primary path: call the configured LLM to extract structured facts from
arbitrary candidate notes (the input is rarely in `key: value` form).
Fallback path: the original regex extractor, used only when the LLM is
unavailable, so the pipeline never hard-fails.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# allow running as a script: add scripts/ to path for `llm` package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from llm.client import complete_json, LLMConfigError  # type: ignore
except Exception:  # noqa: BLE001
    complete_json = None  # type: ignore

    class LLMConfigError(RuntimeError):  # type: ignore
        pass


EMPTY_PROFILE = {
    "basic_info": {
        "name": "XX",
        "email": "XX",
        "phone": "XX",
        "location": "XX",
        "target_direction": "XX",
        "links": [],
    },
    "education": [],
    "skills": [],
    "projects": [],
    "internships": [],
    "awards": [],
    "certifications": [],
    "publications": [],
    "other_experiences": [],
    "needs_user_confirmation": [],
}


SYSTEM_PROMPT = """你是简历事实抽取器。从候选人的自由文本资料中抽取结构化事实。

铁律：
- 只抽取文本中明确存在的事实，绝不编造、不补全、不推断未写明的内容。
- 缺失的字段用 "XX"（标量）或 []（列表）表示。
- 原文是中文就保留中文，不要翻译。
- 日期、数字、专有名词（学校、公司、比赛、技术名）严格照原文。

输出一个 JSON 对象，仅包含这些键：
basic_info{name,email,phone,location,target_direction,links[]},
education[{school,degree,major,start,end}],
skills[字符串],
projects[{name,role,start,end,description,highlights[]}],
internships[{company,role,start,end,description,highlights[]}],
awards[字符串],
certifications[字符串],
publications[字符串],
other_experiences[字符串],
needs_user_confirmation[字符串：列出原文模糊或缺失、需要用户确认的点]
"""


def normalize_profile_llm(text: str) -> dict:
    if complete_json is None:
        raise LLMConfigError("llm client unavailable")
    data = complete_json(SYSTEM_PROMPT, "候选人资料：\n\n" + text)
    # merge onto skeleton so all keys always exist
    profile = json.loads(json.dumps(EMPTY_PROFILE))
    for key, value in data.items():
        if key in profile:
            profile[key] = value
    bi = profile.get("basic_info") or {}
    for k, v in EMPTY_PROFILE["basic_info"].items():
        bi.setdefault(k, v)
    profile["basic_info"] = bi
    return profile


# ── Fallback regex extractor (original behavior) ─────────────────────────────
def field(text: str, *names: str) -> str:
    for name in names:
        match = re.search(rf"(?im)^\s*-?\s*{re.escape(name)}\s*[:：]\s*(.+)$", text)
        if match:
            return match.group(1).strip() or "XX"
    return "XX"


def normalize_profile_regex(text: str) -> dict:
    profile = json.loads(json.dumps(EMPTY_PROFILE))
    profile["basic_info"].update(
        {
            "name": field(text, "Name", "姓名"),
            "email": field(text, "Email", "邮箱"),
            "phone": field(text, "Phone", "电话"),
            "location": field(text, "Location", "所在地", "城市"),
            "target_direction": field(text, "Target direction", "目标方向"),
        }
    )
    return profile


def build_fact_index(profile: dict, source_file: str) -> dict:
    """Flatten profile into traceable facts so writers cannot invent claims."""
    facts = []
    fid = 0

    def add(text: str, category: str) -> None:
        nonlocal fid
        text = (text or "").strip()
        if not text or text == "XX":
            return
        fid += 1
        facts.append(
            {
                "fact_id": f"f{fid:03d}",
                "category": category,
                "fact_text": text,
                "source_file": source_file,
                "confidence": "stated",
                "can_use_in_resume": True,
            }
        )

    bi = profile.get("basic_info", {})
    for k in ("name", "email", "phone", "location", "target_direction"):
        add(bi.get(k, ""), f"basic_info.{k}")
    for e in profile.get("education", []):
        add(" ".join(str(e.get(x, "")) for x in ("school", "degree", "major", "start", "end")).strip(), "education")
    for s in profile.get("skills", []):
        add(str(s), "skill")
    for p in profile.get("projects", []):
        add(str(p.get("name", "")), "project.name")
        add(str(p.get("description", "")), "project.description")
        for h in p.get("highlights", []):
            add(str(h), "project.highlight")
    for it in profile.get("internships", []):
        add(str(it.get("company", "")) + " " + str(it.get("role", "")), "internship")
        add(str(it.get("description", "")), "internship.description")
        for h in it.get("highlights", []):
            add(str(h), "internship.highlight")
    for a in profile.get("awards", []):
        add(str(a), "award")
    for c in profile.get("certifications", []):
        add(str(c), "certification")
    return {"source_file": source_file, "facts": facts}


def normalize_profile(profile_md: Path) -> Path:
    text = profile_md.read_text(encoding="utf-8-sig")
    used = "llm"
    try:
        profile = normalize_profile_llm(text)
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] LLM extraction failed ({exc}); falling back to regex", file=sys.stderr)
        profile = normalize_profile_regex(text)
        used = "regex"

    output = profile_md.with_name("profile.json")
    output.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    fact_index = build_fact_index(profile, profile_md.name)
    fi_path = profile_md.with_name("fact_index.json")
    fi_path.write_text(json.dumps(fact_index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"[info] profile extraction via {used}; {len(fact_index['facts'])} facts", file=sys.stderr)
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Normalize profile markdown into profile.json")
    parser.add_argument("--profile-md", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        output = normalize_profile(Path(args.profile_md).resolve())
        print(output.resolve())
        return 0
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
