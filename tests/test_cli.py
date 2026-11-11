"""The public hermes sound-cut call command."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from helpers import PLUGIN, write_wav, tone


def _call(tool: str, payload: object, capsys):
    code = PLUGIN.cli.handle(
        argparse.Namespace(command="call", tool=tool, json=json.dumps(payload))
    )
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_cli_inspect_prints_estimated_tempo(root: Path, capsys):
    wav = write_wav(root / "tone.wav", tone(44100, 0.5))
    code, out, err = _call("sound_cut_inspect", {"input_path": str(wav)}, capsys)
    assert code == 0
    assert err == ""
    body = json.loads(out)
    assert body["ok"] is True
    assert body["tempo_kind"] == "estimated"
    assert body["wrote"] is False


def test_cli_relative_path_is_not_success(capsys):
    code, out, err = _call("sound_cut_inspect", {"input_path": "tone.wav"}, capsys)
    assert code == 0
    assert err == ""
    body = json.loads(out)
    assert body["ok"] is False
    assert body["wrote"] is False


def test_cli_does_not_print_hidden_file_bytes(root: Path, capsys):
    marker = "SYNTHETIC-MARKER-sound-cut"
    for name in (".git-credentials", ".npmrc", "id_rsa", "auth.json"):
        path = root / name
        path.write_text(f"password={marker}\n", encoding="utf-8")
        code, out, err = _call("sound_cut_inspect", {"input_path": str(path)}, capsys)
        assert code == 0
        assert marker not in out
        assert marker not in err
        body = json.loads(out)
        assert body["ok"] is False
        assert body["wrote"] is False


def test_cli_write_does_not_start_ffmpeg(root: Path, monkeypatch, capsys):
    wav = write_wav(root / "tone.wav", tone(44100, 0.5))
    out_dir = root / "out"
    out_dir.mkdir()

    def boom(*_args, **_kwargs):
        raise AssertionError("ffmpeg started")

    monkeypatch.setattr(PLUGIN.runner.subprocess, "run", boom)
    code, out, err = _call(
        "sound_cut_trim",
        {"input_path": str(wav), "output_dir": str(out_dir), "output_name": "cut.wav"},
        capsys,
    )
    assert code == 0
    assert err == ""
    body = json.loads(out)
    assert body["ok"] is False
    assert body["code"] == "approval_denied"
    assert list(out_dir.iterdir()) == []


def test_cli_cron_write_stays_blocked(root: Path, monkeypatch, capsys):
    wav = write_wav(root / "tone.wav", tone(44100, 0.5))
    out_dir = root / "out"
    out_dir.mkdir()
    monkeypatch.setenv("HERMES_CRON_SESSION", "1")

    def boom(*_args, **_kwargs):
        raise AssertionError("ffmpeg started")

    monkeypatch.setattr(PLUGIN.runner.subprocess, "run", boom)
    code, out, _err = _call(
        "sound_cut_trim",
        {"input_path": str(wav), "output_dir": str(out_dir)},
        capsys,
    )
    body = json.loads(out)
    assert code == 0
    assert body["code"] == "approval_blocked"
    assert list(out_dir.iterdir()) == []


def test_cli_rejects_a_bad_payload(capsys):
    assert PLUGIN.cli.handle(argparse.Namespace(command="call", tool="sound_cut_inspect", json="[]")) == 2
    assert "object" in capsys.readouterr().err
    assert PLUGIN.cli.handle(argparse.Namespace(command="call", tool="sound_cut_inspect", json="{")) == 2
    assert "could not be read" in capsys.readouterr().err


def test_cli_unknown_tool(capsys):
    assert PLUGIN.cli.handle(argparse.Namespace(command="call", tool="sound_cut_missing", json="{}")) == 2
    assert "Unknown tool" in capsys.readouterr().err


def test_no_public_file_parses_the_hermes_launcher():
    root = Path(__file__).resolve().parents[1]
    banned = ("sound_cut_follow", "sed -n", "#!/bin/sh", 'exec "')
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in {".git", "__pycache__", "tests"} for part in path.parts):
            continue
        if path.suffix not in {".py", ".md", ".yaml", ".yml"}:
            continue
        text = path.read_text(encoding="utf-8")
        for item in banned:
            assert item not in text, (path.name, item)
