---
name: sound-cut
description: Trim silence, cut a span, convert, or loop a game sound effect. Measure length, peak, and estimated tempo, or MIDI tracks and notes.
---

Before approval, write the input path, the output path, that no existing file is overwritten, and the full ffmpeg command.

Search with one of these: "trim silence from a sound effect", "estimated tempo and peak of a wav", "midi track note count".

## Inspect

sound_cut_inspect reads a wav, mp3, or flac file on this computer. It returns duration_seconds, peak_dbfs, and tempo_bpm_estimated. The tempo is always an estimate from the energy envelope. A null estimate means no periodic pulse was found. It does not start ffmpeg and does not write a file. Opus needs sound_cut_convert to a wav first.

sound_cut_midi reads a MIDI file. It returns track_count and note_count. The tracks array holds the first 64 rows. track_count counts every track. When the file has more than 64 tracks, tracks_note says the list is the first 64. A set_tempo value is the event stored in the file. It is not an estimate. tempo_bpm_estimated stays null for MIDI.

## Write

sound_cut_trim, sound_cut_slice, sound_cut_convert, and sound_cut_loop start the ffmpeg binary on PATH. Each one asks with pre_tool_call. The output is a new file inside output_dir. If that name exists, the tool writes nothing and returns a free name to pass as output_name.

Pass absolute paths with no symlink and no .. component. On macOS, /tmp and /var are symlinks. Pass the regular path named in the next field. format is wav, mp3, flac, or ogg. ogg needs an ffmpeg that has libvorbis. ffmpeg is stopped after 30 seconds. The child receives HOME, PATH, TMPDIR, LANG, and LC_ALL. It is not a sandbox for hostile code.

## When it fails

- ffmpeg_missing: Install ffmpeg and call again. Nothing was written.
- encoder_missing: Install that codec or pass format wav. Nothing was kept.
- exists: Pass the suggested output_name. Nothing was written.
- symlink: On macOS, /tmp and /var are symlinks. Pass the regular path named in the next field. It was not followed.
- outside: Pass an absolute path with no . or .. component. A relative path stays outside, including when the working directory is the Hermes home.
- not_writable: The output directory cannot be written. Choose one you can write, or change its permissions. Nothing was written.
- not_readable: The file cannot be read. Choose a file you can read. Nothing was measured.
- read_only: The filesystem is read-only. Choose another directory. Nothing was written.
- no_space: The filesystem has no space left. Free some space or choose another directory. Nothing was written.
- decode_unsupported: Convert to wav with sound_cut_convert, then inspect that wav.
- approval_blocked: Cron, hermes -q, webhook, msgraph_webhook, api_server, and the plugin host write nothing, even after always. With plugins.isolation set to host, the plugin still loads. Read tools measure. Write tools stop.
- approval_denied: The write was not approved. Nothing was written.
- approval_not_sent: The approval line would not fit, so it was not sent.
- timed_out: The run was cut off. Nothing was kept.
- empty_output: The result had no samples. Nothing was kept.
- bad_argument: Fix the named field. Nothing was written.
