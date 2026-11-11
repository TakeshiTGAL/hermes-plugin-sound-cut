"""MIDI track names and note counts through mido. Nothing is played."""

from __future__ import annotations

from . import paths
from .audio import failure

MAX_BYTES = 8 * 1024 * 1024
_EXTENSIONS = frozenset({".mid", ".midi"})


def read_midi(args: object) -> dict:
    if not isinstance(args, dict):
        return failure("bad_argument", "Arguments must be an object.", "Pass input_path.")
    unknown = sorted(set(args) - {"input_path"})
    if unknown:
        return failure(
            "bad_argument",
            "Unknown argument: " + ", ".join(unknown) + ".",
            "Pass only input_path.",
        )
    raw = args.get("input_path")
    if not isinstance(raw, str) or not raw:
        return failure("bad_argument", "input_path must be a string.", "Pass input_path as an absolute path.")
    try:
        path, info = paths.real_file(raw)
    except paths.PathRefused as exc:
        return _path_error(exc)
    suffix = "." + path.rsplit(".", 1)[-1].lower() if "." in path.rsplit("/", 1)[-1] else ""
    if suffix not in _EXTENSIONS:
        return failure(
            "bad_format",
            "sound_cut_midi reads a .mid or .midi file.",
            "Pass a MIDI file. An audio file belongs on sound_cut_inspect.",
        )
    if info.st_size > MAX_BYTES:
        return failure(
            "too_large",
            f"The MIDI file is {info.st_size} bytes, over the {MAX_BYTES} byte cap.",
            "Pass a smaller MIDI file. Track counts were not computed.",
        )
    if info.st_size == 0:
        return failure(
            "empty_input",
            "The MIDI file is 0 bytes.",
            "Pass a MIDI file with tracks. Nothing was counted.",
        )
    try:
        paths.assert_readable(path)
    except paths.PathRefused as exc:
        return _path_error(exc)
    try:
        import mido
    except Exception as exc:
        return failure(
            "decoder_missing",
            "mido is not installed, so the MIDI file was not read.",
            "Install the plugin dependencies and call again.",
            detail=type(exc).__name__,
        )
    try:
        mid = mido.MidiFile(path)
    except Exception as exc:
        return failure(
            "midi_unreadable",
            "The file is not a MIDI file mido could parse.",
            "Pass a standard MIDI file. Nothing was counted.",
            detail=type(exc).__name__,
        )
    tracks = []
    note_count = 0
    tempos: list[float] = []
    for index, track in enumerate(mid.tracks):
        name = ""
        notes = 0
        for message in track:
            if message.type == "track_name" and not name and isinstance(message.name, str):
                name = message.name
            elif message.type == "note_on" and int(message.velocity) > 0:
                notes += 1
            elif message.type == "set_tempo":
                tempos.append(round(float(mido.tempo2bpm(message.tempo)), 3))
        note_count += notes
        tracks.append({"index": index, "name": name, "note_count": notes})
    listed = tracks[:64]
    tempo_list = tempos[:32]
    body = {
        "ok": True,
        "isError": False,
        "wrote": False,
        "path": path,
        "track_count": len(tracks),
        "note_count": note_count,
        "tracks": listed,
        "tracks_listed": len(listed),
        "set_tempo_bpm": tempo_list if tempo_list else None,
        "set_tempo_count": len(tempos),
        "set_tempo_source": (
            "midi set_tempo events stored in the file, not an estimate"
            if tempos
            else "the file has no set_tempo event"
        ),
        "tempo_bpm_estimated": None,
        "tempo_kind": "estimated",
        "tempo_reason": (
            "MIDI has no audio samples. set_tempo_bpm is the file event. No tempo was estimated."
        ),
    }
    if len(tracks) > 64:
        body["tracks_note"] = "tracks lists the first 64. track_count counted every track."
    if len(tempos) > 32:
        body["set_tempo_note"] = "set_tempo_bpm lists the first 32. set_tempo_count counted every event."
    return body


def _path_error(exc: paths.PathRefused) -> dict:
    code, error, nxt = paths.refusal_text(exc, surface="midi")
    return failure(code, error, nxt)
