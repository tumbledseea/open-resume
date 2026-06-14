from __future__ import annotations

import re


ALLOWED_MEMORY_TYPES = {
    "user_profile",
    "feedback",
    "project",
    "company_preference",
    "writing_style",
    "resume_version_note",
}

PROFILE_FACT_TYPES = {"education", "experience", "project_experience", "skills", "awards"}
SECRET_PATTERNS = [
    re.compile(r"(?i)\b[A-Z0-9_]*(api[_-]?key|secret|token|password)[A-Z0-9_]*\b\s*="),
    re.compile(r"\bsk-[A-Za-z0-9_-]{6,}"),
]


class MemoryPolicyError(ValueError):
    """Raised when a memory write violates persistence policy."""


def validate_memory_write(memory_type: str, text: str, tags: list[str] | tuple[str, ...]) -> None:
    normalized_type = memory_type.strip()
    if normalized_type in PROFILE_FACT_TYPES or normalized_type not in ALLOWED_MEMORY_TYPES:
        raise MemoryPolicyError(
            f"memory_type must be one of {sorted(ALLOWED_MEMORY_TYPES)}; "
            "profile facts belong in profile.json/fact_index.json"
        )
    if not text.strip():
        raise MemoryPolicyError("memory text is required")
    if _contains_secret(text):
        raise MemoryPolicyError("memory text appears to contain a secret")
    for tag in tags:
        if not str(tag).strip():
            raise MemoryPolicyError("memory tags cannot be empty")


def _contains_secret(text: str) -> bool:
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)
