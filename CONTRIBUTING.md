# Contributing to Hermes Exec Fuse

Hermes Exec Fuse is intentionally small, conservative, and auditable. Contributions are welcome when they improve correctness, compatibility, measurement, or usability without weakening the execution boundary.

## Development setup

```bash
python -m pip install --upgrade pytest ruff
ruff check __init__.py classifier.py compressor.py executor.py schemas.py state.py tests
python -m compileall -q __init__.py classifier.py compressor.py executor.py schemas.py state.py
pytest
```

Python 3.10 is the minimum supported version. CI also runs on Python 3.11 and 3.12.

## Design constraints

Runtime changes must preserve:

1. Every actual shell command is executed through `ctx.dispatch_tool("terminal", ...)`.
2. Only positively recognized read-only commands may be cached, deduplicated, or run concurrently.
3. Mutating and unknown commands remain sequential and invalidate the workspace generation.
4. Cache state stays bounded, session-scoped, in-memory, and thread-safe.
5. Output compaction remains deterministic and preserves diagnostic evidence.
6. Plugin hooks accept `**kwargs` for Hermes forward compatibility.
7. A plugin failure cannot crash the parent agent loop.

Read [ARCHITECTURE.md](ARCHITECTURE.md) before changing scheduling, classification, invalidation, or hook behavior.

## Classifier changes

Classifier changes require extra care because a false positive is more dangerous than a false negative.

For every newly recognized read-only command, test:

- the intended safe form;
- mutating flags or subcommands;
- shell redirection;
- command substitution;
- pipelines and compound commands;
- malformed quoting;
- closely related unknown forms.

When safety is ambiguous, return `unknown`.

## Cache and invalidation changes

A new cache input must be included in the fingerprint. A new mutation surface must advance the workspace generation.

Tests should demonstrate both reuse while generation is unchanged and a cache miss after the relevant mutation.

Do not persist raw terminal output without a separate design and security review.

## Output-compaction changes

Compaction must remain deterministic, bounded, and diagnostic-first. Cover short output, important middle lines, ANSI sequences, JSON-like results, exact boundaries, repeated lines, and empty output.

## Pull-request checklist

- [ ] The change has focused tests.
- [ ] Ruff passes.
- [ ] Compile checks pass.
- [ ] Pytest passes on the minimum Python version.
- [ ] User-visible behavior is reflected in `README.md`.
- [ ] Architectural behavior is reflected in `ARCHITECTURE.md`.
- [ ] Notable changes are added under `Unreleased` in `CHANGELOG.md`.
- [ ] No command path bypasses Hermes terminal dispatch.

## Commit style

Use focused imperative messages:

```text
fix: invalidate cache after project writes
test: cover unsafe git tag variants
docs: clarify direct terminal guard
```

## Security issues

Do not publish exploit details in a normal issue. Follow [SECURITY.md](SECURITY.md) for private reporting guidance.
