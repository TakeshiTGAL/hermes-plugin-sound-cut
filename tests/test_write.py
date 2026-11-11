"""Write tools run the same ffmpeg argv the approval line showed."""

from __future__ import annotations

import json
import os
import shlex
from pathlib import Path

import pytest

from helpers import PLUGIN, call

plan = PLUGIN.plan
runner = PLUGIN.runner


def _trim_args(wav: Path, out: Path, **extra):
    body = {"input_path": str(wav), "output_dir": str(out)}
    body.update(extra)
    return body


def _log(binary: Path) -> dict:
    return json.loads((binary.parent / "ffmpeg-log.json").read_text(encoding="utf-8"))


def test_trim_runs_the_argv_from_the_approval_line(root, wav_file, fake_ffmpeg):
    out = root / "out"
    out.mkdir()
    args = _trim_args(wav_file, out)
    directive, body = call("sound_cut_trim", args)
    assert directive["action"] == "approve"
    assert "\n" not in directive["message"]
    assert "`" not in directive["message"]
    assert "Command: " in directive["message"]
    assert str(wav_file) in directive["message"]
    assert body["ok"] is True
    assert body["wrote"] is True
    assert body["overwritten"] is False
    assert body["code"] == "wrote"
    assert shlex.join(body["command"]) in directive["message"]
    logged = _log(fake_ffmpeg)
    assert logged["argv"] == body["command"]
    for name in ("PATH", "HOME"):
        assert name in logged["env"]
    assert Path(body["output"]).is_file()
    assert body["command"][0] == str(fake_ffmpeg.resolve()) or body["command"][0].endswith("/ffmpeg")


def test_proxy_variables_are_not_copied(root, wav_file, fake_ffmpeg, monkeypatch):
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "ftp_proxy",
        "FTP_PROXY",
    ):
        monkeypatch.setenv(name, "http://127.0.0.1:9")
    out = root / "out"
    out.mkdir()
    _directive, body = call("sound_cut_trim", _trim_args(wav_file, out))
    assert body["ok"] is True
    logged = _log(fake_ffmpeg)
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "ftp_proxy",
        "FTP_PROXY",
    ):
        assert name not in logged["env"]


def test_existing_file_is_not_overwritten_and_a_free_name_is_returned(root, wav_file, fake_ffmpeg):
    out = root / "out"
    out.mkdir()
    existing = out / "tone-trim.wav"
    existing.write_bytes(b"KEEP")
    directive, body = call("sound_cut_trim", _trim_args(wav_file, out))
    assert directive is None
    assert body["code"] == "exists"
    assert body["code"] != "approval_denied"
    assert body["suggested_name"] == "tone-trim-2.wav"
    assert existing.read_bytes() == b"KEEP"
    assert not (fake_ffmpeg.parent / "ffmpeg-log.json").exists()


def test_plan_errors_are_not_turned_into_approval_denied(root, wav_file, fake_ffmpeg, monkeypatch):
    out = root / "out"
    out.mkdir()
    missing_dir = root / "no-such-dir"
    directive, body = call("sound_cut_trim", _trim_args(wav_file, missing_dir))
    assert directive is None
    assert body["code"] == "missing"
    assert not missing_dir.exists()
    monkeypatch.setenv("PATH", str(root / "empty-path"))
    (root / "empty-path").mkdir()
    directive, body = call("sound_cut_slice", {
        "input_path": str(wav_file),
        "output_dir": str(out),
        "start_seconds": 0.1,
        "end_seconds": 0.2,
    })
    assert directive is None
    assert body["code"] == "ffmpeg_missing"
    assert "Install ffmpeg" in body["next"]


def test_bool_unknown_and_bad_names_are_refused(root, wav_file, fake_ffmpeg):
    out = root / "out"
    out.mkdir()
    boolean = call("sound_cut_trim", _trim_args(wav_file, out, silence_threshold_db=True))
    assert boolean[0] is None
    assert boolean[1]["code"] == "bad_argument"
    unknown = call("sound_cut_trim", _trim_args(wav_file, out, overwrite=True))
    assert unknown[1]["code"] == "bad_argument"
    for name in ("../x.wav", "nested/x.wav", ".hidden.wav", "a`b.wav", "noext"):
        body = call("sound_cut_trim", _trim_args(wav_file, out, output_name=name))[1]
        assert body["ok"] is False
        assert body["code"] in {"bad_argument", "bad_format", "outside"}
        assert not (fake_ffmpeg.parent / "ffmpeg-log.json").exists()


def test_unicode_name_and_a_directory_with_a_space(root, wav_file, fake_ffmpeg):
    spaced = root / "sound cut"
    spaced.mkdir()
    directive, body = call(
        "sound_cut_convert",
        _trim_args(wav_file, spaced, output_name="クリック.wav", format="wav"),
    )
    assert directive["action"] == "approve"
    assert body["ok"] is True
    assert body["output"].endswith("クリック.wav")
    assert " " in body["output"]
    assert Path(body["output"]).is_file()


def test_second_call_other_session_and_changed_bytes(root, wav_file, fake_ffmpeg):
    out = root / "out"
    out.mkdir()
    args = _trim_args(wav_file, out, output_name="once.wav")
    first = call("sound_cut_trim", args)
    assert first[1]["ok"] is True
    (out / "once.wav").unlink()
    (fake_ffmpeg.parent / "ffmpeg-log.json").write_text("ONCE", encoding="utf-8")
    second = call("sound_cut_trim", args, hook=False)
    assert second[1]["code"] == "approval_denied"
    assert not (out / "once.wav").exists()
    assert (fake_ffmpeg.parent / "ffmpeg-log.json").read_text(encoding="utf-8") == "ONCE"
    other_args = _trim_args(wav_file, out, output_name="other.wav")
    assert PLUGIN.tools.on_pre_tool_call("sound_cut_trim", other_args, session_id="other", task_id="t")["action"] == "approve"
    denied = json.loads(
        PLUGIN.tools.HANDLERS["sound_cut_trim"](other_args, session_id="s", task_id="t")
    )
    assert denied["code"] == "approval_denied"
    assert not (out / "other.wav").exists()
    changed = _trim_args(wav_file, out, output_name="changed.wav")
    assert PLUGIN.tools.on_pre_tool_call("sound_cut_trim", changed, session_id="s", task_id="t")["action"] == "approve"
    wav_file.write_bytes(wav_file.read_bytes() + b"\x00\x00")
    (fake_ffmpeg.parent / "ffmpeg-log.json").unlink()
    mismatch = call("sound_cut_trim", changed, hook=False)
    assert mismatch[1]["code"] == "mismatch"
    assert not (fake_ffmpeg.parent / "ffmpeg-log.json").exists()
    assert not (out / "changed.wav").exists()


def test_expired_approval_writes_nothing(root, wav_file, fake_ffmpeg, monkeypatch):
    out = root / "out"
    out.mkdir()
    args = _trim_args(wav_file, out, output_name="old.wav")
    assert PLUGIN.tools.on_pre_tool_call("sound_cut_trim", args, session_id="s", task_id="t")["action"] == "approve"
    real = PLUGIN.gates.time.monotonic
    monkeypatch.setattr(PLUGIN.gates.time, "monotonic", lambda: real() + PLUGIN.gates.TTL_S + 5)
    body = call("sound_cut_trim", args, hook=False)[1]
    assert body["code"] == "approval_expired"
    assert not (out / "old.wav").exists()


def test_oversized_approval_line_writes_nothing(root, wav_file, fake_ffmpeg, monkeypatch):
    monkeypatch.setattr(PLUGIN.gates, "APPROVAL_LIMIT", 40)
    out = root / "out"
    out.mkdir()
    directive, body = call("sound_cut_trim", _trim_args(wav_file, out, output_name="long.wav"))
    assert directive["action"] == "block"
    assert "not sent" in directive["message"]
    assert body["code"] == "approval_not_sent"
    assert not (out / "long.wav").exists()
    assert not (fake_ffmpeg.parent / "ffmpeg-log.json").exists()


def test_encoder_failure_timeout_and_empty_output_remove_the_file(root, wav_file, fake_ffmpeg, monkeypatch):
    out = root / "out"
    out.mkdir()
    ogg = call("sound_cut_convert", _trim_args(wav_file, out, format="ogg", output_name="clip.ogg"))
    assert ogg[1]["code"] == "encoder_missing"
    assert not (out / "clip.ogg").exists()
    failed = call("sound_cut_trim", _trim_args(wav_file, out, output_name="fail-me.wav"))
    assert failed[1]["code"] == "ffmpeg_failed"
    assert not (out / "fail-me.wav").exists()
    monkeypatch.setattr(plan, "_TIMEOUT", 1)
    sleepy = call("sound_cut_trim", _trim_args(wav_file, out, output_name="sleep-please.wav"))
    assert sleepy[1]["code"] == "timed_out"
    assert not (out / "sleep-please.wav").exists()
    empty = call("sound_cut_trim", _trim_args(wav_file, out, output_name="empty-please.wav"))
    assert empty[1]["code"] == "empty_output"
    assert not (out / "empty-please.wav").exists()


def test_a_hard_link_created_during_the_run_is_removed(root, wav_file, fake_ffmpeg, monkeypatch):
    out = root / "out"
    out.mkdir()
    other = root / "other-name.wav"

    def linked(argv, **_kwargs):
        os.link(argv[-1], other)
        return __import__("subprocess").CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(runner.subprocess, "run", linked)
    body = call("sound_cut_trim", _trim_args(wav_file, out, output_name="linked.wav"))[1]
    assert body["code"] == "hard_link"
    assert not (out / "linked.wav").exists()
    assert other.is_file()


def test_a_symlink_at_the_output_name_is_not_followed(root, wav_file, fake_ffmpeg):
    out = root / "out"
    out.mkdir()
    outside = root / "outside.wav"
    outside.write_bytes(b"SAFE")
    args = _trim_args(wav_file, out, output_name="linked.wav")
    assert PLUGIN.tools.on_pre_tool_call("sound_cut_trim", args, session_id="s", task_id="t")["action"] == "approve"
    (out / "linked.wav").symlink_to(outside)
    body = call("sound_cut_trim", args, hook=False)[1]
    assert body["ok"] is False
    assert body["code"] == "mismatch"
    assert outside.read_bytes() == b"SAFE"
    assert not (fake_ffmpeg.parent / "ffmpeg-log.json").exists()


def test_parent_symlink_and_slice_past_the_end(root, wav_file, fake_ffmpeg):
    real = root / "real"
    real.mkdir()
    link = root / "link"
    link.symlink_to(real)
    body = call("sound_cut_trim", _trim_args(wav_file, link))[1]
    assert body["code"] == "symlink"
    assert os.path.realpath("/tmp") in body["next"]
    assert os.path.realpath("/var") in body["next"]
    assert list(real.iterdir()) == []
    out = root / "out"
    out.mkdir()
    late = call("sound_cut_slice", {
        "input_path": str(wav_file),
        "output_dir": str(out),
        "start_seconds": 0,
        "end_seconds": 50,
    })
    assert late[0] is None
    assert late[1]["code"] == "bad_argument"
    assert "past the file" in late[1]["error"]


def test_unattended_handler_writes_nothing_even_after_a_stash(root, wav_file, fake_ffmpeg, monkeypatch):
    out = root / "out"
    out.mkdir()
    args = _trim_args(wav_file, out, output_name="cron.wav")
    assert PLUGIN.tools.on_pre_tool_call("sound_cut_trim", args, session_id="s", task_id="t")["action"] == "approve"
    monkeypatch.setenv("HERMES_CRON_SESSION", "1")
    body = call("sound_cut_trim", args, hook=False)[1]
    assert body["code"] == "approval_blocked"
    assert "always" in body["error"]
    assert not (out / "cron.wav").exists()
    assert not (fake_ffmpeg.parent / "ffmpeg-log.json").exists()


@pytest.mark.parametrize(
    "env",
    [
        {"HERMES_CRON_SESSION": "1"},
        {"HERMES_SINGLE_QUERY_SESSION": "1"},
        {"HERMES_SESSION_PLATFORM": "webhook"},
        {"HERMES_SESSION_PLATFORM": "msgraph_webhook"},
        {"HERMES_SESSION_PLATFORM": "api_server"},
        {"HERMES_PLUGIN_HOST_PROCESS": "1"},
    ],
)
def test_unattended_flags_block_before_ffmpeg(root, wav_file, fake_ffmpeg, monkeypatch, env):
    out = root / "out"
    out.mkdir()
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    directive, body = call("sound_cut_trim", _trim_args(wav_file, out, output_name="no.wav"))
    assert directive["action"] == "block"
    assert body["code"] == "approval_blocked"
    assert not (out / "no.wav").exists()


def test_public_cron_reader_present_missing_and_raising(root, wav_file, fake_ffmpeg):
    out = root / "out"
    out.mkdir()
    args = _trim_args(wav_file, out)

    class Present:
        current_cron_execution = staticmethod(lambda: object())

    PLUGIN.attendance.bind_context(Present())
    directive, body = call("sound_cut_trim", args)
    assert directive["action"] == "block"
    assert body["wrote"] is False
    assert "cron" in body["error"]
    assert not (out / "tone-trim.wav").exists()

    class Missing:
        pass

    PLUGIN.attendance.bind_context(Missing())
    assert PLUGIN.attendance.unattended_reason() is None
    directive = PLUGIN.tools.on_pre_tool_call("sound_cut_trim", args, session_id="s", task_id="t")
    assert directive["action"] == "approve"

    class Raising:
        @staticmethod
        def current_cron_execution():
            raise RuntimeError("unreadable")

    PLUGIN.attendance.bind_context(Raising())
    directive, body = call("sound_cut_trim", args)
    assert directive["action"] == "block"
    assert body["wrote"] is False
    assert "cron mark" in body["error"]
    assert not (out / "tone-trim.wav").exists()


def test_loop_of_an_undecoded_file_does_not_start_ffmpeg(root, fake_ffmpeg):
    opus = root / "clip.opus"
    opus.write_bytes(b"not really opus but the suffix is")
    out = root / "out"
    out.mkdir()
    directive, body = call("sound_cut_loop", {"input_path": str(opus), "output_dir": str(out)})
    assert directive is None
    assert body["code"] in {"decode_unsupported", "midi_unreadable", "empty_input"}
    assert body["code"] != "approval_denied"
    assert not (fake_ffmpeg.parent / "ffmpeg-log.json").exists()
