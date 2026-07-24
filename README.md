# Hermes Exec Fuse

**Batch once. Reuse safe results. Keep terminal noise out of the agent context.**

Hermes Exec Fuse is a native [Hermes Agent](https://github.com/NousResearch/hermes-agent) plugin that reduces redundant terminal work. It batches foreground commands, parallelizes only positively recognized read-only inspections, reuses exact safe results, invalidates stale reads after mutations, and compacts oversized output before it reaches the model.

> [!IMPORTANT]
> Version **0.2.0** remains alpha software. The runtime is covered by automated tests across Python 3.10–3.13, but compatibility still needs broader validation across Hermes releases and terminal backends.

## Install

```bash
hermes plugins install agentpixelated/hermes-exec-fuse --enable
```

Restart Hermes and verify:

```text
/plugins
```

Manual installation:

```bash
git clone https://github.com/agentpixelated/hermes-exec-fuse.git \
  ~/.hermes/plugins/hermes-exec-fuse
hermes plugins enable hermes-exec-fuse
```

## Why this exists

Agents often inspect repositories like this:

```text
terminal("git status --short")
terminal("git diff --stat")
terminal("rg TODO")
terminal("git status --short")  # repeated
```

Hermes Exec Fuse turns those calls into one deterministic batch:

```text
exec_fuse([status, diff, todos])
```

It does not call another model to optimize commands. Classification, scheduling, caching, invalidation, failure interpretation, and output reduction are rule-based and auditable.

## Tools

### `exec_fuse`

Runs one to 24 foreground terminal commands.

```json
{
  "commands": [
    {"id": "status", "command": "git status --short"},
    {"id": "diff", "command": "git diff --stat"},
    {"id": "todos", "command": "rg TODO"},
    {"id": "collect", "command": "pytest --collect-only -q"}
  ],
  "parallel": true,
  "cache": true,
  "fail_fast": false,
  "max_output_chars": 4000
}
```

Each command supports:

| Field | Required | Description |
| --- | ---: | --- |
| `id` | Yes | Unique identifier used by dependencies and results. |
| `command` | Yes | Foreground command delegated to Hermes' terminal tool. |
| `cwd` | No | Working directory applied using a safely quoted `cd -- ... &&` prefix. |
| `timeout` | No | Timeout in seconds, clamped to 1–600. |
| `depends_on` | No | IDs that must finish successfully first. |
| `cache` | No | Set `false` when a fresh read is required. |

Batch options:

| Option | Default | Description |
| --- | ---: | --- |
| `parallel` | `true` | Run ready read-only commands concurrently. |
| `cache` | `true` | Reuse eligible session-scoped read-only results. |
| `fail_fast` | `false` | Skip later ready commands after a failure. |
| `max_output_chars` | Configured default | Per-command compact-output budget, clamped to 500–20,000. |

Returned statuses are `executed`, `cache_hit`, `deduplicated`, and `skipped`.

### `exec_fuse_stats`

Returns current session metrics and active non-secret configuration, including:

- workspace generation and generation bumps;
- cache entries, reuse hits, duplicate hits, and avoided calls;
- executions by command classification;
- successful and failed executions;
- reuse rate and compression ratio;
- average execution duration;
- estimated output characters saved.

### `exec_fuse_clear_cache`

Clears cached reads for the current task/session and advances its workspace generation.

```json
{"reset_metrics": false}
```

Use this after changes made outside the observed Hermes process. Set `reset_metrics` to `true` to start a fresh session measurement window.

## Ordered work

Use `depends_on` whenever order matters:

```json
{
  "commands": [
    {
      "id": "generate",
      "command": "python generate.py",
      "cache": false
    },
    {
      "id": "inspect",
      "command": "git diff --stat",
      "depends_on": ["generate"]
    }
  ],
  "fail_fast": true
}
```

The generation command is treated as mutating or unknown, runs sequentially, and invalidates earlier workspace reads before the inspection runs.

## Execution policy

| Classification | Parallel | Cache | Deduplicate | Invalidates cache |
| --- | ---: | ---: | ---: | ---: |
| `read_only` | Yes | Yes | Yes | No |
| `mutating` | No | No | No | Yes |
| `unknown` | No | No | No | Yes |

The classifier intentionally fails closed. A false negative costs performance; a false positive could parallelize unsafe work or reuse stale data.

Commands involving interpreters, package managers, network tools, shell redirection, command substitution, unknown Git operations, or ambiguous syntax are not cached or parallelized. Unknown commands remain executable through Hermes and continue to use its normal security controls.

## Terminal failure detection

Version 0.2.0 recognizes structured failure signals commonly returned by terminal backends:

- truthy `error`;
- `ok: false` or `success: false`;
- non-zero `exit_code`, `return_code`, or `returncode`;
- statuses such as `failed`, `error`, `cancelled`, or `timed_out`.

Ordinary unstructured terminal text is not scanned for failure keywords because doing so could misclassify logs or source code. Failed reads are counted in metrics but never cached, and dependent commands are skipped.

## Runtime configuration

Configuration is read once when the plugin loads.

| Environment variable | Default | Bounds / meaning |
| --- | ---: | --- |
| `HERMES_EXEC_FUSE_TTL_SECONDS` | `300` | `0–3600`; `0` disables result reuse. |
| `HERMES_EXEC_FUSE_MAX_ENTRIES` | `128` | `1–2048` cache entries per session. |
| `HERMES_EXEC_FUSE_MAX_SESSIONS` | `64` | `1–512` tracked sessions. |
| `HERMES_EXEC_FUSE_MAX_WORKERS` | `8` | `1–32` concurrent read-only workers. |
| `HERMES_EXEC_FUSE_DEFAULT_OUTPUT_CHARS` | `4000` | `500–20000` default output budget. |
| `HERMES_EXEC_FUSE_DIRECT_GUARD` | `true` | Block repeated direct read-only terminal calls. |
| `HERMES_EXEC_FUSE_INJECT_HINT` | `true` | Inject a short batching hint before model calls. |

Boolean values accept `true/false`, `yes/no`, `on/off`, and `1/0`. Invalid values fall back to safe defaults; numeric values are clamped.

Example:

```bash
export HERMES_EXEC_FUSE_TTL_SECONDS=120
export HERMES_EXEC_FUSE_MAX_WORKERS=4
export HERMES_EXEC_FUSE_DEFAULT_OUTPUT_CHARS=6000
```

Restart Hermes after changing these values.

## Cache model

Cache identity includes:

```text
normalized command + cwd + timeout options + workspace generation
```

State is:

- scoped to the active task/session;
- in memory only;
- bounded by entries and session count;
- expired by TTL;
- cleared after known or possible mutations.

Known mutation surfaces include mutating or unknown terminal commands and Hermes tools such as `write_file`, `patch`, `execute_code`, and `skill_manage`.

## Output compaction

When output exceeds its budget, the deterministic compactor preserves:

1. the first 24 lines;
2. up to 36 middle lines containing errors, failures, warnings, tracebacks, assertions, timeouts, passes, or successes;
3. the final 18 lines;
4. a marker containing original line and character counts.

ANSI sequences are removed. JSON-like string values are compacted recursively and lists are capped at 100 items. The plugin does not retain a separate full-output archive.

## Safety boundary

Every actual command is executed through:

```python
ctx.dispatch_tool("terminal", ...)
```

The plugin never invokes `subprocess`, `os.system`, or a shell directly. Hermes therefore remains responsible for approvals, credentials, redaction, configured terminal backends, timeout handling, and operating-system permissions.

The classifier is a performance and stale-data safeguard, **not** an authorization system.

## Development

```bash
python -m pip install --upgrade pytest ruff
ruff check __init__.py classifier.py compressor.py config.py executor.py \
  result_status.py schemas.py state.py tests benchmarks
python -m compileall -q __init__.py classifier.py compressor.py config.py \
  executor.py result_status.py schemas.py state.py
pytest
python benchmarks/benchmark_scheduler.py
```

## Project documents

- [Architecture](ARCHITECTURE.md)
- [Changelog](CHANGELOG.md)
- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)
- [Examples](examples)

## Known limitations

- Alpha compatibility has not been validated against every Hermes version or terminal backend.
- Safe-but-unrecognized commands intentionally fall back to `unknown`.
- External filesystem changes cannot be detected automatically.
- Cache state does not survive process restarts.
- Direct duplicate prevention uses a `pre_tool_call` block response rather than transparent result substitution.
- Savings metrics count characters, not tokenizer-specific tokens.

## License

MIT. See [LICENSE](LICENSE).
