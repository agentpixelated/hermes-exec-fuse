"""Small deterministic scheduler benchmark; not a production performance claim."""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

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

from hermes_exec_fuse.config import FuseConfig
from hermes_exec_fuse.executor import ExecFuseRuntime
from hermes_exec_fuse.state import FuseState


class DelayedTerminal:
    def __init__(self, delay: float = 0.04):
        self.delay = delay

    def dispatch_tool(self, name: str, args: dict):
        del name, args
        time.sleep(self.delay)
        return {"exit_code": 0, "output": "ok"}


def run(parallel: bool, count: int = 8) -> float:
    runtime = ExecFuseRuntime(DelayedTerminal(), FuseState(), FuseConfig(max_workers=count))
    commands = [{"id": f"read-{i}", "command": f"echo {i}", "cache": False} for i in range(count)]
    started = time.monotonic()
    response = json.loads(runtime.handle({"commands": commands, "parallel": parallel}, task_id=str(parallel)))
    assert response["ok"] is True
    return time.monotonic() - started


def main() -> None:
    sequential = run(False)
    parallel = run(True)
    print(
        json.dumps(
            {
                "commands": 8,
                "delay_per_command_ms": 40,
                "sequential_ms": round(sequential * 1000, 2),
                "parallel_ms": round(parallel * 1000, 2),
                "observed_speedup": round(sequential / parallel, 2),
                "note": "Synthetic delayed backend; validates scheduling, not real shell performance.",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
