from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from resume_agent.memory.policy import validate_memory_write


@dataclass(frozen=True)
class MemoryRecord:
    id: str
    memory_type: str
    text: str
    tags: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    path: Path = Path()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "memory_type": self.memory_type,
            "text": self.text,
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], path: Path) -> "MemoryRecord":
        tags = data.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        metadata = data.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        return cls(
            id=str(data.get("id") or path.stem),
            memory_type=str(data.get("memory_type") or ""),
            text=str(data.get("text") or ""),
            tags=tuple(str(tag) for tag in tags),
            metadata={str(key): value for key, value in metadata.items()},
            created_at=str(data.get("created_at") or ""),
            path=path,
        )


class FileMemoryStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).resolve()

    def save(
        self,
        memory_type: str,
        text: str,
        tags: list[str] | tuple[str, ...] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryRecord:
        normalized_type = memory_type.strip()
        normalized_tags = tuple(str(tag).strip() for tag in (tags or []))
        validate_memory_write(normalized_type, text, list(normalized_tags))

        record_id = _record_id(text)
        created_at = datetime.now(timezone.utc).isoformat()
        path = self.root / normalized_type / f"{record_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        record = MemoryRecord(
            id=record_id,
            memory_type=normalized_type,
            text=text.strip(),
            tags=normalized_tags,
            metadata=dict(metadata or {}),
            created_at=created_at,
            path=path,
        )
        path.write_text(json.dumps(record.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return record

    def list(self, memory_type: str | None = None) -> list[MemoryRecord]:
        base = self.root / memory_type if memory_type else self.root
        if not base.exists():
            return []
        records: list[MemoryRecord] = []
        for path in sorted(base.rglob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict):
                record = MemoryRecord.from_dict(data, path)
                if not memory_type or record.memory_type == memory_type:
                    records.append(record)
        return records


def _record_id(text: str) -> str:
    words = re.findall(r"[A-Za-z0-9\u4e00-\u9fff]+", text)
    stem = "-".join(words[:4]).lower() or "memory"
    return f"{stem}-{uuid4().hex[:8]}"
