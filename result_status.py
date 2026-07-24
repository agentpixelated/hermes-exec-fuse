"""Normalize structured success and failure signals from terminal backends."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

_FAILURE_STATUSES = {"error", "failed", "failure", "cancelled", "canceled", "timed_out", "timeout"}


@dataclass(frozen=True)
class ResultAssessment:
    ok: bool
    reason: str | None = None
    exit_code: int | None = None


def _numeric_exit_code(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def assess_terminal_result(raw: Any) -> ResultAssessment:
    """Interpret structured fields without scanning ordinary output text."""
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return ResultAssessment(ok=True)
        return assess_terminal_result(parsed)

    if not isinstance(raw, dict):
        return ResultAssessment(ok=True)

    error = raw.get("error")
    if error:
        return ResultAssessment(ok=False, reason=str(error))

    for field in ("ok", "success"):
        if field in raw and raw[field] is False:
            return ResultAssessment(ok=False, reason=f"{field}=false")

    for field in ("exit_code", "return_code", "returncode"):
        if field not in raw:
            continue
        exit_code = _numeric_exit_code(raw[field])
        if exit_code is not None and exit_code != 0:
            return ResultAssessment(ok=False, reason=f"{field}={exit_code}", exit_code=exit_code)

    status = raw.get("status")
    if isinstance(status, str) and status.strip().lower() in _FAILURE_STATUSES:
        return ResultAssessment(ok=False, reason=f"status={status.strip().lower()}")

    return ResultAssessment(ok=True)
