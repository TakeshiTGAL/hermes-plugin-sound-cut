"""Tool schemas. The first sentence of each description stays within 60 characters."""

_INPUT = {
    "type": "string",
    "description": "Absolute path of a regular file. A symlink or a .. component is refused.",
}
_DIR = {
    "type": "string",
    "description": "Absolute directory the new file is written inside. The directory must already exist.",
}
_NAME = {
    "type": "string",
    "description": "One file name inside output_dir. An existing name is refused.",
}
_FORMAT = {
    "type": "string",
    "description": "wav, mp3, flac, or ogg. The output_name extension must match.",
}

INSPECT = {
    "name": "sound_cut_inspect",
    "description": (
        "Measure length, peak, and estimated tempo of a sound effect. "
        "Reads wav, mp3, or flac in-process and returns duration_seconds, peak_dbfs, and tempo_bpm_estimated. "
        "Does not start ffmpeg and does not write a file."
    ),
    "annotations": {"readOnlyHint": True},
    "parameters": {
        "type": "object",
        "properties": {"input_path": _INPUT},
        "required": ["input_path"],
    },
}

MIDI = {
    "name": "sound_cut_midi",
    "description": (
        "Read MIDI track names and note counts without playing. "
        "Returns track_count and note_count. The tracks array holds the first 64 names. "
        "A set_tempo event is the value stored in the file. "
        "tempo_bpm_estimated stays null because a MIDI file is not audio."
    ),
    "annotations": {"readOnlyHint": True},
    "parameters": {
        "type": "object",
        "properties": {"input_path": _INPUT},
        "required": ["input_path"],
    },
}

TRIM = {
    "name": "sound_cut_trim",
    "description": (
        "Trim leading and trailing silence from a sound effect. "
        "Writes a new file with the ffmpeg on PATH after one approval. "
        "Does not overwrite an existing file."
    ),
    "annotations": {"readOnlyHint": False},
    "parameters": {
        "type": "object",
        "properties": {
            "input_path": _INPUT,
            "output_dir": _DIR,
            "output_name": _NAME,
            "format": _FORMAT,
            "silence_threshold_db": {
                "type": "number",
                "description": "Silence threshold in dB from -80 to -20. Default -50.",
            },
            "keep_silence_seconds": {
                "type": "number",
                "description": "Silence to leave at each edge, from 0 to 0.2 seconds. Default 0.",
            },
        },
        "required": ["input_path", "output_dir"],
    },
}

SLICE = {
    "name": "sound_cut_slice",
    "description": (
        "Cut one time span out of a sound effect. "
        "Writes that span with ffmpeg after one approval. "
        "Does not overwrite an existing file."
    ),
    "annotations": {"readOnlyHint": False},
    "parameters": {
        "type": "object",
        "properties": {
            "input_path": _INPUT,
            "output_dir": _DIR,
            "output_name": _NAME,
            "format": _FORMAT,
            "start_seconds": {"type": "number", "description": "Start of the span, from 0 to 600 seconds."},
            "end_seconds": {"type": "number", "description": "End of the span, after start_seconds and at most 600."},
        },
        "required": ["input_path", "output_dir", "start_seconds", "end_seconds"],
    },
}

CONVERT = {
    "name": "sound_cut_convert",
    "description": (
        "Convert a sound effect to wav, mp3, flac, or ogg. "
        "Writes the new file with ffmpeg after one approval. "
        "Does not overwrite an existing file."
    ),
    "annotations": {"readOnlyHint": False},
    "parameters": {
        "type": "object",
        "properties": {
            "input_path": _INPUT,
            "output_dir": _DIR,
            "output_name": _NAME,
            "format": _FORMAT,
        },
        "required": ["input_path", "output_dir"],
    },
}

LOOP = {
    "name": "sound_cut_loop",
    "description": (
        "Crossfade a sound effect so the loop seam is smoother. "
        "Writes a new file with ffmpeg after one approval. "
        "The result is shorter by the crossfade."
    ),
    "annotations": {"readOnlyHint": False},
    "parameters": {
        "type": "object",
        "properties": {
            "input_path": _INPUT,
            "output_dir": _DIR,
            "output_name": _NAME,
            "format": _FORMAT,
            "crossfade_ms": {
                "type": "integer",
                "description": "Crossfade length in milliseconds, from 5 to 500. Default 30.",
            },
        },
        "required": ["input_path", "output_dir"],
    },
}

ALL_SCHEMAS = [INSPECT, MIDI, TRIM, SLICE, CONVERT, LOOP]
