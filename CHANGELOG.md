# Changelog

All notable changes to Hermes Exec Fuse are documented here.

The project follows [Semantic Versioning](https://semver.org/). During the `0.x` series, minor versions may contain behavioral changes.

## Unreleased

### Changed

- Migrated the plugin from the `mcp-radar` incubator into a dedicated standalone repository.
- Moved the Hermes plugin manifest and runtime files to the repository root for direct installation.
- Updated development commands, CI paths, installation instructions, and examples for the standalone layout.

### Fixed

- Failed direct read-only terminal results are recorded in metrics but are not inserted into the reuse cache.

## 0.1.0 — 2026-07-22

### Added

- `exec_fuse` tool for batches of up to 24 foreground terminal commands.
- Conservative `read_only`, `mutating`, and `unknown` command classification.
- Bounded parallel execution for independent read-only commands.
- Explicit dependency ordering with `depends_on` and cycle detection.
- Normalized exact read-only deduplication inside a batch.
- Session-scoped LRU result cache with a five-minute TTL.
- Workspace-generation invalidation after mutating or unknown operations.
- Direct-terminal duplicate-call guard through Hermes lifecycle hooks.
- Deterministic terminal-result compaction with diagnostic-line preservation.
- `exec_fuse_stats` for execution, reuse, and estimated character-savings metrics.
- Automated tests and Python 3.10–3.12 CI.
