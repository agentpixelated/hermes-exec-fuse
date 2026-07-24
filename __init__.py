"""Hermes Exec Fuse registration, hooks, and direct-terminal cache guard."""

from __future__ import annotations

import json
import sys
import types
from importlib.machinery import ModuleSpec
from pathlib import Path
from typing import Any

# Pytest may import a root-level plugin __init__.py without a package name.
# Establish a synthetic package only for that collection mode; Hermes loads this
# directory as a normal package and never takes this branch.
if not __package__:
    _package = types.ModuleType("hermes_exec_fuse")
    _package.__path__ = [str(Path(__file__).resolve().parent)]
    sys.modules.setdefault("hermes_exec_fuse", _package)
    __package__ = "hermes_exec_fuse"
    __spec__ = ModuleSpec("hermes_exec_fuse", loader=None, is_package=True)
    __spec__.submodule_search_locations = _package.__path__

from .classifier import CommandClass, classify_command
from .compressor import compact_result
from .config import FuseConfig
from .executor import ExecFuseRuntime, internal_dispatch_active
from .result_status import assess_terminal_result
from .schemas import EXEC_FUSE, EXEC_FUSE_CLEAR_CACHE, EXEC_FUSE_STATS
from .state import CacheEntry, FuseState

CONFIG = FuseConfig.from_env()
STATE = FuseState(
    max_entries=CONFIG.max_entries,
    ttl_seconds=CONFIG.ttl_seconds,
    max_sessions=CONFIG.max_sessions,
)
_RUNTIME: ExecFuseRuntime | None = None
_CACHE_HIT_PREFIX = "[hermes-exec-fuse:cache-hit]"
_WORKSPACE_MUTATORS = {"write_file", "patch", "execute_code", "skill_manage"}


def _session_key(task_id: str = "", session_id: str = "", **kwargs: Any) -> str:
    del kwargs
    return STATE.session_key(task_id or session_id)


def _pre_tool_call(tool_name: str, args: dict, task_id: str = "", **kwargs: Any):
    """Prevent an identical cached read-only terminal command from running twice."""
    if not CONFIG.direct_guard or not CONFIG.cache_available:
        return None
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
    compact = compact_result(raw, CONFIG.default_output_chars)
    assessment = assess_terminal_result(result)
    STATE.record_execution(
        key,
        len(raw),
        len(compact),
        classification=classification.value,
        duration_ms=duration_ms,
        ok=assessment.ok,
    )
    if not assessment.ok or not CONFIG.cache_available:
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
    if not CONFIG.inject_efficiency_hint:
        return None
    return {
        "context": (
            "Efficiency rule: use exec_fuse for 2+ independent foreground shell commands; "
            "use depends_on for ordering; do not repeat an identical read-only command after a cache hit."
        )
    }


def register(ctx: Any):
    """Register the executor, cache-control tools, metrics, and lifecycle hooks."""
    global _RUNTIME
    _RUNTIME = ExecFuseRuntime(ctx, STATE, CONFIG)
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
        description="Report session execution, failure, cache, timing, compression, and reuse metrics.",
    )
    ctx.register_tool(
        name="exec_fuse_clear_cache",
        toolset="hermes_exec_fuse",
        schema=EXEC_FUSE_CLEAR_CACHE,
        handler=_RUNTIME.clear_cache,
        description="Clear session cache and advance its workspace generation.",
    )
    ctx.register_hook("pre_tool_call", _pre_tool_call)
    ctx.register_hook("post_tool_call", _post_tool_call)
    ctx.register_hook("pre_llm_call", _pre_llm_call)
