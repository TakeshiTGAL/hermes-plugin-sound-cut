"""Load the plugin as a package and share synthesized fixtures."""

from __future__ import annotations

import importlib.util
import json
import math
import os
import struct
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_UNATTENDED = (
    "HERMES_CRON_SESSION",
    "HERMES_SINGLE_QUERY_SESSION",
    "HERMES_SESSION_PLATFORM",
    "HERMES_PLUGIN_HOST_PROCESS",
    "HERMES_YOLO_MODE",
    "HERMES_INTERACTIVE",
)


def _load_plugin():
    name = "sound_cut"
    loaded = sys.modules.get(name)
    if loaded is not None and getattr(loaded, "__file__", None):
        return loaded
    init = ROOT / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        name, init, submodule_search_locations=[str(ROOT)]
    )
    module = importlib.util.module_from_spec(spec)
    module.__package__ = name
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


PLUGIN = _load_plugin()


def physical(path: Path) -> Path:
    """A directory whose every component is a real directory.

    pytest's temporary directory is often under /var, and macOS /var is a symlink.
    """
    resolved = Path(os.path.realpath(path))
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def write_wav(path: Path, samples, rate: int = 44100) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = b"".join(
        struct.pack("<h", max(-32767, min(32767, int(sample)))) for sample in samples
    )
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(data)
    return path


def tone(rate: int, seconds: float, freq: float = 440, amp: int = 12000) -> list[int]:
    count = int(rate * seconds)
    return [int(amp * math.sin(2 * math.pi * freq * i / rate)) for i in range(count)]


def clicks(rate: int, seconds: float, bpm: float = 120) -> list[int]:
    count = int(rate * seconds)
    period = int(rate * 60 / bpm)
    burst = int(rate * 0.02)
    samples = []
    for index in range(count):
        if period and index % period < burst:
            samples.append(int(20000 * math.sin(2 * math.pi * 1000 * index / rate)))
        else:
            samples.append(0)
    return samples


def padded_tone(rate: int = 44100) -> list[int]:
    return [0] * (rate // 4) + tone(rate, 0.5) + [0] * (rate // 4)


def write_fake_ffmpeg(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / "ffmpeg"
    script.write_text(
        """#!/usr/bin/env python3
import json, os, struct, sys, time, wave
from pathlib import Path
here = Path(__file__).resolve().parent
text = " ".join(sys.argv)
(here / "ffmpeg-log.json").write_text(
    json.dumps({"argv": sys.argv, "env": sorted(os.environ)}),
    encoding="utf-8",
)
if "fail-me" in text:
    sys.stderr.write("boom failure\\n")
    sys.exit(3)
if "libvorbis" in text:
    sys.stderr.write("Unknown encoder 'libvorbis'\\n")
    sys.exit(1)
if "sleep-please" in text:
    time.sleep(5)
    sys.exit(0)
if "empty-please" in text:
    sys.exit(0)
out = Path(sys.argv[-1])
rate = 8000
count = 800
frames = b"".join(struct.pack("<h", 1000 if i % 20 < 4 else 0) for i in range(count))
with wave.open(str(out), "w") as handle:
    handle.setnchannels(1)
    handle.setsampwidth(2)
    handle.setframerate(rate)
    handle.writeframes(frames)
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def call(tool: str, args: dict, session: str = "s", task: str = "t", hook: bool = True):
    directive = None
    if hook:
        directive = PLUGIN.tools.on_pre_tool_call(tool, args, session_id=session, task_id=task)
    body = json.loads(PLUGIN.tools.HANDLERS[tool](args, session_id=session, task_id=task))
    return directive, body


def fingerprint(directory: Path) -> list[tuple]:
    rows = []
    for path in sorted(directory.rglob("*")):
        info = path.lstat()
        rows.append((str(path.relative_to(directory)), info.st_mode, info.st_size, info.st_mtime_ns, info.st_ino))
    return rows
