"""Context compression for the OpenResume agent.

Models the Claude Code approach: keep the current turn in full, compress older
turns into structured summaries, and persist cross-session facts to file-based
memory (profile.json / fact_index.json / match_report.json).

Token counting is approximate (1 token ≈ 4 chars for CJK-heavy text, 3.5 for
English).  This is good enough for budget management without pulling in tiktoken.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── approximate token counting ──────────────────────────────────────────
CHARS_PER_TOKEN_CJK = 4.0    # CJK-dominated text ≈ 4 chars per token
CHARS_PER_TOKEN_EN = 3.5     # English-dominated text ≈ 3.5 chars per token
DEFAULT_MAX_TOKENS = 24_000  # leave headroom for the model response


def approximate_tokens(text: str) -> int:
    """Estimate token count for a string.

    Uses a CJK-aware heuristic: counts CJK characters at 4 chars/token and
    everything else at 3.5 chars/token.  Accurate enough for budget gating.
    """
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿" or "　" <= ch <= "〿")
    other = len(text) - cjk
    if cjk + other == 0:
        return 0
    return max(1, int(cjk / CHARS_PER_TOKEN_CJK + other / CHARS_PER_TOKEN_EN))


def approximate_tokens_message(msg: dict[str, Any]) -> int:
    """Approximate token count for a single chat message."""
    tokens = 0
    content = msg.get("content", "")
    if isinstance(content, str):
        tokens += approximate_tokens(content)
    for tc in msg.get("tool_calls", []) or []:
        if isinstance(tc, dict):
            func = tc.get("function", {})
            tokens += approximate_tokens(str(func.get("name", "")))
            tokens += approximate_tokens(str(func.get("arguments", "")))
    return tokens


# ── compression primitives ──────────────────────────────────────────────

@dataclass
class CompressedHistory:
    """Compressed conversation history ready for injection into messages."""

    system_message: dict[str, Any]
    recent_messages: list[dict[str, Any]]
    older_summary: str = ""
    total_tokens: int = 0

    @property
    def messages(self) -> list[dict[str, Any]]:
        result = [self.system_message]
        if self.older_summary:
            result.append({
                "role": "user",
                "content": "[Earlier conversation summary]\n" + self.older_summary,
            })
        result.extend(self.recent_messages)
        return result


def compress_messages(
    messages: list[dict[str, Any]],
    max_tokens: int = DEFAULT_MAX_TOKENS,
    recent_turns: int = 4,
) -> CompressedHistory:
    """Compress a message list to fit within *max_tokens*.

    Strategy (Claude Code style, slimmed for pipeline use):

    1. **System message** — always kept verbatim (it carries core rules).
    2. **Most recent *recent_turns* user/assistant/tool messages** — kept in full.
    3. **Older messages** — replaced with a single compressed summary.
    4. **Static context** inside user messages is never truncated (it carries
       profile and JD — the irreplaceable facts).

    Returns a ``CompressedHistory`` whose ``.messages`` property yields the
    final message list ready for the model.
    """
    if not messages:
        return CompressedHistory(system_message={}, recent_messages=[], older_summary="", total_tokens=0)

    # Separate system message from the rest
    system = messages[0] if messages[0].get("role") == "system" else {"role": "system", "content": ""}
    body = messages[1:] if messages[0].get("role") == "system" else messages

    # If under budget, no compression needed
    total = sum(approximate_tokens_message(m) for m in messages)
    if total <= max_tokens:
        return CompressedHistory(system_message=system, recent_messages=list(body), total_tokens=total)

    # Split into recent (keep full) and older (compress)
    split = max(0, len(body) - recent_turns)
    older = body[:split]
    recent = body[split:]

    # Build summary of older messages — extract key decisions and phase results
    summary = _summarize_older_messages(older)

    recent_tokens = sum(approximate_tokens_message(m) for m in recent)
    summary_tokens = approximate_tokens(system.get("content", "")) + approximate_tokens(summary)

    return CompressedHistory(
        system_message=system,
        recent_messages=recent,
        older_summary=summary,
        total_tokens=summary_tokens + recent_tokens,
    )


def _summarize_older_messages(messages: list[dict[str, Any]]) -> str:
    """Build a structured summary of older conversation turns.

    The summary focuses on what matters for resume generation:
    - Which tools were called and their outcomes
    - Key pipeline phase transitions
    - Critical warnings or failures
    - Does NOT include verbatim profile/JD text (those live in static context)
    """
    lines: list[str] = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if isinstance(content, str):
            content = content.strip()

        if role == "user":
            # Keep user intent but truncate long pastes
            if len(content) > 200:
                content = content[:200] + "..."
            lines.append(f"[user] {content}")

        elif role == "assistant":
            # Keep assistant's stated intent, skip long narrative
            tool_calls = msg.get("tool_calls", []) or []
            tool_names = []
            for tc in tool_calls:
                if isinstance(tc, dict):
                    fn = tc.get("function", {})
                    tool_names.append(str(fn.get("name", "")))
            if tool_names:
                lines.append(f"[assistant] called: {', '.join(tool_names)}")
            elif content:
                short = content[:120] + "..." if len(content) > 120 else content
                lines.append(f"[assistant] {short}")

        elif role == "tool":
            name = msg.get("name", "unknown")
            # Extract status and key outputs from tool result JSON
            try:
                import json as _json
                obj = _json.loads(content) if isinstance(content, str) else content
                if isinstance(obj, dict):
                    status = obj.get("status", "?")
                    outputs = obj.get("outputs", {})
                    output_keys = list(outputs.keys()) if isinstance(outputs, dict) else []
                    error = obj.get("error")
                    line = f"[tool:{name}] status={status}"
                    if output_keys:
                        line += f" outputs={output_keys}"
                    if error:
                        line += f" error={str(error)[:80]}"
                    lines.append(line)
                    continue
            except Exception:
                pass
            short = content[:100] + "..." if len(content) > 100 else content
            lines.append(f"[tool:{name}] {short}")

    return "\n".join(lines) if lines else "(no earlier conversation)"


# ── tool result compression ─────────────────────────────────────────────

def compress_tool_result(content: Any, name: str = "", max_chars: int = 3000) -> Any:
    """Compress a single tool result to fit within *max_chars*.

    For large text/strings, truncates with a note.
    For large dicts, keeps status, tool name, output keys, and the first
    few top-level fields.
    Small results pass through unchanged — the compression only kicks in
    when the result actually exceeds the budget.
    """
    # Small results: pass through unchanged
    if isinstance(content, str) and len(content) <= max_chars:
        return content
    if isinstance(content, dict) and len(str(content)) <= max_chars:
        return content

    # Large string: truncate
    if isinstance(content, str):
        return content[:max_chars] + f"\n... [truncated {len(content) - max_chars} chars]"

    # Large dict: keep key metadata fields, drop verbose data fields
    if isinstance(content, dict):
        compressed: dict[str, Any] = {}
        # Always keep these high-signal fields
        for key in ("status", "tool", "name", "job_id", "company", "role", "count",
                     "overall_score", "semantic_score", "section_name", "query",
                     "version_id", "error", "message", "warnings"):
            if key in content:
                compressed[key] = content[key]
        # Keep output file references but not their full paths
        outputs = content.get("outputs", {})
        if isinstance(outputs, dict):
            compressed["output_files"] = list(outputs.keys())
        # If we kept too little, fall back to keeping all top-level keys
        if len(compressed) <= 1 and len(content) > 0:
            return {k: v for k, v in list(content.items())[:8]}
        compressed["_truncated"] = True
        return compressed

    return content
