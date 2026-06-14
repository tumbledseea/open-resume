from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None  # type: ignore


class ModelConfigError(RuntimeError):
    """Raised when the model client cannot be configured."""


@dataclass(frozen=True)
class ModelToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class ModelResponse:
    content: str = ""
    tool_calls: list[ModelToolCall] = field(default_factory=list)


class ChatModelClient(Protocol):
    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ModelResponse:
        """Return a model message, optionally with tool calls."""


@dataclass(frozen=True)
class ModelConfig:
    api_key: str = field(repr=False)
    model: str
    base_url: str | None = None

    def __repr__(self) -> str:
        base = self.base_url if self.base_url else "default"
        return f"ModelConfig(api_key=<redacted>, model={self.model!r}, base_url={base!r})"


def load_env_file(env_path: Path) -> dict[str, str]:
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


def load_model_config(
    repo_root: Path | str | None = None,
    environ: Mapping[str, str] | None = None,
) -> ModelConfig:
    root = Path(repo_root) if repo_root is not None else Path.cwd()
    process_env = os.environ if environ is None else environ
    file_env = load_env_file(root / ".env")

    api_key = _resolve(("OPENAI_API_KEY", "API_KEY"), process_env, file_env)
    base_url = _resolve(("OPENAI_BASE_URL", "BASE_URL"), process_env, file_env)
    model = _resolve(("OPENAI_MODEL", "MODEL_NAME", "MODEL"), process_env, file_env)

    if not api_key:
        raise ModelConfigError("API key not found: set OPENAI_API_KEY or API_KEY")
    if not model:
        raise ModelConfigError("Model not found: set OPENAI_MODEL, MODEL_NAME, or MODEL")
    return ModelConfig(api_key=api_key, base_url=base_url, model=model)


class OpenAIChatModelClient:
    """OpenAI-compatible Chat Completions client with tool calling."""

    def __init__(
        self,
        config: ModelConfig | None = None,
        repo_root: Path | str | None = None,
        client: Any | None = None,
        temperature: float = 0.2,
    ) -> None:
        self.config = config or load_model_config(repo_root=repo_root)
        self.temperature = temperature
        if client is not None:
            self.client = client
        else:
            if OpenAI is None:
                raise ModelConfigError("openai package not installed (pip install openai)")
            kwargs: dict[str, Any] = {"api_key": self.config.api_key}
            if self.config.base_url:
                kwargs["base_url"] = self.config.base_url
            self.client = OpenAI(**kwargs)

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ModelResponse:
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        response = self.client.chat.completions.create(**kwargs)
        message = _first_message(response)
        return ModelResponse(
            content=str(_get(message, "content") or ""),
            tool_calls=_parse_tool_calls(_get(message, "tool_calls") or []),
        )


def extract_json_object(text: str) -> dict:
    stripped = _strip_code_fence(text.strip())
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        value = json.loads(stripped[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


def _first_message(response: Any) -> Any:
    choices = _get(response, "choices")
    if not choices:
        raise ModelConfigError("model response did not contain choices")
    first = choices[0]
    message = _get(first, "message")
    if message is None:
        raise ModelConfigError("model response did not contain a message")
    return message


def _parse_tool_calls(raw_calls: Any) -> list[ModelToolCall]:
    calls: list[ModelToolCall] = []
    for raw in raw_calls:
        function = _get(raw, "function") or {}
        name = str(_get(function, "name") or "")
        if not name:
            continue
        arguments = _get(function, "arguments") or "{}"
        if isinstance(arguments, str):
            try:
                input_data = json.loads(arguments or "{}")
            except json.JSONDecodeError:
                input_data = {}
        elif isinstance(arguments, dict):
            input_data = arguments
        else:
            input_data = {}
        calls.append(
            ModelToolCall(
                id=str(_get(raw, "id") or f"tool_call_{len(calls) + 1}"),
                name=name,
                input=input_data if isinstance(input_data, dict) else {},
            )
        )
    return calls


def _get(value: Any, key: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(key)
    return getattr(value, key, None)


def _resolve(
    names: tuple[str, ...],
    process_env: Mapping[str, str],
    file_env: Mapping[str, str],
) -> str | None:
    for name in names:
        value = process_env.get(name)
        if value:
            return value
    for name in names:
        value = file_env.get(name)
        if value:
            return value
    return None


def _strip_code_fence(text: str) -> str:
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if len(lines) >= 2 and lines[0].startswith("```"):
        if lines[-1].strip().startswith("```"):
            return "\n".join(lines[1:-1]).strip()
        return "\n".join(lines[1:]).strip()
    return text
