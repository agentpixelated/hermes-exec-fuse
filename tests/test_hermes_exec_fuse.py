from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "hermes_exec_fuse",
    PLUGIN_DIR / "__init__.py",
    submodule_search_locations=[str(PLUGIN_DIR)],
)
assert SPEC and SPEC.loader
plugin = importlib.util.module_from_spec(SPEC)
sys.modules["hermes_exec_fuse"] = plugin
SPEC.loader.exec_module(plugin)

from hermes_exec_fuse.classifier import CommandClass, classify_command, normalize_command
from hermes_exec_fuse.compressor import compact_result
from hermes_exec_fuse.executor import ExecFuseRuntime
from hermes_exec_fuse.state import FuseState


class FakeContext:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def dispatch_tool(self, name: str, args: dict):
        self.calls.append((name, args))
        return json.dumps({"command": args["command"], "output": "ok"})


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("git status --short", CommandClass.READ_ONLY),
        ("git diff && rg TODO", CommandClass.READ_ONLY),
        ("sed -n '1,10p' file", CommandClass.READ_ONLY),
        ("sed -i 's/a/b/' file", CommandClass.MUTATING),
        ("git commit -am test", CommandClass.MUTATING),
        ("git tag v1.0.0", CommandClass.MUTATING),
        ("git tag --list 'v*'", CommandClass.READ_ONLY),
        ("git config user.name", CommandClass.READ_ONLY),
        ("git config user.name Alice", CommandClass.MUTATING),
        ("pytest -q", CommandClass.UNKNOWN),
        ("pytest --collect-only -q", CommandClass.READ_ONLY),
        ("echo hello > file", CommandClass.MUTATING),
    ],
)
def test_classifier(command, expected):
    assert classify_command(command) == expected


def test_normalization():
    assert normalize_command("  git   status   --short ") == "git status --short"


def test_compressor_keeps_failure_lines():
    value = "\n".join([f"line {i}" for i in range(300)] + ["ERROR important failure"])
    compact = compact_result(value, 500)
    assert "ERROR important failure" in compact
    assert len(compact) <= 520


def test_batch_deduplicates_safe_commands():
    ctx = FakeContext()
    state = FuseState()
    runtime = ExecFuseRuntime(ctx, state)
    response = json.loads(runtime.handle({
        "parallel": False,
        "commands": [
            {"id": "one", "command": "git status --short"},
            {"id": "two", "command": "  git   status --short  "},
        ],
    }, task_id="t1"))

    assert response["ok"] is True
    assert len(ctx.calls) == 1
    assert response["results"][1]["status"] == "deduplicated"


def test_cache_reuses_between_batches():
    ctx = FakeContext()
    state = FuseState()
    runtime = ExecFuseRuntime(ctx, state)
    args = {"commands": [{"id": "status", "command": "git status --short"}]}

    first = json.loads(runtime.handle(args, task_id="t1"))
    second = json.loads(runtime.handle(args, task_id="t1"))

    assert first["results"][0]["status"] == "executed"
    assert second["results"][0]["status"] == "cache_hit"
    assert len(ctx.calls) == 1


def test_mutation_invalidates_cache():
    ctx = FakeContext()
    state = FuseState()
    runtime = ExecFuseRuntime(ctx, state)

    runtime.handle({"commands": [{"id": "status", "command": "git status --short"}]}, task_id="t1")
    runtime.handle({"commands": [{"id": "write", "command": "touch marker.txt"}]}, task_id="t1")
    response = json.loads(runtime.handle(
        {"commands": [{"id": "status", "command": "git status --short"}]},
        task_id="t1",
    ))

    assert response["results"][0]["status"] == "executed"
    assert len(ctx.calls) == 3


def test_dependencies_preserve_order():
    ctx = FakeContext()
    runtime = ExecFuseRuntime(ctx, FuseState())
    response = json.loads(runtime.handle({
        "parallel": True,
        "commands": [
            {"id": "first", "command": "touch marker.txt"},
            {"id": "second", "command": "git status --short", "depends_on": ["first"]},
        ],
    }, task_id="t1"))

    assert response["ok"] is True
    assert [args["command"] for _, args in ctx.calls] == ["touch marker.txt", "git status --short"]


def test_direct_terminal_hook_returns_cached_result():
    state = plugin.STATE
    key = "hook-session"
    fingerprint = state.fingerprint(key, "git status --short", "", {})
    state.put(key, plugin.CacheEntry(
        fingerprint=fingerprint,
        command="git status --short",
        compact_output="clean",
        raw_chars=5,
        compact_chars=5,
        generation=state.generation(key),
    ))

    directive = plugin._pre_tool_call(
        tool_name="terminal",
        args={"command": "git status --short"},
        task_id=key,
    )
    assert directive["action"] == "block"
    assert "clean" in directive["message"]


def test_direct_terminal_hook_does_not_cache_failed_result():
    state = plugin.STATE
    key = "failed-hook-session"
    command = "git status --short"

    plugin._post_tool_call(
        tool_name="terminal",
        args={"command": command},
        result=json.dumps({"error": "terminal failed"}),
        task_id=key,
        duration_ms=10,
    )

    fingerprint = state.fingerprint(key, command, "", {})
    assert state.get(key, fingerprint) is None
    assert state.snapshot(key)["executed"] == 1
