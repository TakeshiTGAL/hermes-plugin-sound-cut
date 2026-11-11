"""Remember the plan the public pre_tool_call hook showed."""

from __future__ import annotations

import hashlib
import json
import threading
import time

APPROVAL_LIMIT = 1500
TTL_S = 600
NOT_SENT = "The approval line would not fit in one message, so it was not sent and nothing was written."
DENIED = "The write was not approved, so nothing was written."
MISMATCH = "The file changed after approval, so ffmpeg was not started."
EXPIRED = "The approval is too old, so nothing was written."

_LOCK = threading.Lock()
_STASH: dict[tuple[str, str, str, str], tuple[str, str, float]] = {}


def line_is_sendable(line: str) -> bool:
    if not line or "\n" in line or "\r" in line or "`" in line:
        return False
    return len(line) <= APPROVAL_LIMIT


def canonical_args(args: dict) -> str:
    return json.dumps(args, sort_keys=True, default=str, separators=(",", ":"))


def rule_key(tool_name: str, args: dict) -> str:
    digest = hashlib.sha256(canonical_args(args).encode("utf-8")).hexdigest()[:16]
    return f"{tool_name}:{digest}"


def approve_directive(tool_name: str, args: dict, line: str) -> dict:
    """The public approve result. rule_key is the sha256 digest of this plan."""
    return {
        "action": "approve",
        "message": line,
        "rule_key": rule_key(tool_name, args),
    }


def _key(tool_name: str, args: dict, session_id: str, task_id: str) -> tuple[str, str, str, str]:
    return (tool_name, canonical_args(args), str(session_id or ""), str(task_id or ""))


def _drop_room(session_id: str, task_id: str) -> None:
    room = (str(session_id or ""), str(task_id or ""))
    for key in [key for key in _STASH if key[2:] == room]:
        del _STASH[key]


def clear() -> None:
    with _LOCK:
        _STASH.clear()


def clear_room(session_id: str = "", task_id: str = "") -> None:
    with _LOCK:
        _drop_room(session_id, task_id)


def remember(
    tool_name: str,
    args: dict,
    session_id: str,
    task_id: str,
    line: str,
    fingerprint: str,
) -> None:
    key = _key(tool_name, args, session_id, task_id)
    with _LOCK:
        _drop_room(session_id, task_id)
        _STASH[key] = (line, fingerprint, time.monotonic())


def consume(
    tool_name: str,
    args: dict,
    session_id: str,
    task_id: str,
    line: str,
    fingerprint: str,
) -> tuple[str, str]:
    """Pop the saved plan. approved, denied, mismatch, or expired."""
    key = _key(tool_name, args, session_id, task_id)
    now = time.monotonic()
    with _LOCK:
        found = _STASH.pop(key, None)
    if found is None:
        return "denied", DENIED
    stored_line, stored_fp, made = found
    if now - made > TTL_S:
        return "expired", EXPIRED
    if stored_line != line or stored_fp != fingerprint:
        return "mismatch", MISMATCH
    return "approved", ""
