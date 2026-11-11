"""Read tools measure length, peak, and an estimated tempo. They do not start ffmpeg."""

from __future__ import annotations

import os
import socket
from pathlib import Path

import pytest

from helpers import PLUGIN, clicks, fingerprint, tone, write_wav

audio = PLUGIN.audio


def test_click_train_estimates_120(root: Path):
    path = write_wav(root / "clicks.wav", clicks(44100, 2.0, 120))
    body = audio.inspect_file({"input_path": str(path)})
    assert body["ok"] is True
    assert body["wrote"] is False
    assert body["tempo_kind"] == "estimated"
    assert body["tempo_bpm_estimated"] == pytest.approx(120.0, abs=4.0)
    assert "tempo" not in body
    assert "bpm" not in body
    assert body["duration_seconds"] == pytest.approx(2.0, abs=0.02)
    assert body["peak_dbfs"] is not None and body["peak_dbfs"] < 0


def test_sine_and_silence_do_not_invent_a_tempo(root: Path):
    sine = write_wav(root / "sine.wav", tone(44100, 2.0))
    sine_body = audio.inspect_file({"input_path": str(sine)})
    assert sine_body["tempo_bpm_estimated"] is None
    assert sine_body["tempo_kind"] == "estimated"
    assert sine_body["peak_dbfs"] is not None
    named = write_wav(root / "120bpm-click.wav", tone(44100, 2.0))
    named_body = audio.inspect_file({"input_path": str(named)})
    assert named_body["tempo_bpm_estimated"] is None
    quiet = write_wav(root / "silence.wav", [0] * 44100 * 2)
    quiet_body = audio.inspect_file({"input_path": str(quiet)})
    assert quiet_body["peak_dbfs"] is None
    assert quiet_body["peak_sample"] == 0
    assert quiet_body["tempo_bpm_estimated"] is None
    assert "loud" not in quiet_body["peak_reason"].lower()


def test_short_clip_has_no_tempo(root: Path):
    path = write_wav(root / "short.wav", tone(44100, 0.4))
    body = audio.inspect_file({"input_path": str(path)})
    assert body["ok"] is True
    assert body["tempo_bpm_estimated"] is None
    assert "1 second" in body["tempo_reason"]


def test_inspect_does_not_start_ffmpeg_or_open_a_socket(root: Path, monkeypatch):
    path = write_wav(root / "tone.wav", tone(44100, 0.2))
    before = fingerprint(root)

    def refuse_process(*_args, **_kwargs):
        raise AssertionError("a read tool started a process")

    def refuse_socket(*_args, **_kwargs):
        raise AssertionError("a read tool opened a socket")

    monkeypatch.setattr(PLUGIN.runner.subprocess, "run", refuse_process)
    monkeypatch.setattr(socket, "socket", refuse_socket)
    monkeypatch.setattr(socket, "create_connection", refuse_socket)
    body = audio.inspect_file({"input_path": str(path)})
    assert body["ok"] is True
    assert fingerprint(root) == before


def test_missing_file_is_not_a_claim_about_other_folders(root: Path):
    missing = root / "missing.wav"
    body = audio.inspect_file({"input_path": str(missing)})
    assert body["ok"] is False
    assert body["code"] == "missing"
    assert body["error_type"] == "missing"
    assert "other folders" in body["next"]
    assert not missing.exists()


def test_symlink_input_is_not_followed(root: Path):
    target = write_wav(root / "real.wav", tone(44100, 0.2))
    link = root / "link.wav"
    link.symlink_to(target)
    body = audio.inspect_file({"input_path": str(link)})
    assert body["code"] == "symlink"
    assert target.stat().st_size > 0


def test_dotdot_and_relative_paths_are_refused(root: Path):
    path = write_wav(root / "tone.wav", tone(44100, 0.2))
    dotted = str(root / "sub" / ".." / path.name)
    (root / "sub").mkdir()
    body = audio.inspect_file({"input_path": dotted})
    assert body["code"] == "outside"
    relative = audio.inspect_file({"input_path": path.name})
    assert relative["code"] == "outside"


def test_unknown_argument_and_empty_and_too_large(root: Path, monkeypatch):
    path = write_wav(root / "tone.wav", tone(44100, 0.2))
    unknown = audio.inspect_file({"input_path": str(path), "overwrite": True})
    assert unknown["code"] == "bad_argument"
    empty = root / "empty.wav"
    empty.write_bytes(b"")
    assert audio.inspect_file({"input_path": str(empty)})["code"] == "empty_input"
    monkeypatch.setattr(audio, "MAX_BYTES", 10)
    assert audio.inspect_file({"input_path": str(path)})["code"] == "too_large"
    assert audio.inspect_file({"input_path": str(root)})["code"] == "not_a_file"


def test_quote_and_backtick_in_the_path_are_refused(root: Path):
    body = audio.inspect_file({"input_path": str(root / "a`b.wav")})
    assert body["code"] == "bad_argument"
    quoted = audio.inspect_file({"input_path": str(root / "a'b.wav")})
    assert quoted["code"] == "bad_argument"


def test_macos_tmp_symlink_is_not_followed(root: Path):
    if not os.path.islink("/tmp"):
        pytest.skip("this machine's /tmp is not a symlink")
    path = write_wav(Path(os.path.realpath("/tmp")) / "sound-cut-inspect-real.wav", tone(44100, 0.2))
    try:
        body = audio.inspect_file({"input_path": "/tmp/sound-cut-inspect-real.wav"})
        assert body["code"] == "symlink"
        assert os.path.realpath("/tmp") in body["next"]
        assert os.path.realpath("/var") in body["next"]
        missing = audio.inspect_file({"input_path": "/tmp/sound-cut-no-such-file.wav"})
        assert missing["code"] == "symlink"
        assert os.path.realpath("/tmp") in missing["next"]
        assert path.is_file()
    finally:
        path.unlink(missing_ok=True)


def test_read_hook_does_not_approve(wav_file: Path):
    directive = PLUGIN.tools.on_pre_tool_call(
        "sound_cut_inspect", {"input_path": str(wav_file)}, session_id="s", task_id="t"
    )
    assert directive is None
