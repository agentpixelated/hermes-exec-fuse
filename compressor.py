"""Deterministic terminal output compression."""

from __future__ import annotations

import json
import re
from typing import Any

_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_IMPORTANT = re.compile(
    r"(?:error|failed|failure|fatal|exception|traceback|warning|warn:|assertion|"
    r"denied|not found|timed out|timeout|passed|success)",
    re.IGNORECASE,
)


def _compress_text(text: str, max_chars: int) -> str:
    clean = _ANSI.sub("", text or "").strip()
    if len(clean) <= max_chars:
        return clean

    lines = clean.splitlines()
    head = lines[:24]
    tail = lines[-18:] if len(lines) > 24 else []
    important = [line for line in lines[24:-18] if _IMPORTANT.search(line)][:36]

    selected: list[str] = []
    seen: set[str] = set()
    for line in [*head, *important, *tail]:
        if line not in seen:
            selected.append(line)
            seen.add(line)

    marker = f"... compressed {len(lines)} lines / {len(clean)} chars ..."
    candidate = "\n".join([*selected[:24], marker, *selected[24:]])
    if len(candidate) <= max_chars:
        return candidate

    half = max(100, (max_chars - len(marker) - 4) // 2)
    return f"{clean[:half]}\n{marker}\n{clean[-half:]}"


def compact_result(value: Any, max_chars: int = 4000) -> str:
    """Compact strings and JSON-like terminal results without hiding failures."""
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, default=str)

    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return _compress_text(value, max_chars)

    def shrink(item: Any) -> Any:
        if isinstance(item, str):
            return _compress_text(item, max_chars)
        if isinstance(item, list):
            return [shrink(child) for child in item[:100]]
        if isinstance(item, dict):
            return {str(key): shrink(child) for key, child in item.items()}
        return item

    rendered = json.dumps(shrink(parsed), ensure_ascii=False, separators=(",", ":"), default=str)
    return _compress_text(rendered, max_chars)
