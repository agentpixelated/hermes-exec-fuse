# Hermes Exec Fuse

**Batch once. Reuse safe results. Keep terminal noise out of the agent context.**

Hermes Exec Fuse is a native [Hermes Agent](https://github.com/NousResearch/hermes-agent) plugin for reducing redundant shell work. It gives the model one structured tool for batching foreground commands, safely reusing exact read-only results, preventing duplicate terminal calls, and compacting large outputs before they return to the model.

> [!IMPORTANT]
> Status: **alpha**. The core behavior is covered by automated tests, but broader end-to-end validation across Hermes versions and terminal backends is still in progress.

## Why this exists

Tool-using agents often spend extra iterations and context tokens on patterns such as:

```text
terminal("git status --short")
terminal("git diff --stat")
terminal("rg TODO")
terminal("git status --short")  # repeated
```

Hermes Exec Fuse turns those inspections into one deterministic batch:

```text
exec_fuse([status, diff, todos])
```

It does not call another model to optimize commands. Classification, scheduling, caching, invalidation, and output reduction are rule-based and inspectable.

## Highlights

| Capability | Behavior |
| --- | --- |
| Command batching | Accepts up to 24 foreground commands in one tool call. |
| Safe concurrency | Runs independent commands concurrently only when positively classified as read-only. |
| Exact deduplication | Executes normalized exact read-only duplicates once per batch. |
| Session cache | Reuses successful read-only results for five minutes while workspace state is unchanged. |
| Direct-call guard | Prevents an identical cached read-only `terminal` call from running again. |
| Dependency ordering | Supports explicit command DAGs through `depends_on`. |
| Conservative invalidation | Mutating and unknown operations clear cached workspace reads. |
| Output compaction | Keeps diagnostic evidence while reducing oversized terminal output. |
| Metrics | Reports executions, cache hits, duplicate hits, avoided calls, and estimated character savings. |
| Hermes-native execution | Every real command goes through `ctx.dispatch_tool("terminal", ...)`. |

Because Hermes remains the execution owner, the plugin preserves the configured terminal backend, approval checks, credentials, redaction, timeout handling, and other host behavior.

## Install

### Hermes plugin installer

```bash
hermes plugins install agentpixelated/hermes-exec-fuse --enable
```

Restart Hermes, then verify:

```text
/plugins
```

### Manual installation

```bash
git clone https://github.com/agentpixelated/hermes-exec-fuse.git \
  ~/.hermes/plugins/hermes-exec-fuse
hermes plugins enable hermes-exec-fuse
```

For discovery diagnostics:

```bash
HERMES_PLUGINS_DEBUG=1 hermes plugins list
```

## Quick start

Ask Hermes:

```text
Inspect this repository efficiently. Use exec_fuse to batch git status,
git diff --stat, TODO search, and pytest test collection.
```

Equivalent tool arguments:

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
  "max_output_chars": 4000
}
```

For ordered work:

```json
{
  "commands": [
    {"id": "generate", "command": "python generate.py"},
    {
      "id": "inspect",
      "command": "git diff --stat",
      "depends_on": ["generate"]
    }
  ],
  "fail_fast": true
}
```

## Tools

### `exec_fuse`

Runs one to 24 foreground terminal commands and returns compact structured results.

| Argument | Type | Default | Description |
| --- | --- | --- | --- |
| `commands` | array | required | Command objects with unique IDs. |
| `parallel` | boolean | `true` | Run ready read-only commands concurrently, capped at eight workers. |
| `cache` | boolean | `true` | Enable session-scoped reuse for eligible read-only commands. |
| `fail_fast` | boolean | `false` | Skip later ready commands after a failure. Failed dependencies always cause skips. |
| `max_output_chars` | integer | `4000` | Per-command compact-output budget, clamped to 500–20,000 characters. |

Each command supports `id`, `command`, optional `cwd`, `timeout`, `depends_on`, and a per-command `cache` override.

Returned statuses:

- `executed`
- `cache_hit`
- `deduplicated`
- `skipped`

### `exec_fuse_stats`

Returns session-scoped workspace generation, cache size, executions, reuse counters, avoided calls, raw and returned character counts, and estimated characters saved.

## Execution policy

| Classification | Parallel | Cache | Deduplicate | Invalidates cache |
| --- | ---: | ---: | ---: | ---: |
| `read_only` | Yes | Yes | Yes | No |
| `mutating` | No | No | No | Yes |
| `unknown` | No | No | No | Yes |

The classifier intentionally fails closed. Commands involving interpreters, package managers, network tools, shell redirection, command substitution, unknown Git actions, or ambiguous shell behavior are not cached or parallelized.

Unknown commands remain executable through Hermes; they simply run sequentially and advance the workspace generation afterward.

## Cache model

Cache identity includes:

```text
normalized command + cwd + relevant options + workspace generation
```

Default limits:

- five-minute TTL;
- 128 entries per session;
- 64 tracked sessions;
- in-memory storage only.

Known mutation surfaces include mutating or unknown terminal commands and Hermes tools such as `write_file`, `patch`, `execute_code`, and `skill_manage`.

## Output compaction

Oversized output is reduced deterministically by preserving:

1. the first 24 lines;
2. up to 36 middle lines containing error, failure, warning, traceback, assertion, timeout, pass, or success signals;
3. the final 18 lines;
4. a marker containing original line and character counts.

The plugin does not persist a separate archive of full raw terminal output.

## Safety boundary

- No direct `subprocess`, `os.system`, or shell execution inside the plugin.
- Every actual command is dispatched through Hermes' registered `terminal` tool.
- Only positively recognized reads can run concurrently or be reused.
- Mutating and unknown commands remain sequential.
- Background and interactive commands are outside the current scope.
- Invalid batches and dependency cycles return structured errors.

The classifier is a performance and stale-data safeguard, **not** an authorization system. Hermes' normal security controls remain authoritative.

## Known limitations

- Alpha compatibility has not yet been validated against every Hermes release or terminal backend.
- Many safe but unrecognized commands intentionally fall back to `unknown`.
- Cache state does not survive Hermes restarts.
- External filesystem changes cannot be observed automatically.
- Direct duplicate prevention uses a `pre_tool_call` block response because the current hook API cannot transparently substitute a successful result.
- Savings metrics count characters, not tokenizer-specific tokens.

## Development

```bash
python -m pip install --upgrade pytest ruff
ruff check __init__.py classifier.py compressor.py executor.py schemas.py state.py tests
python -m compileall -q __init__.py classifier.py compressor.py executor.py schemas.py state.py
pytest
```

## Project documents

- [Architecture](ARCHITECTURE.md)
- [Changelog](CHANGELOG.md)
- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)
- [Examples](examples)

## Roadmap

- End-to-end tests against real Hermes installations.
- Compatibility validation across terminal backends.
- Configurable cache limits and classifier extensions.
- Tokenizer-aware benchmarks using real agent traces.
- Tagged releases and a stable `1.0` contract.

## License

MIT. See [LICENSE](LICENSE).