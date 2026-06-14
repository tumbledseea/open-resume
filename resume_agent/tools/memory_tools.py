from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from resume_agent.memory.policy import MemoryPolicyError
from resume_agent.memory.selector import select_memories
from resume_agent.memory.store import FileMemoryStore, MemoryRecord
from resume_agent.tools.base import FunctionTool, ToolContext, ToolExecutionError, ToolPermission, ToolResult


def create_memory_tools(repo_root: Path) -> list[FunctionTool]:
    return [
        FunctionTool(
            name="save_memory",
            description=(
                "Persist a user preference or feedback memory. "
                "Do not use for resume facts; facts belong in profile.json/fact_index.json."
            ),
            input_schema={
                "type": "object",
                "required": ["memory_type", "text"],
                "properties": {
                    "memory_type": {"type": "string"},
                    "text": {"type": "string"},
                    "tags": {"type": "array"},
                    "metadata": {"type": "object"},
                },
            },
            read_only=False,
            permission=ToolPermission.WORKSPACE_WRITE,
            handler=lambda input_data, context: _save_memory(repo_root, input_data),
        ),
        FunctionTool(
            name="recall_memory",
            description="Recall persisted user preferences or feedback relevant to the current request.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "memory_type": {"type": "string"},
                    "max_results": {"type": "integer"},
                },
            },
            read_only=True,
            permission=ToolPermission.READ,
            handler=lambda input_data, context: _recall_memory(repo_root, input_data),
        ),
    ]


def _save_memory(repo_root: Path, input_data: Mapping[str, Any]) -> ToolResult:
    store = FileMemoryStore(repo_root / "memory")
    try:
        record = store.save(
            memory_type=str(input_data["memory_type"]),
            text=str(input_data["text"]),
            tags=_string_list(input_data.get("tags", [])),
            metadata=_metadata(input_data.get("metadata", {})),
        )
    except MemoryPolicyError as exc:
        raise ToolExecutionError(str(exc)) from exc
    return ToolResult(
        content={
            "status": "ok",
            "memory": _record_payload(record),
            "outputs": {"memory": str(record.path)},
        }
    )


def _recall_memory(repo_root: Path, input_data: Mapping[str, Any]) -> ToolResult:
    store = FileMemoryStore(repo_root / "memory")
    records = store.list(memory_type=str(input_data["memory_type"]) if input_data.get("memory_type") else None)
    selected = select_memories(
        records,
        query=str(input_data.get("query") or ""),
        memory_type=str(input_data["memory_type"]) if input_data.get("memory_type") else None,
        max_results=int(input_data.get("max_results") or 5),
    )
    return ToolResult(
        content={
            "status": "ok",
            "memories": [_record_payload(record) for record in selected],
        }
    )


def _record_payload(record: MemoryRecord) -> dict[str, Any]:
    payload = record.to_dict()
    payload["path"] = str(record.path)
    return payload


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items()}
