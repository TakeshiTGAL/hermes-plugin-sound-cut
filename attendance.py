"""Refuse write turns that cannot show a person the approval line.

Hermes checks a saved always rule before its own cron and unattended
refusal. The hook therefore refuses those turns itself. Yolo and
approvals off are not read here.
"""

from __future__ import annotations

import contextvars
import os
from typing import Any

_TRUTHY = frozenset({"1", "true", "yes", "on"})
_UNATTENDED_PLATFORMS = frozenset({"webhook", "msgraph_webhook", "api_server"})
_CTX: Any = None


def bind_context(ctx: Any) -> None:
    """Store the ctx from register. The check reads current_cron_execution on it."""
    global _CTX
    _CTX = ctx


def _context_values(name: str) -> list[Any]:
    try:
        current = contextvars.copy_context()
    except Exception:
        return []
    found = []
    for var, value in current.items():
        if getattr(var, "name", None) == name:
            found.append(value)
    return found


def session_flag(name: str) -> str:
    """A set string on a ContextVar of this name, else the process environment."""
    explicit_empty = False
    for value in _context_values(name):
        if isinstance(value, bool):
            if value:
                return "1"
            explicit_empty = True
            continue
        if not isinstance(value, str):
            continue
        if value == "":
            explicit_empty = True
            continue
        return value
    if explicit_empty:
        return ""
    return str(os.environ.get(name) or "")


def _flag_on(name: str) -> bool:
    return session_flag(name).strip().lower() in _TRUTHY


def unattended_reason() -> str | None:
    """Why this turn cannot ask a person, or None when the hook may ask.

    A missing current_cron_execution reader is not cron. A reader that raises
    is treated as cron so the write does not run.
    """
    raw_host = os.environ.get("HERMES_PLUGIN_HOST_PROCESS", "")
    if raw_host.strip() not in {"", "0"}:
        return "the plugin host"
    if _flag_on("HERMES_CRON_SESSION"):
        return "a cron job"
    reader = getattr(_CTX, "current_cron_execution", None)
    if callable(reader):
        try:
            mark = reader()
        except Exception:
            return "a turn whose cron mark could not be read"
        if mark is not None:
            return "a cron job"
    if _flag_on("HERMES_SINGLE_QUERY_SESSION"):
        return "a single-query run (hermes -q)"
    platform = session_flag("HERMES_SESSION_PLATFORM").strip().lower()
    if platform in _UNATTENDED_PLATFORMS:
        return "an unattended " + platform + " session"
    return None


def unattended_block(reason: str) -> dict:
    return {
        "action": "block",
        "message": (
            "BLOCKED: "
            + reason
            + " cannot write audio, even after always. Nothing was written."
        ),
    }
