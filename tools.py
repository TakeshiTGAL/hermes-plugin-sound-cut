"""Tool handlers. Read tools do not start ffmpeg. Write tools use the stashed plan."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from . import attendance, audio, gates, midi_read, plan, runner

_KINDS = {
    "sound_cut_trim": "trim",
    "sound_cut_slice": "slice",
    "sound_cut_convert": "convert",
    "sound_cut_loop": "loop",
}


def _dump(body: dict) -> str:
    return json.dumps(body, ensure_ascii=False, sort_keys=True)


def _read(fn: Callable[[object], dict]) -> Callable[..., str]:
    def handler(args: dict | None = None, session_id: str = "", task_id: str = "", **_kwargs: Any) -> str:
        del session_id, task_id
        return _dump(fn(args if isinstance(args, dict) else {}))

    return handler


def _write(kind: str) -> Callable[..., str]:
    def handler(args: dict | None = None, session_id: str = "", task_id: str = "", **_kwargs: Any) -> str:
        return _dump(runner.execute(kind, args if isinstance(args, dict) else {}, session_id or "", task_id or ""))

    return handler


HANDLERS = {
    "sound_cut_inspect": _read(audio.inspect_file),
    "sound_cut_midi": _read(midi_read.read_midi),
    "sound_cut_trim": _write("trim"),
    "sound_cut_slice": _write("slice"),
    "sound_cut_convert": _write("convert"),
    "sound_cut_loop": _write("loop"),
}


def on_pre_tool_call(tool_name: str = "", args: dict | None = None, session_id: str = "", task_id: str = "", **_kwargs: Any):
    """Approve a write that starts ffmpeg. Reads and other tools stay silent."""
    kind = _KINDS.get(tool_name or "")
    if kind is None:
        return None
    gates.clear_room(session_id or "", task_id or "")
    reason = attendance.unattended_reason()
    if reason:
        return attendance.unattended_block(reason)
    if not isinstance(args, dict):
        return None
    planned = plan.build(kind, args)
    if not planned.get("ok"):
        return None
    if not gates.line_is_sendable(planned["line"]):
        return {"action": "block", "message": gates.NOT_SENT}
    gates.remember(tool_name, args, session_id or "", task_id or "", planned["line"], planned["fingerprint"])
    return gates.approve_directive(tool_name, args, planned["line"])
