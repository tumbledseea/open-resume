#!/usr/bin/env python
"""Shared LLM client for resume-master scripts.

Reads credentials from the repo-root .env (SiliconFlow / OpenAI-compatible).
Tolerates keys with surrounding spaces and CRLF line endings, and does not
require python-dotenv. Provides complete_json() for structured extraction.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None  # type: ignore


def _find_repo_root(start: Path) -> Path:
    """Walk up until a directory containing .env is found; fall back to start."""
    for parent in [start, *start.parents]:
        if (parent / ".env").is_file():
            return parent
    return start


def load_env(env_path: Path | None = None) -> dict[str, str]:
    """Parse a .env file tolerantly (spaces around '=', CRLF, # comments)."""
    if env_path is None:
        root = _find_repo_root(Path(__file__).resolve())
        env_path = root / ".env"
    env: dict[str, str] = {}
    if not env_path.is_file():
        return env
    for raw in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def _resolve(env: dict[str, str], key: str) -> str | None:
    """Prefer process env, then .env file."""
    return os.environ.get(key) or env.get(key)


class LLMConfigError(RuntimeError):
    pass


def get_client() -> tuple[Any, str]:
    """Return (OpenAI client, model_name). Raises LLMConfigError if unusable."""
    if OpenAI is None:
        raise LLMConfigError("openai package not installed (pip install openai)")
    env = load_env()
    api_key = _resolve(env, "API_KEY") or _resolve(env, "OPENAI_API_KEY")
    base_url = _resolve(env, "BASE_URL") or _resolve(env, "OPENAI_BASE_URL")
    model = _resolve(env, "MODEL_NAME") or _resolve(env, "MODEL")
    if not api_key:
        raise LLMConfigError("API_KEY not found in environment or .env")
    if not model:
        raise LLMConfigError("MODEL_NAME not found in environment or .env")
    client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
    return client, model


def complete_text(system: str, user: str, temperature: float = 0.3) -> str:
    client, model = get_client()
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
    )
    return (resp.choices[0].message.content or "").strip()


def _extract_json(text: str) -> dict[str, Any]:
    """Pull a JSON object out of a model reply, tolerating code fences/prose."""
    text = text.strip()
    if text.startswith("```"):
        # strip ```json ... ``` fence
        inner = text.split("```", 2)
        if len(inner) >= 2:
            body = inner[1]
            if body.lstrip().lower().startswith("json"):
                body = body.lstrip()[4:]
            text = body.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # last resort: slice between first { and last }
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError("model did not return valid JSON")


def complete_json(system: str, user: str, temperature: float = 0.2, retries: int = 1) -> dict[str, Any]:
    """Ask the model for a JSON object. Retries once on parse failure."""
    client, model = get_client()
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        kwargs: dict[str, Any] = dict(model=model, messages=messages, temperature=temperature)
        # Most OpenAI-compatible servers accept this; ignore if unsupported.
        try:
            resp = client.chat.completions.create(response_format={"type": "json_object"}, **kwargs)
        except Exception:
            resp = client.chat.completions.create(**kwargs)
        content = (resp.choices[0].message.content or "").strip()
        try:
            return _extract_json(content)
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": "Return ONLY a valid JSON object, no prose, no code fence."})
    raise ValueError(f"failed to get JSON after {retries + 1} attempts: {last_err}")


def main(argv: list[str] | None = None) -> int:
    """Connectivity self-test: python client.py 'ping'"""
    prompt = (argv or sys.argv[1:] or ["Reply with the single word: pong"])[0]
    try:
        client, model = get_client()
        print(f"model={model}")
        out = complete_text("You are a connectivity test.", prompt)
        print(f"reply={out}")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
