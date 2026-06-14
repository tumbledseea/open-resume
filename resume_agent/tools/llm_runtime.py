from __future__ import annotations

import sys
from pathlib import Path


_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "skills" / "resume-master" / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

try:
    from llm.client import complete_json, LLMConfigError  # type: ignore
except Exception:  # noqa: BLE001
    complete_json = None  # type: ignore

    class LLMConfigError(RuntimeError):  # type: ignore
        pass

