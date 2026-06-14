"""FastAPI backend for OpenResume.

Exposes the deterministic resume pipeline, template listing, artifact reads,
and PDF download over HTTP, and serves the static frontend.

Run locally::

    pip install fastapi uvicorn
    python -m resume_agent.api.server          # or: uvicorn resume_agent.api.server:app

Then open http://127.0.0.1:8000 .

Security note: this binds to localhost and has NO authentication. It is a
local single-user tool. Do not expose it to a public network — the pipeline
can read profile files and trigger outbound network crawls.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel, Field
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "FastAPI is not installed. Run: pip install fastapi uvicorn"
    ) from exc

from resume_agent.api.jobs import JobRunner
from resume_agent.engine.pipeline import PipelineInput


REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECTS_ROOT = REPO_ROOT / "projects"
TEMPLATES_ROOT = REPO_ROOT / "skills" / "resume-master" / "examples"
FRONTEND_DIR = Path(__file__).resolve().parent / "static"


# ── env loading (mirror cli.py so the API has the same LLM/Firecrawl config) ──
def _load_dotenv() -> None:
    import os

    env_path = REPO_ROOT / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if key and key not in os.environ:
            os.environ[key] = val


_load_dotenv()

app = FastAPI(title="OpenResume API", version="1.0")
runner = JobRunner(repo_root=REPO_ROOT)


# ── request models ────────────────────────────────────────────────────────────
class PipelineRequest(BaseModel):
    profile_file: str = Field("", description="Path to profile/background file, relative to repo root or absolute")
    company: str = ""
    role: str = ""
    jd_text: str = ""
    jd_url: str = ""
    search_query: str = ""
    location: str = ""
    template_id: str = ""
    allow_network: bool = False
    compile_pdf: bool = False
    min_match_score: int = 75
    auto_select_job: bool = True
    enable_boss: bool = False
    project_name: str = Field("", description="Optional project folder name under projects/")


# ── helpers ────────────────────────────────────────────────────────────────────
def _resolve_under_repo(path_str: str) -> Path:
    p = Path(path_str)
    resolved = (p if p.is_absolute() else (REPO_ROOT / p)).resolve()
    return resolved


def _ensure_inside(base: Path, target: Path) -> None:
    """Reject path traversal outside the allowed base directory."""
    try:
        target.relative_to(base.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="path escapes allowed directory")


def _ts_name() -> str:
    # Avoid importing datetime.now at module import; fine to call per-request.
    from datetime import datetime

    return datetime.now().strftime("web_%Y%m%d_%H%M%S")


# ── routes ──────────────────────────────────────────────────────────────────────
@app.get("/api/health")
def health() -> dict[str, Any]:
    from resume_agent.model.openai_client import ModelConfigError, load_model_config

    try:
        cfg = load_model_config(repo_root=REPO_ROOT)
        llm = {"configured": True, "model": cfg.model}
    except ModelConfigError:
        llm = {"configured": False, "model": None}

    import os

    firecrawl = bool(str(os.environ.get("FIRECRAWL_API_KEY") or "").strip())
    return {"status": "ok", "llm": llm, "firecrawl_configured": firecrawl}


@app.get("/api/templates")
def list_templates() -> dict[str, Any]:
    templates = []
    if TEMPLATES_ROOT.is_dir():
        for d in sorted(TEMPLATES_ROOT.iterdir()):
            manifest = d / "template_manifest.json"
            if not manifest.is_file():
                continue
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            templates.append({
                "template_id": data.get("template_id", d.name),
                "name": data.get("name", d.name),
                "description": data.get("description", ""),
            })
    return {"templates": templates}


@app.post("/api/pipeline")
def start_pipeline(req: PipelineRequest) -> dict[str, Any]:
    project_name = req.project_name.strip() or _ts_name()
    # sanitize: only a single path segment, no separators
    if "/" in project_name or "\\" in project_name or project_name in {".", ".."}:
        raise HTTPException(status_code=400, detail="invalid project_name")
    project_dir = (PROJECTS_ROOT / project_name).resolve()
    _ensure_inside(PROJECTS_ROOT, project_dir)

    profile_file = ""
    if req.profile_file.strip():
        resolved = _resolve_under_repo(req.profile_file.strip())
        if not resolved.is_file():
            raise HTTPException(status_code=400, detail=f"profile_file not found: {req.profile_file}")
        profile_file = str(resolved)

    if not (req.jd_text.strip() or req.jd_url.strip() or req.search_query.strip()):
        raise HTTPException(status_code=400, detail="one of jd_text / jd_url / search_query is required")

    # template_id is threaded through PipelineInput → render_latex, overriding
    # the template_id baked into resume_modules.json (default: red_card).
    pipeline_input = PipelineInput(
        project_dir=str(project_dir),
        profile_file=profile_file,
        company=req.company,
        role=req.role,
        jd_text=req.jd_text,
        jd_url=req.jd_url,
        search_query=req.search_query,
        location=req.location,
        allow_network=req.allow_network,
        compile_pdf=req.compile_pdf,
        min_match_score=req.min_match_score,
        enable_boss=req.enable_boss,
        auto_select_job=req.auto_select_job,
        template_id=req.template_id.strip(),
    )
    job = runner.start(pipeline_input)
    return {"job_id": job.job_id, "project_dir": job.project_dir, "status": job.status}


@app.get("/api/jobs")
def list_jobs() -> dict[str, Any]:
    return {"jobs": runner.list_jobs()}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = runner.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job.to_dict()


@app.get("/api/jobs/{job_id}/artifact")
def get_artifact(job_id: str, name: str) -> JSONResponse:
    """Return a named artifact's content. JSON files are parsed; text returned raw."""
    job = runner.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    path_str = job.outputs.get(name)
    if not path_str:
        raise HTTPException(status_code=404, detail=f"artifact not found: {name}")
    path = Path(path_str).resolve()
    _ensure_inside(PROJECTS_ROOT, path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"artifact file missing: {name}")
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix == ".json":
        try:
            return JSONResponse({"name": name, "kind": "json", "content": json.loads(text)})
        except json.JSONDecodeError:
            pass
    return JSONResponse({"name": name, "kind": "text", "content": text})


@app.get("/api/jobs/{job_id}/pdf")
def get_pdf(job_id: str):
    job = runner.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    pdf_str = job.outputs.get("resume_pdf")
    if not pdf_str:
        raise HTTPException(status_code=404, detail="no PDF produced (was compile enabled?)")
    pdf_path = Path(pdf_str).resolve()
    _ensure_inside(PROJECTS_ROOT, pdf_path)
    if not pdf_path.is_file():
        raise HTTPException(status_code=404, detail="PDF file missing")
    return FileResponse(str(pdf_path), media_type="application/pdf", filename="resume.pdf")


# ── static frontend ──────────────────────────────────────────────────────────────
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="static")
else:  # pragma: no cover

    @app.get("/")
    def _no_frontend() -> HTMLResponse:
        return HTMLResponse("<h1>OpenResume API</h1><p>Frontend not built. See /docs for the API.</p>")


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
