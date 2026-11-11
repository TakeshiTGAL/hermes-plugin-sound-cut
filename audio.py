"""In-process length, peak, and an estimated tempo.

ffmpeg is not started. WAV, MP3, and FLAC are decoded with miniaudio.
Opus and a file miniaudio cannot open return a next step instead of a guess.
"""

from __future__ import annotations

import math
from array import array

from . import paths

MAX_BYTES = 32 * 1024 * 1024
READ_EXTENSIONS = frozenset({".wav", ".mp3", ".flac", ".ogg", ".opus"})
_HOP_HZ = 100


def failure(code: str, error: str, nxt: str, **extra: object) -> dict:
    body: dict = {
        "ok": False,
        "isError": True,
        "wrote": False,
        "code": code,
        "error_type": code,
        "error": error,
        "next": nxt,
    }
    body.update(extra)
    return body


def _one_string(args: dict, field: str) -> str | dict:
    if field not in args:
        return failure("bad_argument", f"{field} is required.", f"Pass {field} as an absolute path.")
    value = args[field]
    if not isinstance(value, str) or not value:
        return failure("bad_argument", f"{field} must be a string.", f"Pass {field} as an absolute path.")
    return value


def inspect_args(args: object) -> dict:
    if not isinstance(args, dict):
        return failure("bad_argument", "Arguments must be an object.", "Pass input_path.")
    unknown = sorted(set(args) - {"input_path"})
    if unknown:
        return failure(
            "bad_argument",
            "Unknown argument: " + ", ".join(unknown) + ".",
            "Pass only input_path.",
        )
    raw = _one_string(args, "input_path")
    if isinstance(raw, dict):
        return raw
    try:
        path, info = paths.real_file(raw)
    except paths.PathRefused as exc:
        return _path_error(exc)
    suffix = "." + path.rsplit(".", 1)[-1].lower() if "." in path.rsplit("/", 1)[-1] else ""
    if suffix not in READ_EXTENSIONS:
        return failure(
            "bad_format",
            f"{suffix or 'that file'} is not a sound file this tool reads.",
            "Pass a wav, mp3, flac, ogg, or opus file. Nothing was written.",
            field="input_path",
        )
    if info.st_size > MAX_BYTES:
        return failure(
            "too_large",
            f"The file is {info.st_size} bytes, over the {MAX_BYTES} byte read cap.",
            "Pass a shorter sound effect. Duration and peak were not computed.",
        )
    if info.st_size == 0:
        return failure(
            "empty_input",
            "The file is 0 bytes.",
            "Pass a sound file that has samples. Nothing was measured.",
        )
    try:
        paths.assert_readable(path)
    except paths.PathRefused as exc:
        return _path_error(exc)
    return {"path": path, "size": info.st_size}


def _path_error(exc: paths.PathRefused) -> dict:
    code, error, nxt = paths.refusal_text(exc, surface="read")
    if exc.kind == "bad_path":
        return failure(code, error, nxt, field="input_path")
    return failure(code, error, nxt)


def _decode(path: str) -> dict:
    try:
        paths.assert_readable(path)
    except paths.PathRefused as exc:
        return _path_error(exc)
    try:
        import miniaudio
    except Exception as exc:
        return failure(
            "decoder_missing",
            "miniaudio is not installed, so the file was not decoded.",
            "Install the plugin dependencies and call again. This tool does not start ffmpeg.",
            detail=type(exc).__name__,
        )
    try:
        import numpy as np
    except Exception as exc:
        return failure(
            "decoder_missing",
            "numpy is not installed, so the file was not decoded.",
            "Install the plugin dependencies and call again. This tool does not start ffmpeg.",
            detail=type(exc).__name__,
        )
    try:
        info = miniaudio.get_file_info(path)
        channels = int(info.nchannels or 0)
        sample_rate = int(info.sample_rate or 0)
        if channels < 1 or sample_rate < 1:
            raise miniaudio.DecodeError("missing rate or channels")
        decoded = miniaudio.decode_file(path, nchannels=channels, sample_rate=sample_rate)
    except Exception as exc:
        return failure(
            "decode_unsupported",
            "The file could not be decoded in-process.",
            "sound_cut_convert can write a wav after approval, and sound_cut_inspect can read that wav. ffmpeg was not started.",
            detail=type(exc).__name__,
        )
    samples = decoded.samples
    if not isinstance(samples, array) or len(samples) < 1:
        return failure(
            "empty_input",
            "The decoder returned no samples.",
            "Pass a file that contains audio samples.",
        )
    header_duration = float(getattr(info, "duration", 0.0) or 0.0)
    decoded_frames = len(samples) / channels
    decoded_seconds = decoded_frames / sample_rate
    duration = header_duration if header_duration > 0 else decoded_seconds
    source = "container header" if header_duration > 0 else "decoded samples"
    ints = np.asarray(samples, dtype=np.int32)
    peak = int(np.max(np.abs(ints))) if ints.size else 0
    if peak <= 0:
        peak_dbfs = None
        peak_reason = "every sample is 0"
    else:
        peak_dbfs = round(20.0 * math.log10(peak / 32768.0), 2)
        peak_reason = "maximum absolute sample over full scale"
    mono = ints.astype(np.float64)
    if channels > 1:
        frames = mono.size // channels
        mono = mono[: frames * channels].reshape(frames, channels).mean(axis=1)
    mono = mono / 32768.0
    tempo = estimate_tempo(mono, sample_rate)
    return {
        "ok": True,
        "isError": False,
        "wrote": False,
        "path": path,
        "duration_seconds": round(duration, 6),
        "duration_source": source,
        "decoded_seconds": round(decoded_seconds, 6),
        "sample_rate": sample_rate,
        "channels": channels,
        "peak_sample": peak,
        "peak_dbfs": peak_dbfs,
        "peak_reason": peak_reason,
        **tempo,
    }


def estimate_tempo(samples: np.ndarray, sample_rate: int) -> dict:
    """Energy-envelope autocorrelation. The number is always an estimate."""
    import numpy as np

    base = {
        "tempo_bpm_estimated": None,
        "tempo_kind": "estimated",
        "tempo_method": "energy autocorrelation",
    }
    if sample_rate <= 0 or samples.size == 0:
        return {**base, "tempo_reason": "there are no samples to estimate from"}
    duration = float(samples.size) / float(sample_rate)
    if duration < 1.0:
        return {**base, "tempo_reason": "shorter than 1 second, so no tempo was estimated"}
    hop = max(1, sample_rate // _HOP_HZ)
    count = int(samples.size // hop)
    if count < 20:
        return {**base, "tempo_reason": "too few frames to estimate a tempo"}
    frames = samples[: count * hop].reshape(count, hop)
    energy = np.sqrt(np.mean(frames * frames, axis=1))
    energy = energy - float(np.mean(energy))
    if float(np.max(np.abs(energy))) < 1e-4:
        return {**base, "tempo_reason": "the envelope is flat, so no tempo was estimated"}
    corr = np.correlate(energy, energy, mode="full")
    corr = corr[corr.size // 2 :]
    hop_s = hop / float(sample_rate)
    min_lag = max(1, int(round(60.0 / 200.0 / hop_s)))
    max_lag = min(int(round(60.0 / 50.0 / hop_s)), int(corr.size) - 1)
    if max_lag <= min_lag:
        return {**base, "tempo_reason": "the clip is too short for a 50 to 200 BPM estimate"}
    window = corr[min_lag : max_lag + 1]
    peak_index = int(np.argmax(window))
    peak = float(window[peak_index])
    median = float(np.median(np.abs(window))) + 1e-12
    confidence = peak / median
    if peak <= 0 or confidence < 4.0:
        return {
            **base,
            "tempo_reason": "no clear periodic pulse, so no tempo was estimated",
            "tempo_confidence": round(confidence, 2),
        }
    lag = min_lag + peak_index
    bpm = 60.0 / (lag * hop_s)
    return {
        "tempo_bpm_estimated": round(bpm, 1),
        "tempo_kind": "estimated",
        "tempo_method": "energy autocorrelation",
        "tempo_confidence": round(confidence, 2),
        "tempo_reason": "estimated from the energy envelope; this is not a metronome mark",
    }


def inspect_file(args: object) -> dict:
    parsed = inspect_args(args)
    if parsed.get("ok") is False:
        return parsed
    return _decode(parsed["path"])


def duration_seconds(path: str) -> float | dict:
    """Header duration for a file the decoder can open, else an error dict."""
    body = _decode(path)
    if body.get("ok") is False:
        return body
    return float(body["duration_seconds"])
