from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft7Validator


REQUIRED_TEMPLATE1_MODULES = ("education", "experience", "projects", "awards")


@dataclass(frozen=True)
class ResumeModulesValidationError(ValueError):
    messages: tuple[str, ...]

    def __str__(self) -> str:
        return "; ".join(self.messages)


def validate_resume_modules(
    repo_root: Path,
    data: Any,
    required_modules: tuple[str, ...] = REQUIRED_TEMPLATE1_MODULES,
) -> None:
    messages = resume_modules_validation_errors(repo_root, data, required_modules)
    if messages:
        raise ResumeModulesValidationError(tuple(messages))


def resume_modules_validation_errors(
    repo_root: Path,
    data: Any,
    required_modules: tuple[str, ...] = REQUIRED_TEMPLATE1_MODULES,
) -> list[str]:
    if not isinstance(data, Mapping):
        return [f"<root>: expected object, got {type(data).__name__}"]

    schema = _load_schema(repo_root)
    validator = Draft7Validator(schema)
    messages: list[str] = []
    for error in sorted(validator.iter_errors(data), key=lambda item: list(item.path)):
        location = ".".join(str(part) for part in error.path) or "<root>"
        messages.append(f"{location}: {error.message}")

    module_ids = {
        str(module.get("module_id"))
        for module in data.get("modules", [])
        if isinstance(module, Mapping)
    }
    missing = [module_id for module_id in required_modules if module_id not in module_ids]
    if missing:
        messages.append("modules: missing required template1 modules: " + ", ".join(missing))

    return messages


def _load_schema(repo_root: Path) -> dict[str, Any]:
    schema_path = repo_root / "skills" / "resume-master" / "schemas" / "resume_modules.schema.json"
    return json.loads(schema_path.read_text(encoding="utf-8"))

