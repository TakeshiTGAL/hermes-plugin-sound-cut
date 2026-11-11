"""The ffmpeg on PATH trims, slices, converts, and loops a synthesized tone."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from helpers import PLUGIN, call, padded_tone, tone, write_wav

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not on PATH")


def _ffmpeg() -> str:
    return shutil.which("ffmpeg")


def test_trim_slice_loop_and_mp3(root):
    source = write_wav(root / "padded.wav", padded_tone())
    out = root / "out"
    out.mkdir()
    trim = call("sound_cut_trim", {"input_path": str(source), "output_dir": str(out)})
    assert trim[0]["action"] == "approve"
    assert trim[1]["ok"] is True
    assert 0.30 <= trim[1]["duration_seconds"] <= 0.75
    tone_path = write_wav(root / "tone.wav", tone(44100, 1.0))
    sliced = call("sound_cut_slice", {
        "input_path": str(tone_path),
        "output_dir": str(out),
        "start_seconds": 0.25,
        "end_seconds": 0.75,
        "output_name": "span.wav",
    })
    assert sliced[1]["ok"] is True
    assert 0.40 <= sliced[1]["duration_seconds"] <= 0.60
    looped = call("sound_cut_loop", {
        "input_path": str(tone_path),
        "output_dir": str(out),
        "output_name": "loop.wav",
        "crossfade_ms": 30,
    })
    assert looped[1]["ok"] is True
    assert looped[1]["duration_seconds"] < 0.99
    assert "0:a:0" not in looped[1]["command"]
    assert "[out]" in looped[1]["command"]
    spaced = root / "sound cut"
    spaced.mkdir()
    spaced_trim = call("sound_cut_trim", {
        "input_path": str(source),
        "output_dir": str(spaced),
        "output_name": "spaced.wav",
    })
    assert spaced_trim[1]["ok"] is True
    assert " " in spaced_trim[1]["output"]
    converted = call("sound_cut_convert", {
        "input_path": str(tone_path),
        "output_dir": str(out),
        "format": "mp3",
        "output_name": "tone.mp3",
    })
    assert converted[1]["ok"] is True
    inspected = PLUGIN.audio.inspect_file({"input_path": converted[1]["output"]})
    assert inspected["ok"] is True
    assert inspected["duration_seconds"] == pytest.approx(1.0, abs=0.15)


def test_opus_inspect_does_not_start_ffmpeg_and_ogg_reports_the_encoder(root, monkeypatch):
    tone_path = write_wav(root / "tone.wav", tone(44100, 0.4))
    opus = root / "tone.opus"
    encoded = subprocess.run(
        [_ffmpeg(), "-hide_banner", "-nostdin", "-y", "-i", str(tone_path), "-c:a", "libopus", str(opus)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if encoded.returncode != 0:
        pytest.skip("this ffmpeg cannot write opus")
    started = {"ran": False}

    def refuse(*_args, **_kwargs):
        started["ran"] = True
        raise AssertionError("inspect started ffmpeg")

    monkeypatch.setattr(PLUGIN.runner.subprocess, "run", refuse)
    body = PLUGIN.audio.inspect_file({"input_path": str(opus)})
    assert body["code"] == "decode_unsupported"
    assert started["ran"] is False
    monkeypatch.undo()
    encoders = subprocess.run(
        [_ffmpeg(), "-hide_banner", "-encoders"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        text=True,
    )
    out = root / "out"
    out.mkdir()
    ogg = call("sound_cut_convert", {
        "input_path": str(tone_path),
        "output_dir": str(out),
        "format": "ogg",
        "output_name": "tone.ogg",
    })
    if "libvorbis" not in encoders.stdout:
        assert ogg[1]["code"] == "encoder_missing"
        assert not (out / "tone.ogg").exists()
    else:
        assert ogg[1]["ok"] is True
        assert Path(ogg[1]["output"]).is_file()
