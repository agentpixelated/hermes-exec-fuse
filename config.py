"""Runtime configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Mapping


def _bounded_int(value: str | None, default: int, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _boolean(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


@dataclass(frozen=True)
class FuseConfig:
    """Bounded, non-secret settings for one plugin process."""

    ttl_seconds: int = 300
    max_entries: int = 128
    max_sessions: int = 64
    max_workers: int = 8
    default_output_chars: int = 4000
    direct_guard: bool = True
    inject_efficiency_hint: bool = True

    @property
    def cache_available(self) -> bool:
        return self.ttl_seconds > 0 and self.max_entries > 0

    def snapshot(self) -> dict[str, int | bool]:
        return {**asdict(self), "cache_available": self.cache_available}

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "FuseConfig":
        env = os.environ if environ is None else environ
        return cls(
            ttl_seconds=_bounded_int(env.get("HERMES_EXEC_FUSE_TTL_SECONDS"), 300, 0, 3600),
            max_entries=_bounded_int(env.get("HERMES_EXEC_FUSE_MAX_ENTRIES"), 128, 1, 2048),
            max_sessions=_bounded_int(env.get("HERMES_EXEC_FUSE_MAX_SESSIONS"), 64, 1, 512),
            max_workers=_bounded_int(env.get("HERMES_EXEC_FUSE_MAX_WORKERS"), 8, 1, 32),
            default_output_chars=_bounded_int(
                env.get("HERMES_EXEC_FUSE_DEFAULT_OUTPUT_CHARS"), 4000, 500, 20000
            ),
            direct_guard=_boolean(env.get("HERMES_EXEC_FUSE_DIRECT_GUARD"), True),
            inject_efficiency_hint=_boolean(env.get("HERMES_EXEC_FUSE_INJECT_HINT"), True),
        )
