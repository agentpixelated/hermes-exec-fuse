from __future__ import annotations

import importlib.util
import json
import sys
import time
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
from hermes_exec_fuse.config import FuseConfig
from hermes_exec_fuse.executor import ExecFuseRuntime
from hermes_exec_fuse.result_status import assess_terminal_result
from hermes_exec_fuse.state import FuseState


class FakeContext:
    def __init__(self, result=None, delay: float = 0.0):
        self.calls: list[tuple[str, dict]] = []
        self.result = result
        self.delay = delay

    def dispatch_tool(self, name: str, args: dict):
        self.calls.append((name, args))
        if self.delay:
            time.sleep(self.delay)
        if self.result is not None:
            return self.result
        return json.dumps({"command": args["command"], "output": "ok", "exit_code": 0})


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


@pytest.mark.parametrize(
    ("value", "ok", "reason"),
    [
        ({"exit_code": 0}, True, None),
        ({"exit_code": 2}, False, "exit_code=2"),
        ({"returncode": "1"}, False, "returncode=1"),
        ({"ok": False}, False, "ok=false"),
        ({"success": False}, False, "success=false"),
        ({"status": "FAILED"}, False, "status=failed"),
        ({"error": "boom"}, False, "boom"),
        ("ordinary terminal output", True, None),
    ],
)
def test_result_assessment(value, ok, reason):
    assessment = assess_terminal_result(value)
    assert assessment.ok is ok
    assert assessment.reason == reason


def test_result_assessment_reads_json_strings():
    assessment = assess_terminal_result(json.dumps({"return_code": 7}))
    assert assessment.ok is False
    assert assessment.exit_code == 7


def test_config_from_env_clamps_and_parses():
    config = FuseConfig.from_env(
        {
            "HERMES_EXEC_FUSE_TTL_SECONDS": "0",
            "HERMES_EXEC_FUSE_MAX_ENTRIES": "99999",
            "HERMES_EXEC_FUSE_MAX_SESSIONS": "2",
            "HERMES_EXEC_FUSE_MAX_WORKERS": "0",
            "HERMES_EXEC_FUSE_DEFAULT_OUTPUT_CHARS": "100",
            "HERMES_EXEC_FUSE_DIRECT_GUARD": "off",
            "HERMES_EXEC_FUSE_INJECT_HINT": "yes",
        }
    )
    assert config.ttl_seconds == 0
    assert config.max_entries == 2048
    assert config.max_sessions == 2
    assert config.max_workers == 1
    assert config.default_output_chars == 500
    assert config.direct_guard is False
    assert config.inject_efficiency_hint is True
    assert config.cache_available is False


def test_batch_deduplicates_safe_commands():
    ctx = FakeContext()
    state = FuseState()
    runtime = ExecFuseRuntime(ctx, state)
    response = json.loads(
        runtime.handle(
            {
                "parallel": False,
                "commands": [
                    {"id": "one", "command": "git status --short"},
                    {"id": "two", "command": "  git   status --short  "},
                ],
            },
            task_id="t1",
        )
    )

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


def test_zero_ttl_disables_reuse():
    ctx = FakeContext()
    state = FuseState(ttl_seconds=0)
    runtime = ExecFuseRuntime(ctx, state, FuseConfig(ttl_seconds=0))
    args = {"commands": [{"id": "status", "command": "git status --short"}]}

    runtime.handle(args, task_id="t1")
    response = json.loads(runtime.handle(args, task_id="t1"))

    assert response["results"][0]["status"] == "executed"
    assert len(ctx.calls) == 2


def test_mutation_invalidates_cache():
    ctx = FakeContext()
    state = FuseState()
    runtime = ExecFuseRuntime(ctx, state)

    runtime.handle({"commands": [{"id": "status", "command": "git status --short"}]}, task_id="t1")
    runtime.handle({"commands": [{"id": "write", "command": "touch marker.txt"}]}, task_id="t1")
    response = json.loads(
        runtime.handle(
            {"commands": [{"id": "status", "command": "git status --short"}]},
            task_id="t1",
        )
    )

    assert response["results"][0]["status"] == "executed"
    assert len(ctx.calls) == 3


def test_dependencies_preserve_order():
    ctx = FakeContext()
    runtime = ExecFuseRuntime(ctx, FuseState())
    response = json.loads(
        runtime.handle(
            {
                "parallel": True,
                "commands": [
                    {"id": "first", "command": "touch marker.txt"},
                    {"id": "second", "command": "git status --short", "depends_on": ["first"]},
                ],
            },
            task_id="t1",
        )
    )

    assert response["ok"] is True
    assert [args["command"] for _, args in ctx.calls] == ["touch marker.txt", "git status --short"]


def test_structured_exit_code_failure_skips_dependency():
    ctx = FakeContext(result={"exit_code": 3, "output": "failed"})
    runtime = ExecFuseRuntime(ctx, FuseState())
    response = json.loads(
        runtime.handle(
            {
                "commands": [
                    {"id": "first", "command": "git status --short"},
                    {"id": "second", "command": "git diff --stat", "depends_on": ["first"]},
                ]
            },
            task_id="t1",
        )
    )

    assert response["ok"] is False
    assert response["results"][0]["exit_code"] == 3
    assert response["results"][1]["status"] == "skipped"
    assert len(ctx.calls) == 1


def test_clear_cache_advances_generation_and_can_reset_metrics():
    state = FuseState()
    runtime = ExecFuseRuntime(FakeContext(), state)
    runtime.handle({"commands": [{"id": "status", "command": "git status --short"}]}, task_id="t1")
    before = state.snapshot("t1")

    cleared = json.loads(runtime.clear_cache({"reset_metrics": True}, task_id="t1"))
    after = state.snapshot("t1")

    assert cleared["removed_entries"] == 1
    assert cleared["generation_after"] == cleared["generation_before"] + 1
    assert before["executed"] == 1
    assert after["executed"] == 0
    assert after["cache_entries"] == 0


def test_stats_include_config_and_derived_metrics():
    config = FuseConfig(max_workers=3, default_output_chars=1234)
    state = FuseState()
    runtime = ExecFuseRuntime(FakeContext(), state, config)
    runtime.handle({"commands": [{"id": "status", "command": "git status --short"}]}, task_id="t1")
    runtime.handle({"commands": [{"id": "status", "command": "git status --short"}]}, task_id="t1")

    stats = json.loads(runtime.stats({}, task_id="t1"))
    assert stats["config"]["max_workers"] == 3
    assert stats["config"]["default_output_chars"] == 1234
    assert stats["reuse_rate"] == 0.5
    assert stats["executions_by_class"]["read_only"] == 1
    assert stats["executed_ok"] == 1


def test_parallel_execution_uses_configured_workers():
    ctx = FakeContext(delay=0.03)
    config = FuseConfig(max_workers=4)
    runtime = ExecFuseRuntime(ctx, FuseState(), config)
    commands = [{"id": f"c{i}", "command": f"echo {i}"} for i in range(4)]

    started = time.monotonic()
    response = json.loads(runtime.handle({"commands": commands, "parallel": True}, task_id="t1"))
    elapsed = time.monotonic() - started

    assert response["ok"] is True
    assert elapsed < 0.1


def test_direct_terminal_hook_returns_cached_result():
    state = plugin.STATE
    key = "hook-session"
    fingerprint = state.fingerprint(key, "git status --short", "", {})
    state.put(
        key,
        plugin.CacheEntry(
            fingerprint=fingerprint,
            command="git status --short",
            compact_output="clean",
            raw_chars=5,
            compact_chars=5,
            generation=state.generation(key),
        ),
    )

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
        result=json.dumps({"returncode": 1, "output": "failed"}),
        task_id=key,
        duration_ms=10,
    )

    fingerprint = state.fingerprint(key, command, "", {})
    assert state.get(key, fingerprint) is None
    snapshot = state.snapshot(key)
    assert snapshot["executed"] == 1
    assert snapshot["executed_failed"] == 1
