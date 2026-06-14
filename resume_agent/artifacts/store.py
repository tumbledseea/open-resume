from __future__ import annotations

import difflib
import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from resume_agent.tools.base import ToolExecutionError


DEFAULT_ARTIFACT_PATHS = (
    "profile/profile.md",
    "profile/profile.json",
    "profile/fact_index.json",
    "jd/jd_raw.md",
    "jd/jd_analysis.md",
    "strategy/resume_strategy.md",
    "strategy/spec_lock.json",
    "drafts/resume.md",
    "latex/resume_modules.json",
    "latex/resume.tex",
    "latex/template1.cls",
    "exports/resume.md",
    "exports/resume.pdf",
    "checks/truthfulness_report.json",
    "checks/ats_report.json",
    "checks/match_report.json",
    "checks/match_trend.json",
    "checks/export_quality.json",
    "state.json",
)


@dataclass(frozen=True)
class ArtifactSnapshot:
    version_id: str
    version_dir: Path
    metadata_path: Path
    files: tuple[dict[str, Any], ...]


def snapshot_artifacts(
    project_dir: Path,
    paths: list[str] | None = None,
    reason: str = "",
) -> ArtifactSnapshot:
    project = project_dir.resolve()
    project.mkdir(parents=True, exist_ok=True)
    requested = paths if paths is not None else list(DEFAULT_ARTIFACT_PATHS)
    explicit = paths is not None
    version_id = _new_version_id()
    version_dir = project / "versions" / version_id
    files: list[dict[str, Any]] = []

    for raw_path in requested:
        relative = _safe_relative_path(project, raw_path)
        source = project / relative
        if not source.is_file():
            if explicit:
                raise ToolExecutionError(f"artifact not found: {relative.as_posix()}")
            continue
        target = version_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        files.append(
            {
                "path": relative.as_posix(),
                "snapshot_path": str(target.resolve()),
                "size": source.stat().st_size,
                "sha256": _sha256(source),
            }
        )

    version_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = version_dir / "metadata.json"
    metadata = {
        "version_id": version_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "files": files,
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return ArtifactSnapshot(
        version_id=version_id,
        version_dir=version_dir,
        metadata_path=metadata_path,
        files=tuple(files),
    )


def diff_artifact(project_dir: Path, version_id: str, path: str) -> dict[str, Any]:
    project = project_dir.resolve()
    relative = _safe_relative_path(project, path)
    snapshot_path = _version_dir(project, version_id) / relative
    current_path = project / relative
    if not snapshot_path.is_file():
        raise ToolExecutionError(f"snapshot artifact not found: {relative.as_posix()}")
    if not current_path.is_file():
        raise ToolExecutionError(f"current artifact not found: {relative.as_posix()}")

    before = snapshot_path.read_text(encoding="utf-8-sig", errors="replace").splitlines(keepends=True)
    after = current_path.read_text(encoding="utf-8-sig", errors="replace").splitlines(keepends=True)
    diff = "".join(
        difflib.unified_diff(
            before,
            after,
            fromfile=f"versions/{version_id}/{relative.as_posix()}",
            tofile=relative.as_posix(),
        )
    )
    return {
        "path": relative.as_posix(),
        "version_id": version_id,
        "has_changes": bool(diff),
        "diff": diff,
    }


def rollback_artifact(project_dir: Path, version_id: str, path: str) -> dict[str, Any]:
    project = project_dir.resolve()
    relative = _safe_relative_path(project, path)
    snapshot_path = _version_dir(project, version_id) / relative
    target_path = project / relative
    if not snapshot_path.is_file():
        raise ToolExecutionError(f"snapshot artifact not found: {relative.as_posix()}")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(snapshot_path, target_path)
    return {
        "rolled_back": relative.as_posix(),
        "version_id": version_id,
        "outputs": {"artifact": str(target_path.resolve())},
    }


def _safe_relative_path(project_dir: Path, value: str) -> Path:
    path = Path(value)
    resolved = path.resolve() if path.is_absolute() else (project_dir / path).resolve()
    try:
        relative = resolved.relative_to(project_dir)
    except ValueError as exc:
        raise ToolExecutionError(f"artifact path is outside project: {value}") from exc
    if relative == Path("."):
        raise ToolExecutionError("artifact path must point to a file")
    return relative


def _version_dir(project_dir: Path, version_id: str) -> Path:
    safe_id = version_id.strip()
    if not safe_id or any(char in safe_id for char in "\\/:"):
        raise ToolExecutionError(f"invalid version_id: {version_id}")
    version_dir = project_dir / "versions" / safe_id
    if not version_dir.is_dir():
        raise ToolExecutionError(f"version not found: {version_id}")
    return version_dir


def _new_version_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{stamp}_{uuid4().hex[:8]}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()
