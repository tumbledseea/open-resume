#!/usr/bin/env python
"""CLI entry point for Resume Agent.

Usage:
    python resume_agent/cli.py generate --person-dir person --company 字节 --role "AI Agent" --jd-text "JD内容"
    python resume_agent/cli.py compile --project projects/xxx
    python resume_agent/cli.py chat --jd-text "JD内容"
    python resume_agent/cli.py chat --once "你好" --jd-text "JD内容"
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# ── Load .env from repo root (if present) ────────────────────────────────────
def _load_dotenv() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if key and key not in os.environ:  # never overwrite shell-set vars
            os.environ[key] = val

_load_dotenv()

# Windows GBK terminal compat: strip emoji for safe printing
_OUT = sys.stdout
if hasattr(_OUT, "encoding") and _OUT.encoding and _OUT.encoding.upper() in ("GBK", "GB2312", "CP936"):
    import re as _re
    _EMOJI_STRIP = _re.compile(r"[^\x00-\x7F一-鿿　-〿＀-￯ -⁯]")
    def _safe_print(*args, **kwargs):
        text = " ".join(str(a) for a in args)
        text = _EMOJI_STRIP.sub("", text)
        print(text, **kwargs)
else:
    def _safe_print(*args, **kwargs):
        print(*args, **kwargs)

# Ensure resume_agent is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from resume_agent.engine.query_engine import EngineRequest, ResumeQueryEngine
from resume_agent.tools.base import ToolPermission


def cmd_generate(args: argparse.Namespace) -> int:
    engine = ResumeQueryEngine(repo_root=REPO_ROOT)
    project_dir = _resolve(args.project_dir or REPO_ROOT / "projects" / _ts_name())

    jd_text = args.jd_text or _read_file(args.jd_file)

    response = engine.submit_message(
        EngineRequest(
            message=args.message or "生成简历",
            profile_file=_resolve(args.profile_file),
            project_dir=project_dir,
            company=args.company,
            role=args.role,
            jd_text=jd_text,
            jd_url=args.jd_url,
        )
    )
    _print_response(response)
    return 0 if response.status == "completed" else 1


def cmd_compile(args: argparse.Namespace) -> int:
    engine = ResumeQueryEngine(repo_root=REPO_ROOT)
    response = engine.submit_message(
        EngineRequest(
            message="编译导出",
            project_dir=_resolve(args.project),
        )
    )
    _print_response(response)
    return 0 if response.status == "completed" else 1


def _prompt_input() -> str | None:
    """Read user input, supporting multi-line paste.

    - Short single-line message: just type and press Enter.
    - Multi-line paste (e.g. JD text): paste content, then type ``.`` on its
      own line to submit.  Each continuation line shows ``  `` instead of ``> ``.
    Returns ``None`` on EOF, or the joined text (stripped).
    """
    try:
        first = input("> ")
    except EOFError:
        print()
        return None
    text = first.strip()
    # If the user typed a dot on a blank line, that's a request to paste
    if text == ".":
        lines: list[str] = []
        while True:
            try:
                line = input("  ")
            except EOFError:
                break
            if line.strip() == ".":
                break
            lines.append(line)
        return "\n".join(lines).strip()
    return text


def cmd_chat(args: argparse.Namespace) -> int:
    allowed_permissions = {ToolPermission.READ, ToolPermission.WORKSPACE_WRITE, ToolPermission.EXPORT}
    if args.allow_network:
        allowed_permissions.add(ToolPermission.NETWORK)

    engine = ResumeQueryEngine(
        repo_root=REPO_ROOT,
        allowed_permissions=allowed_permissions,
        max_turns=args.max_turns,
    )
    project_dir = _resolve(args.project_dir or REPO_ROOT / "projects" / _ts_name("chat"))

    # Read JD file once at startup (used as seed on first turn)
    seed_jd_text = args.jd_text or _read_file(args.jd_file)

    history: list[dict] = []

    def submit(text: str, include_seed_jd: bool) -> int:
        response = engine.submit_message(
            EngineRequest(
                message=text,
                profile_file=_resolve(args.profile_file),
                project_dir=project_dir,
                company=args.company,
                role=args.role,
                jd_text=seed_jd_text if include_seed_jd else None,
                jd_url=args.jd_url if include_seed_jd else None,
                history=list(history),
            )
        )
        _safe_print(f"[agent] {response.message}")
        if response.changed_files:
            _safe_print("[agent] changed files:")
            for path in response.changed_files:
                _safe_print(f"  - {path}")
        if response.warnings:
            _safe_print("[agent] warnings:")
            for warning in response.warnings:
                _safe_print(f"  ! {warning}")
        history.append({"role": "user", "content": text})
        history.append({"role": "assistant", "content": response.message})
        return 0 if response.status == "completed" else 1

    if args.once:
        return submit(args.once, include_seed_jd=True)

    _safe_print("[agent] OpenResume chat started. 输入 exit / quit 结束。")
    _safe_print("[agent] 多行文本粘贴：直接粘贴内容，然后在单独一行输入 . 提交。")
    _safe_print(f"[agent] project_dir={project_dir}")
    first_turn = True
    while True:
        text = _prompt_input()
        if text is None:  # EOF
            return 0
        if text.lower() in {"exit", "quit", ":q"}:
            return 0
        if not text:
            continue
        code = submit(text, include_seed_jd=first_turn)
        first_turn = False
        if code != 0:
            return code


def cmd_list_tools(args: argparse.Namespace) -> int:
    from resume_agent.tools.builtins import create_builtin_registry

    registry = create_builtin_registry(REPO_ROOT)
    perms = {ToolPermission.READ, ToolPermission.WORKSPACE_WRITE, ToolPermission.NETWORK, ToolPermission.EXPORT}
    print("Available tools:")
    for t in registry.available_tools(perms):
        print(f"  {t.name:30s}  {t.permission.value:20s}  {'R' if t.read_only else 'W'}")
    return 0


def _read_file(path_str: str | None) -> str | None:
    """Read text from a file path, returning None if the path is empty or missing."""
    if not path_str:
        return None
    path = Path(path_str)
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8-sig")


def _resolve(path_str: str | None) -> Path | None:
    if not path_str:
        return None
    p = Path(path_str)
    return p.resolve() if p.is_absolute() else (REPO_ROOT / p).resolve()


def _ts_name(prefix: str = "resume") -> str:
    from datetime import datetime
    return datetime.now().strftime(f"{prefix}_%Y%m%d_%H%M%S")


def _print_response(response) -> None:
    _safe_print(f"\nStatus: {response.status}")
    _safe_print(f"Intent: {response.intent}")
    _safe_print(f"Message: {response.message}")
    if response.changed_files:
        _safe_print("Files changed:")
        for f in response.changed_files:
            _safe_print(f"  - {f}")
    if response.warnings:
        _safe_print("Warnings:")
        for w in response.warnings:
            _safe_print(f"  ! {w}")


def cmd_pipeline(args: argparse.Namespace) -> int:
    from resume_agent.engine.pipeline import PipelineInput, ResumePipeline

    jd_text = args.jd_text or _read_file(args.jd_file) or ""
    project_dir = _resolve(args.project_dir) or REPO_ROOT / "projects" / _ts_name("pipeline")

    pipeline_input = PipelineInput(
        project_dir=str(project_dir),
        profile_file=str(_resolve(args.profile_file)) if args.profile_file else "",
        company=args.company or "",
        role=args.role or "",
        jd_text=jd_text,
        jd_url=args.jd_url or "",
        search_query=args.search_query or "",
        location=args.location or "",
        allow_network=args.allow_network,
        compile_pdf=args.compile,
        min_match_score=args.min_match_score,
        enable_boss=args.enable_boss,
        auto_select_job=args.auto_select,
        template_id=args.template or "",
    )

    pipeline = ResumePipeline(repo_root=REPO_ROOT)
    result = pipeline.run(pipeline_input)

    _safe_print(f"\nPipeline status: {result.status}")
    _safe_print(f"Phases ({len(result.phases)}):")
    for phase in result.phases:
        icon = {"ok": "[ok]", "failed": "[FAIL]", "skipped": "[skip]", "needs_user_input": "[wait]"}.get(phase.status.value, "[?]")
        _safe_print(f"  {icon} {phase.name} ({phase.duration_s:.1f}s){': ' + phase.error if phase.error else ''}")

    if result.warnings:
        _safe_print("\nWarnings:")
        for w in result.warnings:
            _safe_print(f"  ! {w}")

    if result.next_actions:
        _safe_print("\nNext actions:")
        for a in result.next_actions:
            _safe_print(f"  -> {a}")

    if result.outputs:
        _safe_print("\nOutputs:")
        for k, v in sorted(result.outputs.items()):
            _safe_print(f"  {k}: {v}")

    return 0 if result.status == "completed" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Resume Agent CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="Generate a resume from person data + JD")
    gen.add_argument("--profile-file", help="Path to user's profile/background file (e.g. person/mytest_1.md)")
    gen.add_argument("--project-dir", help="Output project directory (auto if omitted)")
    gen.add_argument("--company", default="XX")
    gen.add_argument("--role", default="XX")
    gen.add_argument("--jd-text", help="Job description text")
    gen.add_argument("--jd-file", help="Path to a file containing JD text")
    gen.add_argument("--jd-url", help="Job description URL")
    gen.add_argument("--message", default="生成简历")
    gen.set_defaults(func=cmd_generate)

    comp = sub.add_parser("compile", help="Compile existing project to PDF")
    comp.add_argument("--project", required=True, help="Project directory")
    comp.set_defaults(func=cmd_compile)

    chat = sub.add_parser("chat", help="Start an interactive LLM-driven resume agent chat")
    chat.add_argument("--profile-file", help="Path to user's profile/background file (e.g. person/mytest_1.md)")
    chat.add_argument("--project-dir", help="Output project directory (auto if omitted)")
    chat.add_argument("--company", default="XX")
    chat.add_argument("--role", default="XX")
    chat.add_argument("--jd-text", help="Optional seed JD text for the first turn")
    chat.add_argument("--jd-file", help="Path to a file containing JD text (read at startup)")
    chat.add_argument("--jd-url", help="Optional seed JD URL for the first turn")
    chat.add_argument("--allow-network", action="store_true", help="Allow network tools such as fetch_jd_url")
    chat.add_argument("--max-turns", type=int, default=12, help="Maximum model/tool loop turns per user message")
    chat.add_argument("--once", help="Run one chat turn and exit, useful for scripts/tests")
    chat.set_defaults(func=cmd_chat)

    sub.add_parser("tools", help="List registered tools").set_defaults(func=cmd_list_tools)

    pipe = sub.add_parser("pipeline", help="Run the full deterministic resume generation pipeline")
    pipe.add_argument("--profile-file", help="Path to user profile/background file")
    pipe.add_argument("--project-dir", help="Output project directory (auto if omitted)")
    pipe.add_argument("--company", default="")
    pipe.add_argument("--role", default="")
    pipe.add_argument("--jd-text", help="Job description text (paste directly)")
    pipe.add_argument("--jd-file", help="Path to a file containing JD text")
    pipe.add_argument("--jd-url", help="Job description URL to crawl")
    pipe.add_argument("--search-query", help="Search query to find matching job postings")
    pipe.add_argument("--location", default="", help="City for job search (e.g. 上海)")
    pipe.add_argument("--allow-network", action="store_true", help="Allow network tools (jd_url fetch, job search)")
    pipe.add_argument("--compile", action="store_true", help="Also compile LaTeX to PDF (requires xelatex)")
    pipe.add_argument("--min-match-score", type=int, default=75, help="Minimum match score threshold (default 75)")
    pipe.add_argument("--enable-boss", action="store_true", help="Enable BOSS 直聘 API (requires BOSS_COOKIES)")
    pipe.add_argument("--auto-select", action="store_true", help="Auto-select top search result without asking user")
    pipe.add_argument("--template", help="Template id to render (e.g. red_card, navy_sidebar, teal_clean). Overrides resume_modules.json.")
    pipe.set_defaults(func=cmd_pipeline)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
