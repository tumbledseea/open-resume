"""Deterministic resume generation pipeline orchestrator.

Executes the full pipeline in fixed phase order, independent of model decisions.
Each phase calls the relevant tool handler directly (no LLM tool-call loop).
"""

from __future__ import annotations

import json
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from resume_agent.tools.base import ToolContext, ToolExecutionError, ToolPermission
from resume_agent.tools.builtins import create_builtin_registry


def _extract_match_score(outputs: dict[str, Any]) -> int:
    """Read the match score from a match_analysis tool result.

    The match_analysis tool returns ``overall_score``; older/other tools may
    use ``match_score``. Accept either so the revise loop triggers correctly.
    """
    for key in ("overall_score", "match_score"):
        if key in outputs and outputs[key] is not None:
            try:
                return int(outputs[key])
            except (TypeError, ValueError):
                continue
    return 0


class PhaseStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    OK = "ok"
    SKIPPED = "skipped"
    FAILED = "failed"
    NEEDS_INPUT = "needs_user_input"


@dataclass
class PipelinePhase:
    name: str
    status: PhaseStatus = PhaseStatus.PENDING
    outputs: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    duration_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "outputs": self.outputs,
            "error": self.error,
            "duration_s": round(self.duration_s, 2),
        }


@dataclass
class PipelineInput:
    project_dir: str
    profile_file: str = ""
    company: str = ""
    role: str = ""
    jd_text: str = ""
    jd_url: str = ""
    search_query: str = ""
    location: str = ""
    allow_network: bool = False
    compile_pdf: bool = True
    min_match_score: int = 75
    max_revise_loops: int = 2
    enable_boss: bool = False
    auto_select_job: bool = False
    template_id: str = ""
    photo_file: str = ""


@dataclass
class PipelineResult:
    status: str  # "completed" | "needs_user_input" | "failed"
    phases: list[PipelinePhase] = field(default_factory=list)
    outputs: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "phases": [p.to_dict() for p in self.phases],
            "outputs": self.outputs,
            "warnings": self.warnings,
            "next_actions": self.next_actions,
        }


class ResumePipeline:
    """Run the full targeted resume pipeline in deterministic phase order."""

    def __init__(self, repo_root: Path | str) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.registry = create_builtin_registry(repo_root=self.repo_root)

    def run(self, pipeline_input: PipelineInput) -> PipelineResult:
        project_dir = Path(pipeline_input.project_dir)
        self._project_dir = project_dir  # saved for _finalize
        ctx = ToolContext(
            workspace=project_dir,
            metadata={
                "project_dir": str(project_dir),
                "allow_network": pipeline_input.allow_network,
                "profile_file": str(pipeline_input.profile_file) if pipeline_input.profile_file else "",
            },
        )
        allowed = {ToolPermission.READ, ToolPermission.WORKSPACE_WRITE}
        if pipeline_input.allow_network:
            allowed.add(ToolPermission.NETWORK)
        if pipeline_input.compile_pdf:
            # compile_pdf is an EXPORT-permissioned tool; grant it only when asked.
            allowed.add(ToolPermission.EXPORT)

        result = PipelineResult(status="running")

        # ── Phase 0: preflight ──────────────────────────────────────────────
        phase = self._run_phase(result, "preflight", lambda: self.registry.execute(
            "pipeline_preflight",
            {
                "project_dir": str(project_dir),
                "profile_file": pipeline_input.profile_file,
                "jd_text": pipeline_input.jd_text,
                "jd_url": pipeline_input.jd_url,
                "search_query": pipeline_input.search_query,
                "company": pipeline_input.company,
                "role": pipeline_input.role,
                "allow_network": pipeline_input.allow_network,
                "compile_pdf": pipeline_input.compile_pdf,
            },
            ctx, allowed,
        ))
        if phase.status == PhaseStatus.FAILED:
            return self._finalize(result, "failed")
        if phase.outputs.get("status") == "needs_user_input":
            result.next_actions = phase.outputs.get("issues", [])
            return self._finalize(result, "needs_user_input")
        result.warnings.extend(phase.outputs.get("warnings", []))

        # ── Phase 1: import_profile ─────────────────────────────────────────
        if pipeline_input.profile_file:
            phase = self._run_phase(result, "import_profile", lambda: self.registry.execute(
                "import_profile",
                {"profile_file": pipeline_input.profile_file, "project_dir": str(project_dir)},
                ctx, allowed,
            ))
            if phase.status == PhaseStatus.FAILED:
                return self._finalize(result, "failed")

        # ── Phase 2: normalize_profile ──────────────────────────────────────
        phase = self._run_phase(result, "normalize_profile", lambda: self.registry.execute(
            "normalize_profile",
            {"project_dir": str(project_dir)},
            ctx, allowed,
        ))
        if phase.status == PhaseStatus.FAILED:
            return self._finalize(result, "failed")

        # ── Phase 3: resolve_target_job ─────────────────────────────────────
        phase = self._run_phase(result, "resolve_target_job", lambda: self.registry.execute(
            "resolve_target_job",
            {
                "project_dir": str(project_dir),
                "jd_text": pipeline_input.jd_text,
                "jd_url": pipeline_input.jd_url,
                "search_query": pipeline_input.search_query,
                "company": pipeline_input.company,
                "role": pipeline_input.role,
                "location": pipeline_input.location,
                "auto_select": pipeline_input.auto_select_job,
                "enable_boss": pipeline_input.enable_boss,
            },
            ctx, allowed,
        ))
        if phase.status == PhaseStatus.FAILED:
            return self._finalize(result, "failed")
        if phase.outputs.get("status") == "needs_user_input":
            result.next_actions = [phase.outputs.get("message", "Select a job and re-run")]
            result.outputs["candidates"] = phase.outputs.get("candidates", [])
            return self._finalize(result, "needs_user_input")

        # ── Phase 4: analyze_jd ─────────────────────────────────────────────
        phase = self._run_phase(result, "analyze_jd", lambda: self.registry.execute(
            "analyze_jd",
            {"project_dir": str(project_dir)},
            ctx, allowed,
        ))
        if phase.status == PhaseStatus.FAILED:
            return self._finalize(result, "failed")

        # ── Phase 5: build_resume_strategy ──────────────────────────────────
        phase = self._run_phase(result, "build_resume_strategy", lambda: self.registry.execute(
            "build_resume_strategy",
            {"project_dir": str(project_dir)},
            ctx, allowed,
        ))
        if phase.status == PhaseStatus.FAILED:
            return self._finalize(result, "failed")

        # ── Phase 6: generate_resume_modules ────────────────────────────────
        phase = self._run_phase(result, "generate_resume_modules", lambda: self.registry.execute(
            "generate_resume_modules",
            {"project_dir": str(project_dir)},
            ctx, allowed,
        ))
        if phase.status == PhaseStatus.FAILED:
            return self._finalize(result, "failed")

        # ── inject photo if provided ────────────────────────────────────────
        # ── post-process resume_modules.json (photo + education ordering) ──
        photo_src = Path(pipeline_input.photo_file).resolve() if pipeline_input.photo_file else None
        if photo_src and photo_src.is_file():
            modules_path = project_dir / "latex" / "resume_modules.json"
            try:
                modules = json.loads(modules_path.read_text(encoding="utf-8"))
                modules.setdefault("header", {})["photo"] = "photo.png"
                shutil.copy2(photo_src, (project_dir / "latex" / "photo.png"))
                modules_path.write_text(json.dumps(modules, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            except Exception as exc:
                result.warnings.append(f"photo injection failed: {exc}")
        elif pipeline_input.photo_file:
            result.warnings.append(f"photo file not found: {pipeline_input.photo_file}")

        # ── reorder education: graduate degrees (985/211/QS100) first ──
        try:
            modules_path = project_dir / "latex" / "resume_modules.json"
            if modules_path.is_file():
                modules = json.loads(modules_path.read_text(encoding="utf-8"))
                for m in modules.get("modules", []):
                    if isinstance(m, dict) and m.get("module_id") == "education":
                        items = m.get("items", [])
                        if len(items) >= 2:
                            ranked = _education_rank(items)
                            items.sort(key=ranked)
                        break
                modules_path.write_text(json.dumps(modules, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except Exception:
            pass  # non-fatal: default ordering is still valid

        # ── Phase 7: render_latex ───────────────────────────────────────────
        render_input: dict[str, Any] = {"project_dir": str(project_dir)}
        if pipeline_input.template_id:
            render_input["template_id"] = pipeline_input.template_id
        phase = self._run_phase(result, "render_latex", lambda: self.registry.execute(
            "render_latex",
            dict(render_input),
            ctx, allowed,
        ))
        if phase.status == PhaseStatus.FAILED:
            return self._finalize(result, "failed")

        # ── Phase 8: compile_pdf (optional) ────────────────────────────────
        if pipeline_input.compile_pdf:
            phase = self._run_phase(result, "compile_pdf", lambda: self.registry.execute(
                "compile_pdf",
                {"project_dir": str(project_dir)},
                ctx, allowed,
            ))
            if phase.status == PhaseStatus.FAILED:
                result.warnings.append("compile_pdf failed — LaTeX may not be installed. Continuing to quality checks.")

        # ── Phase 9: check_truthfulness ─────────────────────────────────────
        phase = self._run_phase(result, "check_truthfulness", lambda: self.registry.execute(
            "check_truthfulness",
            {"project_dir": str(project_dir)},
            ctx, allowed,
        ))
        if phase.status == PhaseStatus.FAILED:
            result.warnings.append("check_truthfulness failed — skipping")

        # ── Phase 10: check_ats ─────────────────────────────────────────────
        phase = self._run_phase(result, "check_ats", lambda: self.registry.execute(
            "check_ats",
            {"project_dir": str(project_dir)},
            ctx, allowed,
        ))
        if phase.status == PhaseStatus.FAILED:
            result.warnings.append("check_ats failed — skipping")

        # ── Phase 11: match_analysis ────────────────────────────────────────
        phase = self._run_phase(result, "match_analysis", lambda: self.registry.execute(
            "match_analysis",
            {"project_dir": str(project_dir)},
            ctx, allowed,
        ))
        match_score = 0
        if phase.status == PhaseStatus.OK:
            match_score = _extract_match_score(phase.outputs)

        # ── Phase 12: revise loop ───────────────────────────────────────────
        revise_count = 0
        while (
            match_score > 0
            and match_score < pipeline_input.min_match_score
            and revise_count < pipeline_input.max_revise_loops
        ):
            revise_count += 1
            phase = self._run_phase(
                result, f"revise_loop_{revise_count}",
                lambda: self.registry.execute(
                    "revise_resume_from_match_report",
                    {"project_dir": str(project_dir)},
                    ctx, allowed,
                )
            )
            if phase.status == PhaseStatus.FAILED:
                break
            # Re-render and re-check
            self._run_phase(result, f"render_latex_{revise_count}", lambda: self.registry.execute(
                "render_latex", dict(render_input), ctx, allowed,
            ))
            self._run_phase(result, f"match_analysis_{revise_count}", lambda: self.registry.execute(
                "match_analysis", {"project_dir": str(project_dir)}, ctx, allowed,
            ))
            last_match = result.phases[-1]
            if last_match.status == PhaseStatus.OK:
                match_score = _extract_match_score(last_match.outputs)

        if match_score > 0 and match_score < pipeline_input.min_match_score:
            result.warnings.append(
                f"match_score={match_score} is below threshold={pipeline_input.min_match_score} "
                f"after {revise_count} revise loop(s)"
            )
            result.next_actions.append(
                f"Consider revising profile content or lowering min_match_score (current: {pipeline_input.min_match_score})"
            )

        # ── Phase 13: pipeline_report ───────────────────────────────────────
        self._write_pipeline_report(project_dir, result)

        # Collect final outputs
        result.outputs.update(self._collect_outputs(project_dir))
        return self._finalize(result, "completed")

    # ── helpers ──────────────────────────────────────────────────────────────

    def _run_phase(self, result: PipelineResult, name: str, fn) -> PipelinePhase:
        phase = PipelinePhase(name=name, status=PhaseStatus.RUNNING)
        result.phases.append(phase)
        t0 = time.monotonic()
        try:
            tool_result = fn()
            phase.outputs = tool_result.content if tool_result.content else {}
            phase.status = PhaseStatus.OK
        except ToolExecutionError as exc:
            phase.error = str(exc)
            phase.status = PhaseStatus.FAILED
        except Exception as exc:  # noqa: BLE001
            phase.error = f"{type(exc).__name__}: {exc}"
            phase.status = PhaseStatus.FAILED
        finally:
            phase.duration_s = time.monotonic() - t0
        return phase

    def _write_pipeline_report(self, project_dir: Path, result: PipelineResult) -> None:
        checks_dir = project_dir / "checks"
        checks_dir.mkdir(parents=True, exist_ok=True)
        report_path = checks_dir / "pipeline_report.json"
        report_path.write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _collect_outputs(self, project_dir: Path) -> dict[str, str]:
        candidates = {
            "profile": project_dir / "profile" / "profile.json",
            "fact_index": project_dir / "profile" / "fact_index.json",
            "jd_raw": project_dir / "jd" / "jd_raw.md",
            "jd_analysis": project_dir / "jd" / "jd_analysis.md",
            "strategy": project_dir / "strategy" / "spec_lock.json",
            "resume_md": project_dir / "drafts" / "resume.md",
            "resume_modules": project_dir / "latex" / "resume_modules.json",
            "resume_tex": project_dir / "latex" / "resume.tex",
            "resume_pdf": project_dir / "exports" / "resume.pdf",
            "truthfulness_report": project_dir / "checks" / "truthfulness_report.json",
            "ats_report": project_dir / "checks" / "ats_report.json",
            "match_report": project_dir / "checks" / "match_report.json",
            "pipeline_report": project_dir / "checks" / "pipeline_report.json",
        }
        return {k: str(v) for k, v in candidates.items() if v.is_file()}

    def _finalize(self, result: PipelineResult, status: str) -> PipelineResult:
        result.status = status
        # Always write the report, even on early exit, so the caller can inspect what happened
        try:
            project_dir = Path(result.phases[0].outputs.get("project_dir", ".")) if result.phases else Path(".")
            # Find project_dir from phase inputs indirectly via the result outputs
            self._write_pipeline_report_to_any_checks_dir(result)
        except Exception:  # noqa: BLE001
            pass
        return result

    def _write_pipeline_report_to_any_checks_dir(self, result: PipelineResult) -> None:
        # Try to locate project_dir from stored pipeline input or phase outputs
        # We keep a reference on self after run() sets it
        if hasattr(self, "_project_dir"):
            self._write_pipeline_report(Path(self._project_dir), result)


# ── education ordering helper ──────────────────────────────────────────

# Schools whose name or badges indicate a highly-ranked institution.
# Detection chain: exact substring match against school name → check item badges.
_PRESTIGE_SCHOOLS = ("985", "211", "双一流", "C9", "九校联盟", "常春藤", "Ivy League",
                      "清华", "北大", "浙大", "复旦", "上交", "南大", "中科大", "国科大",
                      "华东师范", "北京师范", "南开", "天津大学", "华中科技", "武大", "中山", "哈工大",
                      "西安交大", "同济", "北航", "中国人民", "北师大", "东南", "厦门",
                      "Harvard", "MIT", "Stanford", "Oxford", "Cambridge", "ETH", "NUS",
                      "NTU", "Tokyo", "Caltech", "Berkeley", "CMU", "Yale", "Princeton",
                      "Columbia", "UCLA", "Imperial", "Toronto", "McGill", "EPFL")

_QSTOP100_HINTS = ("QS", "qs", "Qs前", "世界排名", "Top 1", "top 1")


def _education_rank(items: list[dict]) -> Callable[[dict], int]:
    """Return a sort key function that puts graduate degrees from prestigious
    schools first.  Lower rank = shown higher on the resume.

    Priority order:
      0 — graduate degree (硕士/博士/Master/PhD) from a 985/211/QS100 school
      1 — graduate degree from any school
      2 — undergraduate degree (本科/Bachelor) or other
      3 — everything else
    """
    def rank(item: dict) -> int:
        school = str(item.get("school", "") or "")
        badges = [str(b).strip() for b in (item.get("badges", []) or [])]
        degree = str(item.get("degree", "") or "")
        combined = school + " " + " ".join(badges)

        is_grad = any(w in degree for w in ("硕士", "博士", "研究生", "Master", "PhD", "Ph.D"))
        is_ug = any(w in degree for w in ("本科", "学士", "Bachelor"))

        prestigious = False
        # 1. explicit badges ("985", "211", "双一流")
        if any(b in badges for b in ("985", "211", "双一流")):
            prestigious = True
        # 2. school name substring match
        if not prestigious:
            for kw in _PRESTIGE_SCHOOLS:
                if kw in combined:
                    prestigious = True
                    break
        # 3. QS top-100 hints
        if not prestigious:
            for hint in _QSTOP100_HINTS:
                if hint in combined:
                    prestigious = True
                    break

        if is_grad and prestigious:
            return 0
        if is_grad:
            return 1
        if is_ug:
            return 2
        return 3

    return rank
