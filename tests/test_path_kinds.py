"""Path refusals keep the cause that the open call reported.

Each test is one row of the input table. A permission error, a read-only
filesystem, and a full disk are not reported as a symlink or as a bad path.
"""

from __future__ import annotations

import errno
import os

from helpers import PLUGIN, call, tone, write_wav

paths = PLUGIN.paths
audio = PLUGIN.audio
midi_read = PLUGIN.midi_read


def _raise_on_create(monkeypatch, err: int):
    real_open = os.open

    def wrapped(path, flags, *args, **kwargs):
        if flags & os.O_CREAT:
            raise OSError(err, os.strerror(err))
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(paths.os, "open", wrapped)


def test_unwritable_directory_is_not_called_a_symlink(root, wav_file, fake_ffmpeg):
    out = root / "locked"
    out.mkdir()
    os.chmod(out, 0o555)
    try:
        args = {
            "input_path": str(wav_file),
            "output_dir": str(out),
            "output_name": "out.wav",
        }
        directive, body = call("sound_cut_trim", args)
        assert directive is not None
        assert directive["action"] == "approve"
        assert body["code"] == "not_writable"
        assert "symlink" not in body["error"].lower()
        assert "permissions" in body["next"]
        assert list(out.iterdir()) == []
        assert not (fake_ffmpeg.parent / "ffmpeg-log.json").exists()
    finally:
        os.chmod(out, 0o755)


def test_sealed_parent_is_not_outside(root):
    sealed = root / "sealed"
    sealed.mkdir()
    wav = write_wav(sealed / "tone.wav", tone(44100, 0.2))
    os.chmod(sealed, 0)
    try:
        body = audio.inspect_file({"input_path": str(wav)})
        assert body["code"] == "not_readable"
        assert "absolute" not in body["error"].lower()
        assert wav.name not in body["error"]
    finally:
        os.chmod(sealed, 0o755)


def test_unreadable_file_is_not_a_decode_error(root):
    wav = write_wav(root / "tone.wav", tone(44100, 0.2))
    os.chmod(wav, 0)
    try:
        body = audio.inspect_file({"input_path": str(wav)})
        assert body["code"] == "not_readable"
        assert body.get("detail") is None
    finally:
        os.chmod(wav, 0o644)


def test_unreadable_midi_is_not_unreadable_format(root):
    path = root / "line.mid"
    path.write_bytes(b"MThd" + b"\x00" * 32)
    os.chmod(path, 0)
    try:
        body = midi_read.read_midi({"input_path": str(path)})
        assert body["code"] == "not_readable"
    finally:
        os.chmod(path, 0o644)


def test_unreadable_trim_does_not_crash(root, wav_file, fake_ffmpeg):
    os.chmod(wav_file, 0)
    out = root / "out"
    out.mkdir()
    try:
        directive, body = call(
            "sound_cut_trim",
            {"input_path": str(wav_file), "output_dir": str(out), "output_name": "out.wav"},
        )
        assert directive is None
        assert body["code"] == "not_readable"
        assert not (out / "out.wav").exists()
        assert not (fake_ffmpeg.parent / "ffmpeg-log.json").exists()
    finally:
        os.chmod(wav_file, 0o644)


def test_create_enospc_is_no_space(root, wav_file, fake_ffmpeg, monkeypatch):
    out = root / "out"
    out.mkdir()
    _raise_on_create(monkeypatch, errno.ENOSPC)
    directive, body = call(
        "sound_cut_trim",
        {"input_path": str(wav_file), "output_dir": str(out), "output_name": "out.wav"},
    )
    assert directive["action"] == "approve"
    assert body["code"] == "no_space"
    assert "symlink" not in body["error"].lower()
    assert not (fake_ffmpeg.parent / "ffmpeg-log.json").exists()


def test_create_erofs_is_read_only(root, wav_file, fake_ffmpeg, monkeypatch):
    out = root / "out"
    out.mkdir()
    _raise_on_create(monkeypatch, errno.EROFS)
    _directive, body = call(
        "sound_cut_trim",
        {"input_path": str(wav_file), "output_dir": str(out), "output_name": "out.wav"},
    )
    assert body["code"] == "read_only"
    assert "symlink" not in body["error"].lower()
    assert not (fake_ffmpeg.parent / "ffmpeg-log.json").exists()


def test_create_eio_is_io_error(root, wav_file, fake_ffmpeg, monkeypatch):
    out = root / "out"
    out.mkdir()
    _raise_on_create(monkeypatch, errno.EIO)
    _directive, body = call(
        "sound_cut_trim",
        {"input_path": str(wav_file), "output_dir": str(out), "output_name": "out.wav"},
    )
    assert body["code"] == "io_error"
    assert "EIO" in body["error"]
    assert "symlink" not in body["error"].lower()
    assert not (fake_ffmpeg.parent / "ffmpeg-log.json").exists()


def test_create_eloop_stays_symlink(root, wav_file, fake_ffmpeg, monkeypatch):
    out = root / "out"
    out.mkdir()
    _raise_on_create(monkeypatch, errno.ELOOP)
    _directive, body = call(
        "sound_cut_trim",
        {"input_path": str(wav_file), "output_dir": str(out), "output_name": "out.wav"},
    )
    assert body["code"] == "symlink"
    assert os.path.realpath("/tmp") in body["next"]


def test_symlink_next_omits_a_noop_substitution(monkeypatch):
    monkeypatch.setattr(paths.os.path, "realpath", lambda spelled: spelled)
    text = paths.symlink_next(wrote=False)
    assert "instead of /tmp" not in text
    assert "instead of /var" not in text
    assert "On macOS, pass /tmp instead of /tmp" not in text
    assert text.startswith("Pass the regular path, not the symlink.")
    assert text.endswith("Nothing was read through the link.")


def test_relative_path_stays_outside_when_cwd_is_a_hermes_home(root, monkeypatch):
    home = root / "hermes"
    home.mkdir()
    wav = write_wav(home / "jump.wav", tone(44100, 0.2))
    monkeypatch.chdir(home)
    relative = audio.inspect_file({"input_path": "jump.wav"})
    assert relative["code"] == "outside"
    absolute = audio.inspect_file({"input_path": str(wav)})
    assert absolute["ok"] is True
    assert absolute["duration_seconds"] == 0.2


def test_directory_symlink_is_still_refused(root, wav_file):
    real = root / "real"
    real.mkdir()
    link = root / "link"
    link.symlink_to(real)
    body = call("sound_cut_trim", {"input_path": str(wav_file), "output_dir": str(link)})[1]
    assert body["code"] == "symlink"
    assert list(real.iterdir()) == []
