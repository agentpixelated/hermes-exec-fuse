"""Thread-safe, session-scoped cache and metrics."""

from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from threading import RLock
from typing import Any

from .classifier import normalize_command


@dataclass
class CacheEntry:
    fingerprint: str
    command: str
    compact_output: str
    raw_chars: int
    compact_chars: int
    generation: int
    created_at: float = field(default_factory=time.monotonic)
    source: str = "terminal"
    duration_ms: int = 0


@dataclass
class SessionState:
    generation: int = 0
    cache: OrderedDict[str, CacheEntry] = field(default_factory=OrderedDict)
    executed: int = 0
    cache_hits: int = 0
    duplicate_hits: int = 0
    avoided_calls: int = 0
    raw_chars: int = 0
    returned_chars: int = 0


class FuseState:
    def __init__(self, max_entries: int = 128, ttl_seconds: int = 300, max_sessions: int = 64):
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self.max_sessions = max_sessions
        self._sessions: OrderedDict[str, SessionState] = OrderedDict()
        self._lock = RLock()

    @staticmethod
    def session_key(value: str | None) -> str:
        return (value or "default").strip() or "default"

    def _session(self, key: str) -> SessionState:
        key = self.session_key(key)
        session = self._sessions.get(key)
        if session is None:
            session = SessionState()
            self._sessions[key] = session
            while len(self._sessions) > self.max_sessions:
                self._sessions.popitem(last=False)
        else:
            self._sessions.move_to_end(key)
        return session

    def generation(self, key: str) -> int:
        with self._lock:
            return self._session(key).generation

    def fingerprint(self, key: str, command: str, cwd: str = "", options: dict[str, Any] | None = None) -> str:
        with self._lock:
            generation = self._session(key).generation
        payload = {
            "command": normalize_command(command),
            "cwd": (cwd or "").strip(),
            "options": options or {},
            "generation": generation,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def semantic_key(command: str, cwd: str = "", options: dict[str, Any] | None = None) -> str:
        payload = {
            "command": normalize_command(command),
            "cwd": (cwd or "").strip(),
            "options": options or {},
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def get(self, key: str, fingerprint: str) -> CacheEntry | None:
        with self._lock:
            session = self._session(key)
            entry = session.cache.get(fingerprint)
            if entry is None:
                return None
            if time.monotonic() - entry.created_at > self.ttl_seconds:
                session.cache.pop(fingerprint, None)
                return None
            session.cache.move_to_end(fingerprint)
            return entry

    def put(self, key: str, entry: CacheEntry) -> None:
        with self._lock:
            session = self._session(key)
            session.cache[entry.fingerprint] = entry
            session.cache.move_to_end(entry.fingerprint)
            while len(session.cache) > self.max_entries:
                session.cache.popitem(last=False)

    def bump_generation(self, key: str) -> int:
        with self._lock:
            session = self._session(key)
            session.generation += 1
            session.cache.clear()
            return session.generation

    def record_execution(self, key: str, raw_chars: int, returned_chars: int) -> None:
        with self._lock:
            session = self._session(key)
            session.executed += 1
            session.raw_chars += max(raw_chars, 0)
            session.returned_chars += max(returned_chars, 0)

    def record_hit(self, key: str, entry: CacheEntry, duplicate: bool = False) -> None:
        with self._lock:
            session = self._session(key)
            session.cache_hits += 1
            session.avoided_calls += 1
            session.returned_chars += entry.compact_chars
            if duplicate:
                session.duplicate_hits += 1

    def snapshot(self, key: str) -> dict[str, Any]:
        with self._lock:
            session = self._session(key)
            data = asdict(session)
            data["cache_entries"] = len(session.cache)
            data.pop("cache", None)
            data["estimated_chars_saved"] = max(0, session.raw_chars - session.returned_chars)
            return data
