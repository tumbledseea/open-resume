from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Mapping

from resume_agent.tools.base import ToolExecutionError, ToolResult


def resolve_project_dir(repo_root: Path, input_data: Mapping[str, object]) -> Path:
    if input_data.get("project_dir"):
        return resolve_path(repo_root, str(input_data["project_dir"]))
    return repo_root / "projects" / "_default"


def run_script(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    script = scripts_dir(repo_root) / args[0]
    if not script.is_file():
        raise ToolExecutionError(f"missing script: {script}")
    # Force UTF-8 I/O in the child so scripts that print CJK text don't crash
    # with UnicodeEncodeError under Windows' default gbk console codepage.
    child_env = dict(os.environ)
    child_env["PYTHONIOENCODING"] = "utf-8"
    child_env["PYTHONUTF8"] = "1"
    proc = subprocess.run(
        [sys.executable, str(script), *args[1:]],
        cwd=repo_root,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=child_env,
    )
    if proc.returncode != 0:
        message = proc.stderr.strip() or proc.stdout.strip() or f"exit code {proc.returncode}"
        raise ToolExecutionError(f"{args[0]} failed: {message}")
    return proc


def script_result(
    tool_name: str,
    proc: subprocess.CompletedProcess[str],
    outputs: Mapping[str, Path],
) -> ToolResult:
    return ToolResult(
        content={
            "status": "ok",
            "tool": tool_name,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
            "outputs": {name: str(path.resolve()) for name, path in outputs.items()},
        }
    )


def resolve_path(repo_root: Path, value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (repo_root / path).resolve()


def scripts_dir(repo_root: Path) -> Path:
    return repo_root / "skills" / "resume-master" / "scripts"


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]

