"""Pytest fixtures. Import helpers from tests, not this module."""

from __future__ import annotations

from pathlib import Path

import pytest

from helpers import (
    PLUGIN,
    _UNATTENDED,
    padded_tone,
    physical,
    write_fake_ffmpeg,
    write_wav,
)


@pytest.fixture(autouse=True)
def _reset_plugin_state(monkeypatch):
    for name in _UNATTENDED:
        monkeypatch.delenv(name, raising=False)
    PLUGIN.gates.clear()
    PLUGIN.attendance.bind_context(None)
    yield
    PLUGIN.gates.clear()
    PLUGIN.attendance.bind_context(None)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return physical(tmp_path)


@pytest.fixture
def wav_file(root: Path) -> Path:
    return write_wav(root / "tone.wav", padded_tone())


@pytest.fixture
def fake_ffmpeg(root: Path, monkeypatch):
    import os

    binary = write_fake_ffmpeg(root / "bin")
    monkeypatch.setenv("PATH", str(binary.parent) + os.pathsep + os.environ.get("PATH", ""))
    return binary
