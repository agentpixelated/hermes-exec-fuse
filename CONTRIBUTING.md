# Contributing to Hermes Exec Fuse

Hermes Exec Fuse is intentionally conservative and auditable. Contributions are welcome when they improve correctness, compatibility, measurement, or usability without weakening the Hermes execution boundary.

## Development setup

```bash
python -m pip install --upgrade pytest ruff
ruff check __init__.py classifier.py compressor.py config.py executor.py \
  result_status.py schemas.py state.py tests benchmarks
python -m compileall -q __init__.py classifier.py compressor.py config.py \
  executor.py result_status.py schemas.py state.py
pytest
python benchmarks/benchmark_scheduler.py
```

Python 3.10 is the minimum supported version. CI runs through Python 3.13.

## Design constraints

Runtime changes must preserve:

1. Every actual command uses `ctx.dispatch_tool("terminal", ...)`.
2. Only positively recognized read-only commands may be cached, deduplicated, or run concurrently.
3. Mutating and unknown commands remain sequential and invalidate workspace state.
4. Cache state remains bounded, session-scoped, in-memory, and thread-safe.
5. Output compaction remains deterministic and diagnostic-first.
6. Hooks and handlers accept `**kwargs` for forward compatibility.
7. Plugin failures return structured errors rather than crashing the agent loop.
8. Environment configuration remains bounded and non-secret.

Read [ARCHITECTURE.md](ARCHITECTURE.md) before changing scheduling, classification, invalidation, hooks, result normalization, or cache identity.

## Test expectations

Classifier changes require safe forms plus adversarial neighboring cases: mutating flags, redirection, substitutions, pipelines, malformed quoting, and ambiguous variants.

Terminal-result changes should cover all supported structured fields and must avoid guessing failure from ordinary output text.

Cache changes must demonstrate both reuse in one generation and a miss after invalidation. Configuration changes need default, invalid, and boundary tests.

## Pull-request checklist

- [ ] Focused tests cover success and nearby failure cases.
- [ ] Ruff, compile checks, and Pytest pass.
- [ ] User-visible behavior is documented in `README.md`.
- [ ] Design changes are reflected in `ARCHITECTURE.md`.
- [ ] Notable changes are recorded in `CHANGELOG.md`.
- [ ] No command path bypasses Hermes terminal dispatch.
- [ ] No raw terminal output is persisted.

## Security issues

Do not publish exploit details in a normal issue. Follow [SECURITY.md](SECURITY.md).
