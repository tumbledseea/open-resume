from __future__ import annotations

import re

from resume_agent.memory.store import MemoryRecord


def select_memories(
    records: list[MemoryRecord],
    query: str = "",
    memory_type: str | None = None,
    max_results: int = 5,
) -> list[MemoryRecord]:
    filtered = [record for record in records if memory_type is None or record.memory_type == memory_type]
    terms = _query_terms(query)
    if not terms:
        return sorted(filtered, key=lambda record: record.created_at, reverse=True)[:max_results]

    scored: list[tuple[int, MemoryRecord]] = []
    for record in filtered:
        haystack = " ".join([record.text, " ".join(record.tags), " ".join(str(v) for v in record.metadata.values())])
        score = sum(1 for term in terms if term.lower() in haystack.lower())
        if score:
            scored.append((score, record))
    scored.sort(key=lambda item: (item[0], item[1].created_at), reverse=True)
    return [record for _, record in scored[:max_results]]


def _query_terms(query: str) -> list[str]:
    return [term for term in re.split(r"\s+", query.strip()) if term]
