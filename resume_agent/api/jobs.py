"""In-process job runner for long-running pipeline executions.

The pipeline takes minutes (real LLM + crawl + compile), so the HTTP layer
cannot run it synchronously inside a request. This module runs each pipeline
in a background thread and tracks live status. The orchestrator already writes
``checks/pipeline_report.json`` incrementally, so progress is observable from
disk too, but we also keep an in-memory record for fast polling.

State lives only in this process — restarting the server forgets running jobs.
That is acceptable for a local single-user tool; artifacts persist on disk.
"""

from __future__ import annotations

import threading
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from resume_agent.engine.pipeline import PipelineInput, PipelineResult, ResumePipeline


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Job:
    job_id: str
    project_dir: str
    status: str = "queued"  # queued | running | completed | needs_user_input | failed | error
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    phases: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    outputs: dict[str, str] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "project_dir": self.project_dir,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "phases": self.phases,
            "warnings": self.warnings,
            "next_actions": self.next_actions,
            "outputs": self.outputs,
            "error": self.error,
        }


class JobRunner:
    """Runs pipelines on background threads and tracks their state."""

    def __init__(self, repo_root: Path) -> None:
        self._repo_root = Path(repo_root).resolve()
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            return [job.to_dict() for job in self._jobs.values()]

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def start(self, pipeline_input: PipelineInput) -> Job:
        job_id = uuid.uuid4().hex[:12]
        job = Job(job_id=job_id, project_dir=str(pipeline_input.project_dir))
        with self._lock:
            self._jobs[job_id] = job
        thread = threading.Thread(
            target=self._run,
            args=(job, pipeline_input),
            name=f"pipeline-{job_id}",
            daemon=True,
        )
        thread.start()
        return job

    # ── internals ─────────────────────────────────────────────────────────────

    def _update(self, job: Job, **fields: Any) -> None:
        with self._lock:
            for key, value in fields.items():
                setattr(job, key, value)
            job.updated_at = _now_iso()

    def _run(self, job: Job, pipeline_input: PipelineInput) -> None:
        self._update(job, status="running")
        try:
            pipeline = ResumePipeline(repo_root=self._repo_root)
            result: PipelineResult = pipeline.run(pipeline_input)
            self._update(
                job,
                status=result.status,
                phases=[p.to_dict() for p in result.phases],
                warnings=list(result.warnings),
                next_actions=list(result.next_actions),
                outputs=dict(result.outputs),
            )
        except Exception as exc:  # noqa: BLE001
            self._update(
                job,
                status="error",
                error=f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}",
            )
