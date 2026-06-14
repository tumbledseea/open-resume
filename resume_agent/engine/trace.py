from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


class TraceLogger:
    def __init__(self, project_dir: Path, run_id: str | None = None) -> None:
        self.project_dir = project_dir.resolve()
        self.run_id = run_id or uuid4().hex
        self.path = self.project_dir / "runs" / f"{self.run_id}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, event_type: str, payload: dict[str, Any]) -> None:
        event = {
            "time": datetime.now(timezone.utc).isoformat(),
            "type": event_type,
            "payload": _json_safe(payload),
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value
