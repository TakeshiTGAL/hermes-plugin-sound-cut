"""Run the argv from plan.build. The child is not a shell."""

from __future__ import annotations

import subprocess

from . import attendance, audio, gates, paths, plan
from .audio import failure

_TOOLS = {
    "trim": "sound_cut_trim",
    "slice": "sound_cut_slice",
    "convert": "sound_cut_convert",
    "loop": "sound_cut_loop",
}


def execute(kind: str, args: object, session_id: str = "", task_id: str = "") -> dict:
    tool = _TOOLS[kind]
    payload = args if isinstance(args, dict) else {}
    reason = attendance.unattended_reason()
    planned = plan.build(kind, args)
    if reason:
        if planned.get("ok"):
            gates.consume(tool, payload, session_id, task_id, planned["line"], planned["fingerprint"])
        else:
            gates.consume(tool, payload, session_id, task_id, "\0", "\0")
        return failure(
            "approval_blocked",
            attendance.unattended_block(reason)["message"],
            "Use an attended chat. Nothing was written.",
        )
    if not planned.get("ok"):
        decision, _detail = gates.consume(tool, payload, session_id, task_id, "\0", "\0")
        if decision != "denied":
            return failure(
                "mismatch",
                gates.MISMATCH,
                "Call again so the approval matches the file. Nothing was written.",
            )
        return planned
    if not gates.line_is_sendable(planned["line"]):
        gates.consume(tool, payload, session_id, task_id, planned["line"], planned["fingerprint"])
        return failure(
            "approval_not_sent",
            gates.NOT_SENT,
            "Shorten the path and call again. Nothing was written.",
        )
    decision, detail = gates.consume(tool, payload, session_id, task_id, planned["line"], planned["fingerprint"])
    if decision == "denied":
        return failure(
            "approval_denied",
            detail,
            "Ask in an attended chat and approve that command. Nothing was written.",
        )
    if decision == "expired":
        return failure(
            "approval_expired",
            detail,
            "Call again to ask for a new approval. Nothing was written.",
        )
    if decision != "approved":
        return failure(
            "mismatch",
            detail,
            "Call again so the approval matches the file. Nothing was written.",
        )
    try:
        created = paths.create_exclusive(planned["directory"], planned["name"])
    except paths.PathRefused as exc:
        if exc.kind == "exists":
            suggestion = paths.suggest_name(planned["directory"], planned["name"])
            return failure(
                "exists",
                "The output appeared before ffmpeg started, so it was not overwritten.",
                f"Pass output_name {suggestion}." if suggestion else "Pick another output_name.",
                suggested_name=suggestion,
            )
        code, error, nxt = paths.refusal_text(exc, surface="create")
        return failure(code, error, nxt)
    try:
        completed = subprocess.run(
            planned["argv"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=planned["timeout"],
            env=plan.child_env(),
            check=False,
        )
    except subprocess.TimeoutExpired:
        paths.unlink_if_ours(created)
        return failure(
            "timed_out",
            f"ffmpeg was stopped after {planned['timeout']} seconds.",
            "Use a shorter file and call again. Nothing was kept.",
        )
    except OSError as exc:
        paths.unlink_if_ours(created)
        return failure(
            "ffmpeg_failed",
            "ffmpeg could not be started.",
            "Check that the ffmpeg on PATH is runnable. Nothing was kept.",
            detail=type(exc).__name__,
        )
    if completed.returncode != 0:
        paths.unlink_if_ours(created)
        excerpt = completed.stderr.decode("utf-8", errors="replace")[-400:].replace("\n", " ").strip()
        code = "ffmpeg_failed"
        nxt = "Read the ffmpeg message and call again. Nothing was kept."
        if "Unknown encoder" in excerpt or "Encoder not found" in excerpt:
            code = "encoder_missing"
            nxt = "This ffmpeg has no encoder for that format. Install the codec or pass format wav."
        return failure(code, excerpt or "ffmpeg failed.", nxt)
    try:
        final, info = paths.real_file(created)
    except paths.PathRefused:
        paths.unlink_if_ours(created)
        return failure(
            "write_refused",
            "The output was not a regular file after ffmpeg exited.",
            "Nothing was kept.",
        )
    if info.st_nlink != 1:
        paths.unlink_if_ours(final)
        return failure(
            "hard_link",
            "The output had another directory entry, so this name was removed.",
            "Call again with a new output_name.",
        )
    measured = audio.duration_seconds(final)
    duration = None if isinstance(measured, dict) else round(float(measured), 6)
    if duration == 0 or info.st_size <= 44:
        paths.unlink_if_ours(final)
        return failure(
            "empty_output",
            "ffmpeg wrote no usable samples.",
            "Check the input and the span. Nothing was kept.",
        )
    return {
        "ok": True,
        "isError": False,
        "wrote": True,
        "overwritten": False,
        "output": final,
        "duration_seconds": duration,
        "command": planned["argv"],
        "code": "wrote",
    }
