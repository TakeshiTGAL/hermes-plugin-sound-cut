"""Build one ffmpeg argument list. The approval line and the child use this list."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from pathlib import Path

from . import audio, paths
from .audio import failure

OUTPUT_EXTENSIONS = frozenset({".wav", ".mp3", ".flac", ".ogg"})
INPUT_EXTENSIONS = frozenset({".wav", ".mp3", ".flac", ".ogg", ".opus"})
_KINDS = frozenset({"trim", "slice", "convert", "loop"})
_TIMEOUT = 30
_CODEC = {
    "wav": ["-c:a", "pcm_s16le"],
    "mp3": ["-c:a", "libmp3lame", "-q:a", "4"],
    "flac": ["-c:a", "flac"],
    "ogg": ["-c:a", "libvorbis", "-q:a", "5"],
}
_KEEP = frozenset({"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL"})


def child_env() -> dict[str, str]:
    """HOME, PATH, TMPDIR, LANG, and LC_ALL only. Proxy variables are not copied."""
    return {key: os.environ[key] for key in _KEEP if os.environ.get(key)}


def find_ffmpeg() -> str | None:
    found = shutil.which("ffmpeg")
    if not found or not os.path.isfile(found):
        return None
    return os.path.abspath(found)


def _number(value: object, field: str, low: float, high: float) -> float | dict:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return failure(
            "bad_argument",
            f"{field} must be a number from {low} to {high}.",
            f"Pass {field} as a number. Nothing was written.",
            field=field,
        )
    number = float(value)
    if number < low or number > high or number != number:
        return failure(
            "bad_argument",
            f"{field} must be from {low} to {high}.",
            f"Pass {field} inside that range. Nothing was written.",
            field=field,
        )
    return number


def _seconds(value: float) -> str:
    text = f"{value:.3f}"
    if not re.fullmatch(r"\d+\.\d{3}", text):
        raise ValueError(text)
    return text


def _db(value: float) -> str:
    text = f"{value:.1f}"
    if not re.fullmatch(r"-\d+\.\d", text):
        raise ValueError(text)
    return text + "dB"


def _default_name(kind: str, source: str, extension: str) -> str:
    stem = Path(source).stem or "sound"
    stem = re.sub(r"[^A-Za-z0-9._-]", "-", stem)[:40] or "sound"
    suffix = {"trim": "trim", "slice": "slice", "convert": "converted", "loop": "loop"}[kind]
    return f"{stem}-{suffix}.{extension}"


def build(kind: str, args: object) -> dict:
    """Return a plan dict, or an error dict with ok False."""
    if kind not in _KINDS:
        return failure("bad_argument", "Unknown write.", "Use trim, slice, convert, or loop.")
    if not isinstance(args, dict):
        return failure("bad_argument", "Arguments must be an object.", "Pass input_path and output_dir.")
    allowed = {"input_path", "output_dir", "output_name", "format"}
    if kind == "trim":
        allowed |= {"silence_threshold_db", "keep_silence_seconds"}
    elif kind == "slice":
        allowed |= {"start_seconds", "end_seconds"}
    elif kind == "loop":
        allowed |= {"crossfade_ms"}
    unknown = sorted(set(args) - allowed)
    if unknown:
        return failure(
            "bad_argument",
            "Unknown argument: " + ", ".join(unknown) + ".",
            "Drop the unknown argument. Nothing was written.",
        )
    raw_input = args.get("input_path")
    raw_dir = args.get("output_dir")
    if not isinstance(raw_input, str) or not raw_input:
        return failure("bad_argument", "input_path must be a string.", "Pass an absolute input_path.")
    if not isinstance(raw_dir, str) or not raw_dir:
        return failure("bad_argument", "output_dir must be a string.", "Pass an absolute output_dir.")
    try:
        source, info = paths.real_file(raw_input)
        directory = paths.real_directory(raw_dir)
    except paths.PathRefused as exc:
        return _path_error(exc, "input_path" if exc.detail == raw_input else "output_dir")
    in_suffix = Path(source).suffix.lower()
    if in_suffix not in INPUT_EXTENSIONS:
        return failure(
            "bad_format",
            f"{in_suffix or 'that file'} is not an input this tool accepts.",
            "Pass wav, mp3, flac, ogg, or opus. Nothing was written.",
        )
    if info.st_size == 0:
        return failure("empty_input", "The input is 0 bytes.", "Pass a sound file. Nothing was written.")
    if info.st_size > audio.MAX_BYTES:
        return failure(
            "too_large",
            f"The input is {info.st_size} bytes, over the {audio.MAX_BYTES} byte cap.",
            "Pass a shorter sound effect. Nothing was written.",
        )
    fmt = args.get("format", in_suffix[1:] if in_suffix in OUTPUT_EXTENSIONS else "wav")
    if not isinstance(fmt, str) or fmt.lower() not in _CODEC:
        return failure(
            "bad_format",
            "format must be wav, mp3, flac, or ogg.",
            "Pass one of those formats. Nothing was written.",
            field="format",
        )
    fmt = fmt.lower()
    name = args.get("output_name")
    if name is None:
        name = _default_name(kind, source, fmt)
    if not isinstance(name, str):
        return failure("bad_argument", "output_name must be a string.", "Pass one file name.", field="output_name")
    try:
        name, got = paths.output_name_parts(name, OUTPUT_EXTENSIONS)
    except paths.PathRefused as exc:
        if exc.kind == "bad_format":
            return failure(
                "bad_format",
                "output_name must end in .wav, .mp3, .flac, or .ogg.",
                "Change the extension. Nothing was written.",
                field="output_name",
            )
        return failure(
            "bad_argument",
            "output_name must be one file name, without a slash or a leading dot.",
            "Pass a single file name inside output_dir.",
            field="output_name",
        )
    if got != fmt:
        return failure(
            "bad_format",
            "output_name's extension and format disagree.",
            "Make the extension match format. Nothing was written.",
            field="output_name",
        )
    try:
        state = paths.output_state(directory, name)
    except paths.PathRefused as exc:
        if exc.kind != "missing":
            return _path_error(exc, "output_name")
        state = "absent"
    if state != "absent":
        suggestion = paths.suggest_name(directory, name)
        nxt = (
            f"Pass output_name {suggestion}. Nothing was written."
            if suggestion
            else "Pick another output_name. Nothing was written."
        )
        return failure(
            "exists",
            f"{name} already exists in the output directory, so it was not overwritten.",
            nxt,
            suggested_name=suggestion,
        )
    binary = find_ffmpeg()
    if not binary:
        return failure(
            "ffmpeg_missing",
            "ffmpeg was not found on PATH.",
            "Install ffmpeg and call again. Nothing was written.",
        )
    try:
        extra, duration = _filters(kind, args, source)
    except ValueError:
        return failure("bad_argument", "A filter number was refused.", "Pass a plain number. Nothing was written.")
    if isinstance(extra, dict):
        return extra
    argv = [binary, "-hide_banner", "-nostdin", "-y", "-i", source, "-vn", *extra, *(_CODEC[fmt]), str(Path(directory) / name)]
    if any("\n" in part or "`" in part for part in argv):
        return failure(
            "bad_argument",
            "The command would contain a newline or a backtick.",
            "Use a plain path. Nothing was written.",
        )
    import shlex

    output = str(Path(directory) / name)
    line = (
        f"{_tool(kind)} writes {output} from {source}. "
        "The output does not exist and will be created. "
        "An existing file is not overwritten. "
        "Command: " + shlex.join(argv)
    )
    try:
        source_hash = paths.file_sha256(source)
    except paths.PathRefused as exc:
        return _path_error(exc, "input_path")
    fingerprint = hashlib.sha256(
        (source_hash + "\n" + state + "\n" + "\n".join(argv)).encode("utf-8")
    ).hexdigest()
    return {
        "ok": True,
        "kind": kind,
        "argv": argv,
        "line": line,
        "fingerprint": fingerprint,
        "output": output,
        "source": source,
        "directory": directory,
        "name": name,
        "duration_seconds": duration,
        "timeout": _TIMEOUT,
    }


def _tool(kind: str) -> str:
    return "sound_cut_" + kind


def _filters(kind: str, args: dict, source: str) -> tuple[list[str] | dict, float | None]:
    if kind == "convert":
        return ["-map", "0:a:0"], None
    if kind == "trim":
        threshold = args.get("silence_threshold_db", -50.0)
        keep = args.get("keep_silence_seconds", 0.0)
        parsed_t = _number(threshold, "silence_threshold_db", -80.0, -20.0)
        parsed_k = _number(keep, "keep_silence_seconds", 0.0, 0.2)
        if isinstance(parsed_t, dict):
            return parsed_t, None
        if isinstance(parsed_k, dict):
            return parsed_k, None
        db = _db(parsed_t)
        keep_s = _seconds(parsed_k)
        filt = (
            f"silenceremove=start_periods=1:start_silence={keep_s}:start_threshold={db}:detection=peak,"
            f"areverse,silenceremove=start_periods=1:start_silence={keep_s}:start_threshold={db}:detection=peak,areverse"
        )
        return ["-map", "0:a:0", "-af", filt], None
    if kind == "slice":
        if "start_seconds" not in args or "end_seconds" not in args:
            return failure(
                "bad_argument",
                "start_seconds and end_seconds are required.",
                "Pass both. Nothing was written.",
            ), None
        start = _number(args["start_seconds"], "start_seconds", 0.0, 600.0)
        end = _number(args["end_seconds"], "end_seconds", 0.0, 600.0)
        if isinstance(start, dict):
            return start, None
        if isinstance(end, dict):
            return end, None
        if end <= start or (end - start) < 0.001:
            return failure(
                "bad_argument",
                "end_seconds must be greater than start_seconds.",
                "Pass a longer span. Nothing was written.",
                field="end_seconds",
            ), None
        bound = _bound(source, end)
        if isinstance(bound, dict):
            return bound, None
        filt = f"atrim=start={_seconds(start)}:end={_seconds(end)},asetpts=PTS-STARTPTS"
        return ["-map", "0:a:0", "-af", filt], None
    cross = _number(args.get("crossfade_ms", 30), "crossfade_ms", 5, 500)
    if isinstance(cross, dict):
        return cross, None
    seconds = audio.duration_seconds(source)
    if isinstance(seconds, dict):
        seconds["next"] = (
            "sound_cut_convert can write a wav after approval, then sound_cut_loop can read that duration. "
            "ffmpeg was not started."
        )
        return seconds, None
    fade = float(cross) / 1000.0
    if seconds <= fade * 2:
        return failure(
            "bad_argument",
            f"The sound is {seconds:.3f} seconds, too short for a {fade:.3f} second crossfade.",
            "Use a shorter crossfade_ms or a longer file. Nothing was written.",
            field="crossfade_ms",
        ), None
    fade_s = _seconds(fade)
    graph = (
        f"[0:a]asplit=2[a][b];"
        f"[a]atrim=start=0:end={fade_s},asetpts=PTS-STARTPTS[head];"
        f"[b]atrim=start={fade_s},asetpts=PTS-STARTPTS[rest];"
        f"[rest][head]acrossfade=d={fade_s}:c1=tri:c2=tri[out]"
    )
    return ["-filter_complex", graph, "-map", "[out]"], seconds


def _bound(source: str, end: float) -> dict | None:
    measured = audio.duration_seconds(source)
    if isinstance(measured, dict):
        if measured.get("code") == "decode_unsupported":
            return None
        return measured
    if end > measured + 0.02:
        return failure(
            "bad_argument",
            f"end_seconds is past the file, which is {measured:.3f} seconds.",
            "Pass an end_seconds inside the file. Nothing was written.",
            field="end_seconds",
            duration_seconds=round(measured, 6),
        )
    return None


def _path_error(exc: paths.PathRefused, field: str) -> dict:
    code, error, nxt = paths.refusal_text(exc, surface="write", field=field)
    reported = "output_dir" if code == "not_a_directory" else field
    return failure(code, error, nxt, field=reported)
