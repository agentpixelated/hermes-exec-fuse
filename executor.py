"""Batch executor that delegates every command to Hermes' terminal tool."""

from __future__ import annotations

import json
import shlex
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from .classifier import CommandClass, classify_command
from .compressor import compact_result
from .state import CacheEntry, FuseState

_INTERNAL_DISPATCH = threading.local()


def internal_dispatch_active() -> bool:
    return bool(getattr(_INTERNAL_DISPATCH, "active", False))


@dataclass
class CommandSpec:
    id: str
    command: str
    cwd: str = ""
    timeout: int | None = None
    depends_on: tuple[str, ...] = ()
    cache: bool = True

    @property
    def classification(self) -> CommandClass:
        return classify_command(self.command)

    @property
    def options(self) -> dict[str, Any]:
        return {"timeout": self.timeout} if self.timeout is not None else {}


class ExecFuseRuntime:
    def __init__(self, ctx: Any, state: FuseState):
        self.ctx = ctx
        self.state = state

    @staticmethod
    def _parse_specs(items: Any) -> list[CommandSpec]:
        if not isinstance(items, list) or not items:
            raise ValueError("commands must be a non-empty array")
        if len(items) > 24:
            raise ValueError("at most 24 commands are allowed")

        specs: list[CommandSpec] = []
        seen: set[str] = set()
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                raise ValueError(f"commands[{index}] must be an object")
            command_id = str(item.get("id", "")).strip()
            command = str(item.get("command", "")).strip()
            if not command_id or not command:
                raise ValueError(f"commands[{index}] needs non-empty id and command")
            if command_id in seen:
                raise ValueError(f"duplicate command id: {command_id}")
            seen.add(command_id)
            timeout = item.get("timeout")
            if timeout is not None:
                timeout = max(1, min(600, int(timeout)))
            depends_on = tuple(str(dep).strip() for dep in item.get("depends_on", []) if str(dep).strip())
            specs.append(CommandSpec(
                id=command_id,
                command=command,
                cwd=str(item.get("cwd", "")).strip(),
                timeout=timeout,
                depends_on=depends_on,
                cache=bool(item.get("cache", True)),
            ))

        known = {spec.id for spec in specs}
        for spec in specs:
            unknown = [dep for dep in spec.depends_on if dep not in known]
            if unknown:
                raise ValueError(f"{spec.id} depends on unknown IDs: {', '.join(unknown)}")
            if spec.id in spec.depends_on:
                raise ValueError(f"{spec.id} cannot depend on itself")
        return specs

    @staticmethod
    def _terminal_args(spec: CommandSpec) -> dict[str, Any]:
        command = spec.command
        if spec.cwd:
            command = f"cd -- {shlex.quote(spec.cwd)} && {command}"
        payload: dict[str, Any] = {"command": command}
        if spec.timeout is not None:
            payload["timeout"] = spec.timeout
        return payload

    @staticmethod
    def _failed(raw: Any) -> bool:
        if isinstance(raw, dict):
            return bool(raw.get("error"))
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return False
            return isinstance(parsed, dict) and bool(parsed.get("error"))
        return False

    def _run_one(self, spec: CommandSpec, session_key: str, cache_enabled: bool, max_chars: int) -> dict[str, Any]:
        classification = spec.classification
        can_cache = cache_enabled and spec.cache and classification == CommandClass.READ_ONLY
        fingerprint = self.state.fingerprint(session_key, spec.command, spec.cwd, spec.options)
        if can_cache:
            cached = self.state.get(session_key, fingerprint)
            if cached is not None:
                self.state.record_hit(session_key, cached)
                return {
                    "id": spec.id,
                    "status": "cache_hit",
                    "classification": classification.value,
                    "fingerprint": fingerprint[:12],
                    "output": cached.compact_output,
                    "duration_ms": 0,
                    "ok": True,
                }

        generation_before = self.state.generation(session_key)
        started = time.monotonic()
        try:
            _INTERNAL_DISPATCH.active = True
            raw = self.ctx.dispatch_tool("terminal", self._terminal_args(spec))
            ok = not self._failed(raw)
            error = None
        except Exception as exc:
            raw = {"error": f"terminal dispatch failed: {exc}"}
            ok = False
            error = str(exc)
        finally:
            _INTERNAL_DISPATCH.active = False

        duration_ms = round((time.monotonic() - started) * 1000)
        raw_text = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False, default=str)
        compact = compact_result(raw_text, max_chars)
        self.state.record_execution(session_key, len(raw_text), len(compact))

        if classification != CommandClass.READ_ONLY and self.state.generation(session_key) == generation_before:
            self.state.bump_generation(session_key)
        elif can_cache and ok:
            entry = CacheEntry(
                fingerprint=fingerprint,
                command=spec.command,
                compact_output=compact,
                raw_chars=len(raw_text),
                compact_chars=len(compact),
                generation=generation_before,
                source="exec_fuse",
                duration_ms=duration_ms,
            )
            self.state.put(session_key, entry)

        result = {
            "id": spec.id,
            "status": "executed",
            "classification": classification.value,
            "fingerprint": fingerprint[:12],
            "output": compact,
            "duration_ms": duration_ms,
            "ok": ok,
        }
        if error:
            result["error"] = error
        return result

    def handle(self, args: dict[str, Any], **kwargs: Any) -> str:
        try:
            specs = self._parse_specs(args.get("commands"))
            parallel = bool(args.get("parallel", True))
            cache_enabled = bool(args.get("cache", True))
            fail_fast = bool(args.get("fail_fast", False))
            max_chars = max(500, min(20000, int(args.get("max_output_chars", 4000))))
            session_key = self.state.session_key(kwargs.get("task_id") or kwargs.get("session_id"))

            canonical: dict[str, str] = {}
            duplicate_of: dict[str, str] = {}
            enriched: list[CommandSpec] = []
            for spec in specs:
                if spec.classification == CommandClass.READ_ONLY:
                    semantic = self.state.semantic_key(spec.command, spec.cwd, spec.options)
                    previous = canonical.get(semantic)
                    if previous:
                        duplicate_of[spec.id] = previous
                        spec = CommandSpec(
                            id=spec.id,
                            command=spec.command,
                            cwd=spec.cwd,
                            timeout=spec.timeout,
                            depends_on=tuple(dict.fromkeys((*spec.depends_on, previous))),
                            cache=spec.cache,
                        )
                    else:
                        canonical[semantic] = spec.id
                enriched.append(spec)
            specs = enriched

            pending = {spec.id: spec for spec in specs}
            results: dict[str, dict[str, Any]] = {}
            failed_any = False

            while pending:
                ready = [
                    spec
                    for spec in specs
                    if spec.id in pending and all(dep in results for dep in spec.depends_on)
                ]
                if not ready:
                    raise ValueError("dependency cycle detected")

                executable: list[CommandSpec] = []
                for spec in ready:
                    dependency_failed = any(not results[dep].get("ok", False) for dep in spec.depends_on)
                    if fail_fast and failed_any or dependency_failed:
                        results[spec.id] = {
                            "id": spec.id,
                            "status": "skipped",
                            "reason": "failed dependency" if dependency_failed else "fail_fast",
                            "ok": False,
                        }
                        pending.pop(spec.id, None)
                        failed_any = True
                        continue
                    source_id = duplicate_of.get(spec.id)
                    if source_id:
                        source = results[source_id]
                        results[spec.id] = {
                            "id": spec.id,
                            "status": "deduplicated",
                            "reused_from": source_id,
                            "classification": CommandClass.READ_ONLY.value,
                            "fingerprint": source.get("fingerprint"),
                            "output": source.get("output", ""),
                            "duration_ms": 0,
                            "ok": source.get("ok", False),
                        }
                        entry = CacheEntry(
                            fingerprint=str(source.get("fingerprint", "")),
                            command=spec.command,
                            compact_output=str(source.get("output", "")),
                            raw_chars=len(str(source.get("output", ""))),
                            compact_chars=len(str(source.get("output", ""))),
                            generation=self.state.generation(session_key),
                            source="intra_batch",
                        )
                        self.state.record_hit(session_key, entry, duplicate=True)
                        pending.pop(spec.id, None)
                        failed_any = failed_any or not results[spec.id]["ok"]
                        continue
                    executable.append(spec)

                read_only = [spec for spec in executable if spec.classification == CommandClass.READ_ONLY]
                sequential = [spec for spec in executable if spec.classification != CommandClass.READ_ONLY]

                if parallel and len(read_only) > 1:
                    with ThreadPoolExecutor(max_workers=min(8, len(read_only)), thread_name_prefix="exec-fuse") as pool:
                        futures = {
                            pool.submit(self._run_one, spec, session_key, cache_enabled, max_chars): spec
                            for spec in read_only
                        }
                        for future in as_completed(futures):
                            spec = futures[future]
                            result = future.result()
                            results[spec.id] = result
                            pending.pop(spec.id, None)
                            failed_any = failed_any or not result.get("ok", False)
                else:
                    sequential = [*read_only, *sequential]

                for spec in sequential:
                    if spec.id not in pending:
                        continue
                    if fail_fast and failed_any:
                        results[spec.id] = {"id": spec.id, "status": "skipped", "reason": "fail_fast", "ok": False}
                    else:
                        results[spec.id] = self._run_one(spec, session_key, cache_enabled, max_chars)
                    pending.pop(spec.id, None)
                    failed_any = failed_any or not results[spec.id].get("ok", False)

            ordered = [results[spec.id] for spec in specs]
            counts: dict[str, int] = {}
            for result in ordered:
                counts[result["status"]] = counts.get(result["status"], 0) + 1
            return json.dumps({
                "ok": all(result.get("ok", False) for result in ordered),
                "summary": {
                    "total": len(ordered),
                    "statuses": counts,
                    "workspace_generation": self.state.generation(session_key),
                },
                "results": ordered,
            }, ensure_ascii=False, separators=(",", ":"))
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    def stats(self, args: dict[str, Any], **kwargs: Any) -> str:
        del args
        session_key = self.state.session_key(kwargs.get("task_id") or kwargs.get("session_id"))
        return json.dumps({"session": session_key, **self.state.snapshot(session_key)}, separators=(",", ":"))
