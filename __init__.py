"""Hermes Exec Fuse registration, hooks, and direct-terminal cache guard."""

from __future__ import annotations

import json
from typing import Any

from .classifier import CommandClass, classify_command
from .compressor import compact_result
from .executor import ExecFuseRuntime, internal_dispatch_active
from .schemas import EXEC_FUSE, EXEC_FUSE_STATS
from .state import CacheEntry, FuseState

STATE = FuseState()
_RUNTIME: ExecFuseRuntime | None = None
_CACHE_HIT_PREFIX = "[hermes-exec-fuse:cache-hit]"
_WORKSPACE_MUTATORS = {"write_file", "patch", "execute_code", "skill_manage"}


def _session_key(task_id: str = "", session_id: str = "", **kwargs: Any) -> str:
    del kwargs
    return STATE.session_key(task_id or session_id)


def _pre_tool_call(tool_name: str, args: dict, task_id: str = "", **kwargs: Any):
    """Prevent an identical cached read-only terminal command from running twice."""
    if tool_name != "terminal" or internal_dispatch_active():
        return None
    if args.get("background") or not isinstance(args.get("command"), str):
        return None

    command = args["command"]
    if classify_command(command) != CommandClass.READ_ONLY:
        return None

    key = _session_key(task_id=task_id, **kwargs)
    options = {name: args[name] for name in ("timeout",) if name in args}
    fingerprint = STATE.fingerprint(key, command, "", options)
    entry = STATE.get(key, fingerprint)
    if entry is None:
        return None

    STATE.record_hit(key, entry)
    message = (
        f"{_CACHE_HIT_PREFIX} skipped an identical read-only command and reused its cached result. "
        f"fingerprint={fingerprint[:12]} generation={entry.generation}. Result:\n"
        f"{entry.compact_output}"
    )
    return {"action": "block", "message": message}


def _post_tool_call(
    tool_name: str,
    args: dict,
    result: str,
    task_id: str = "",
    duration_ms: int = 0,
    **kwargs: Any,
):
    """Record safe reads and invalidate them after known workspace mutations."""
    key = _session_key(task_id=task_id, **kwargs)

    if tool_name in _WORKSPACE_MUTATORS:
        STATE.bump_generation(key)
        return
    if tool_name != "terminal" or internal_dispatch_active():
        return

    command = args.get("command")
    if not isinstance(command, str):
        return
    classification = classify_command(command)
    if classification != CommandClass.READ_ONLY:
        STATE.bump_generation(key)
        return
    if isinstance(result, str) and _CACHE_HIT_PREFIX in result:
        return

    options = {name: args[name] for name in ("timeout",) if name in args}
    fingerprint = STATE.fingerprint(key, command, "", options)
    raw = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
    compact = compact_result(raw)
    STATE.record_execution(key, len(raw), len(compact))
    if ExecFuseRuntime._failed(result):
        return

    STATE.put(
        key,
        CacheEntry(
            fingerprint=fingerprint,
            command=command,
            compact_output=compact,
            raw_chars=len(raw),
            compact_chars=len(compact),
            generation=STATE.generation(key),
            source="terminal_hook",
            duration_ms=duration_ms,
        ),
    )


def _pre_llm_call(**kwargs: Any):
    """Give the model a short, cache-friendly execution-efficiency rule."""
    del kwargs
    return {
        "context": (
            "Efficiency rule: use exec_fuse for 2+ independent foreground shell commands; "
            "use depends_on for ordering; do not repeat an identical read-only command after a cache hit."
        )
    }


def register(ctx: Any):
    """Register the batch executor, metrics tool, and lifecycle hooks with Hermes."""
    global _RUNTIME
    _RUNTIME = ExecFuseRuntime(ctx, STATE)
    ctx.register_tool(
        name="exec_fuse",
        toolset="hermes_exec_fuse",
        schema=EXEC_FUSE,
        handler=_RUNTIME.handle,
        description=(
            "Batch foreground terminal commands with conservative parallelism, exact safe result reuse, "
            "dependency ordering, and compact structured output."
        ),
    )
    ctx.register_tool(
        name="exec_fuse_stats",
        toolset="hermes_exec_fuse",
        schema=EXEC_FUSE_STATS,
        handler=_RUNTIME.stats,
        description="Report session-scoped execution, cache, deduplication, and output-savings metrics.",
    )
    ctx.register_hook("pre_tool_call", _pre_tool_call)
    ctx.register_hook("post_tool_call", _post_tool_call)
    ctx.register_hook("pre_llm_call", _pre_llm_call)
