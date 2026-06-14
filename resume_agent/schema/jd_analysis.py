from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from jsonschema import Draft7Validator


JD_ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "company",
        "role",
        "keywords",
        "key_requirements",
        "nice_to_have",
        "analysis_summary",
    ],
    "additionalProperties": True,
    "properties": {
        "company": {"type": "string"},
        "role": {"type": "string"},
        "mode": {"type": "string"},
        "keywords": {
            "type": "array",
            "maxItems": 20,
            "items": {"type": "string"},
        },
        "key_requirements": {
            "type": "array",
            "maxItems": 8,
            "items": {"type": "string"},
        },
        "nice_to_have": {
            "type": "array",
            "maxItems": 8,
            "items": {"type": "string"},
        },
        "analysis_summary": {"type": "string"},
        "confidence_score": {
            "type": "number",
            "minimum": 0,
            "maximum": 100,
        },
        "hard_requirements": {
            "type": "array",
            "items": {"type": "string"},
        },
        "preferred_requirements": {
            "type": "array",
            "items": {"type": "string"},
        },
        "tools_and_technologies": {
            "type": "array",
            "items": {"type": "string"},
        },
        "business_domain": {
            "type": "array",
            "items": {"type": "string"},
        },
        "resume_implications": {
            "type": "array",
            "items": {"type": "string"},
        },
        "risks_or_gaps": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
}


@dataclass(frozen=True)
class JDAnalysisValidationError(ValueError):
    messages: tuple[str, ...]

    def __str__(self) -> str:
        return "; ".join(self.messages)


def validate_jd_analysis(data: Any) -> None:
    messages = jd_analysis_validation_errors(data)
    if messages:
        raise JDAnalysisValidationError(tuple(messages))


def jd_analysis_validation_errors(data: Any) -> list[str]:
    if not isinstance(data, Mapping):
        return [f"<root>: expected object, got {type(data).__name__}"]

    validator = Draft7Validator(JD_ANALYSIS_SCHEMA)
    messages: list[str] = []
    for error in sorted(validator.iter_errors(data), key=lambda item: list(item.path)):
        location = ".".join(str(part) for part in error.path) or "<root>"
        messages.append(f"{location}: {error.message}")
    return messages


def normalize_jd_analysis(data: Mapping[str, Any]) -> dict[str, Any]:
    """Return a canonical JD analysis while preserving backward-compatible aliases."""
    keywords = _string_list(data.get("keywords"))[:20]
    key_requirements = _string_list(data.get("key_requirements"))[:8]
    nice_to_have = _string_list(data.get("nice_to_have"))[:8]

    hard_requirements = _string_list(data.get("hard_requirements")) or key_requirements
    preferred_requirements = _string_list(data.get("preferred_requirements")) or nice_to_have
    tools = _string_list(data.get("tools_and_technologies")) or keywords

    normalized: dict[str, Any] = {
        "company": str(data.get("company") or "").strip(),
        "role": str(data.get("role") or "").strip(),
        "mode": str(data.get("mode") or "targeted").strip() or "targeted",
        "keywords": keywords,
        "key_requirements": key_requirements,
        "nice_to_have": nice_to_have,
        "analysis_summary": str(data.get("analysis_summary") or "").strip(),
        "hard_requirements": hard_requirements,
        "preferred_requirements": preferred_requirements,
        "tools_and_technologies": tools,
        "business_domain": _string_list(data.get("business_domain")),
        "resume_implications": _string_list(data.get("resume_implications")),
        "risks_or_gaps": _string_list(data.get("risks_or_gaps")),
    }

    if "confidence_score" in data:
        normalized["confidence_score"] = _clamp_score(data.get("confidence_score"))

    return normalized


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _clamp_score(value: Any) -> int:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0
    return int(max(0, min(100, round(parsed))))
