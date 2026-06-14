from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class ResumeStage(str, Enum):
    COLLECT_PROFILE = "collect_profile"
    IMPORT_PROFILE = "import_profile"
    NORMALIZE_PROFILE = "normalize_profile"
    FETCH_JD = "fetch_jd"
    ANALYZE_JD = "analyze_jd"
    BUILD_STRATEGY = "build_strategy"
    GENERATE_MODULES = "generate_modules"
    RENDER_LATEX = "render_latex"
    DRAFT_RESUME = "draft_resume"
    GENERATE_LATEX = "generate_latex"
    COMPILE_PDF = "compile_pdf"
    REVIEW = "review"
    DONE = "done"


@dataclass
class ResumeSessionState:
    project_dir: Path
    profile_file: Path | None = None
    stage: ResumeStage = ResumeStage.COLLECT_PROFILE
    company: str = "XX"
    role: str = "XX"
    changed_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_dir": str(self.project_dir.resolve()),
            "profile_file": str(self.profile_file.resolve()) if self.profile_file else "",
            "stage": self.stage.value,
            "company": self.company,
            "role": self.role,
            "changed_files": list(self.changed_files),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], project_dir: Path) -> "ResumeSessionState":
        raw_stage = str(data.get("stage") or ResumeStage.COLLECT_PROFILE.value)
        try:
            stage = ResumeStage(raw_stage)
        except ValueError:
            stage = ResumeStage.COLLECT_PROFILE

        raw_profile_file = str(data.get("profile_file") or "")
        profile_file = Path(raw_profile_file).resolve() if raw_profile_file else None
        changed_files = data.get("changed_files", [])
        if not isinstance(changed_files, list):
            changed_files = []

        return cls(
            project_dir=project_dir.resolve(),
            profile_file=profile_file,
            stage=stage,
            company=str(data.get("company") or "XX"),
            role=str(data.get("role") or "XX"),
            changed_files=[str(item) for item in changed_files],
        )
