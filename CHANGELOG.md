# Changelog

All notable changes to Hermes Exec Fuse are documented here. The project follows [Semantic Versioning](https://semver.org/); during `0.x`, minor releases may contain behavioral changes.

## 0.2.0 — 2026-07-24

### Added

- `exec_fuse_clear_cache` for explicit session cache invalidation and optional metric reset.
- Environment-based runtime configuration for TTL, cache bounds, worker count, output budget, direct guard, and model hint injection.
- Structured terminal failure normalization for `ok`, `success`, exit-code fields, error fields, and failure statuses.
- Execution metrics by command class, success/failure counters, generation bumps, reuse rate, compression ratio, and average duration.
- Config snapshot in `exec_fuse_stats`.
- Scheduler benchmark using a deterministic delayed fake terminal backend.
- Python 3.13 CI coverage.

### Changed

- Parallel worker count and default output budget are now configurable.
- Failed command results include `failure_reason` and structured `exit_code` when available.
- Batch summaries include classifications and total execution duration.
- Root plugin import is robust when Pytest collects the standalone repository's `__init__.py` directly.

### Fixed

- Non-zero structured terminal exit codes now fail dependencies instead of being treated as successful output.
- A TTL of zero now cleanly disables cache reuse.

## 0.1.0 — 2026-07-22

### Added

- `exec_fuse` for batches of up to 24 foreground terminal commands.
- Conservative `read_only`, `mutating`, and `unknown` classification.
- Bounded parallel execution and dependency ordering.
- Exact read-only deduplication and session-scoped cache reuse.
- Workspace-generation invalidation and direct-terminal duplicate guard.
- Deterministic output compaction and `exec_fuse_stats`.
- Standalone installation layout, documentation, tests, and Python 3.10–3.12 CI.
