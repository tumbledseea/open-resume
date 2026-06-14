from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class StdioMCPServerConfig:
    name: str
    command: str
    args: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MCPConfig:
    servers: tuple[StdioMCPServerConfig, ...] = ()
    job_crawler_backend: str = "builtin"


def load_mcp_config(
    repo_root: Path | str,
    config_path: Path | str | None = None,
    environ: Mapping[str, str] | None = None,
) -> MCPConfig:
    root = Path(repo_root).resolve()
    env = os.environ if environ is None else environ
    path = _config_path(root, config_path, env)
    data = _read_json(path) if path is not None and path.is_file() else {}

    backend = str(
        env.get("OPENRESUME_JOB_CRAWLER_BACKEND")
        or _nested(data, ("job_crawler", "backend"))
        or "builtin"
    ).strip().lower()

    return MCPConfig(
        servers=tuple(_stdio_servers(data)),
        job_crawler_backend=backend or "builtin",
    )


def _config_path(
    repo_root: Path,
    config_path: Path | str | None,
    environ: Mapping[str, str],
) -> Path | None:
    if config_path is not None:
        return Path(config_path).resolve()
    if environ.get("OPENRESUME_MCP_CONFIG"):
        return Path(str(environ["OPENRESUME_MCP_CONFIG"])).resolve()

    candidates = (
        repo_root / ".openresume" / "mcp.json",
        repo_root / "openresume.mcp.json",
    )
    return next((path for path in candidates if path.is_file()), candidates[0])


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _stdio_servers(data: Mapping[str, object]) -> list[StdioMCPServerConfig]:
    raw_servers = data.get("servers", [])
    if not isinstance(raw_servers, list):
        return []

    servers: list[StdioMCPServerConfig] = []
    for raw in raw_servers:
        if not isinstance(raw, Mapping):
            continue
        if str(raw.get("transport") or "stdio") != "stdio":
            continue
        name = str(raw.get("name") or "").strip()
        command = str(raw.get("command") or "").strip()
        if not name or not command:
            continue
        raw_args = raw.get("args", [])
        args = tuple(str(item) for item in raw_args) if isinstance(raw_args, list) else ()
        env = raw.get("env", {})
        servers.append(
            StdioMCPServerConfig(
                name=name,
                command=command,
                args=args,
                env={str(key): str(value) for key, value in env.items()} if isinstance(env, Mapping) else {},
            )
        )
    return servers


def _nested(data: Mapping[str, object], path: tuple[str, ...]) -> object | None:
    value: object = data
    for key in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value
