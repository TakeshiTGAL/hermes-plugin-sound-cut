# Sound Cut

Sound Cut prepares a game sound effect on this computer before that file goes into a game.

- Measure a wav, mp3, or flac. The reply has duration_seconds, peak_dbfs, and tempo_bpm_estimated. tempo_kind is estimated.
- Read a MIDI file. The reply has track_count and note_count. A set_tempo value is the event stored in the file. tempo_bpm_estimated stays null.
- Trim silence, cut one span, convert among wav, mp3, flac, and ogg, or write a loop seam. The new file is created only after one approval, and only inside the directory you name.

ffmpeg is the program already on PATH. This plugin does not install ffmpeg and does not download a model. Reading length, peak, tempo, and MIDI does not start ffmpeg. The four write tools register pre_tool_call and start ffmpeg only after that hook approves. The approval line is the full command. An existing file is not overwritten. The new file stays inside the directory you name. A path component that is a symlink is refused and is not followed. On macOS, /tmp and /var are symlinks, so pass the regular path named in the next field.

Tempo is always an estimate from the energy envelope. A null estimate means no periodic pulse was found. A MIDI set_tempo value is the event stored in the file, and tempo_bpm_estimated stays null for MIDI.

Sound Cut stores no API key. It does not call ElevenLabs. Audio stays on this computer.

Yolo and approvals off skip the prompt. This plugin still refuses cron, `hermes -q`, webhook, msgraph_webhook, api_server, and the plugin host, even after always. With `plugins.isolation` set to host, the plugin loads and runs in the plugin host. Read tools still measure the file. Write tools stop before ffmpeg starts. Choosing always stores one `plugin_rule:<tool>:<16 hex>` line in config.yaml for that same argument set, and that line stays after the plugin is removed.

Requires Hermes 0.21.6 or later. Checked on the v0.22.2 tree. macOS with ffmpeg 8.1 was exercised. Linux and Windows were not.

## Install and first call

From this repository, with `hermes` on PATH. A non-interactive shell needs `--yes-deps`. Without that flag the install exits 0 and leaves the plugin disabled. `python3` on PATH only writes the wav with the standard library.

```
export HERMES_HOME="${TMPDIR:-/tmp}/sound-cut-home"
export HOME="${TMPDIR:-/tmp}/sound-cut-user"
mkdir -p "$HERMES_HOME" "$HOME"
hermes plugins install --yes-deps "file://${PWD}" </dev/null
hermes plugins enable sound-cut </dev/null
python3 - <<'PY'
import math, struct, wave
from pathlib import Path
wav = Path.cwd() / "sound-cut-check.wav"
rate = 44100
tone = b"".join(struct.pack("<h", int(12000 * math.sin(2 * math.pi * 440 * i / rate))) for i in range(rate // 2))
silence = b"\x00\x00" * (rate // 4)
with wave.open(str(wav), "w") as handle:
    handle.setnchannels(1)
    handle.setsampwidth(2)
    handle.setframerate(rate)
    handle.writeframes(silence + tone + silence)
print(wav)
PY
hermes sound-cut call sound_cut_inspect --json "{\"input_path\":\"${PWD}/sound-cut-check.wav\"}" </dev/null
```

The same steps when `HERMES_HOME` is unset, so Hermes uses `$HOME/.hermes`:

```
mkdir -p "${TMPDIR:-/tmp}/sound-cut-user-2"
env -u HERMES_HOME HOME="${TMPDIR:-/tmp}/sound-cut-user-2" hermes plugins install --yes-deps "file://${PWD}" </dev/null
env -u HERMES_HOME HOME="${TMPDIR:-/tmp}/sound-cut-user-2" hermes plugins enable sound-cut </dev/null
python3 - <<'PY'
import math, struct, wave
from pathlib import Path
wav = Path.cwd() / "sound-cut-check.wav"
rate = 44100
tone = b"".join(struct.pack("<h", int(12000 * math.sin(2 * math.pi * 440 * i / rate))) for i in range(rate // 2))
silence = b"\x00\x00" * (rate // 4)
with wave.open(str(wav), "w") as handle:
    handle.setnchannels(1)
    handle.setsampwidth(2)
    handle.setframerate(rate)
    handle.writeframes(silence + tone + silence)
print(wav)
PY
env -u HERMES_HOME HOME="${TMPDIR:-/tmp}/sound-cut-user-2" hermes sound-cut call sound_cut_inspect --json "{\"input_path\":\"${PWD}/sound-cut-check.wav\"}" </dev/null
```

`tempo_bpm_estimated` is null or a number, and `tempo_kind` is `estimated`. The wav stays in this repository directory. On macOS, pass that absolute path. A path under `/tmp` or `/var` has a symlink component.

`hermes sound-cut call` prints one JSON object. It does not open the `hermes` program file. A write tool on that command returns `approval_denied` and does not start ffmpeg. A trim writes only after the approval hook has run in an attended chat, and only inside `output_dir`.

## Tools

| Tool | What it does |
| --- | --- |
| `sound_cut_inspect` | Length, peak, estimated tempo. No ffmpeg. |
| `sound_cut_midi` | Track count and note count. No playback. |
| `sound_cut_trim` | Cut leading and trailing silence. |
| `sound_cut_slice` | Write one time span. |
| `sound_cut_convert` | wav, mp3, flac, or ogg. |
| `sound_cut_loop` | Crossfade the end into the start. |

Before approval, the message shows the input path, the output path, and the full ffmpeg command. The card's command field is the tool name. The message is what will run.

## Details

`pre_tool_call` is the hook this plugin registers. It approves the four write tools. Read tools and every other tool receive no directive from this hook. `hermes sound-cut call` does not send that hook. A write from the command has no saved approval, returns `approval_denied`, and leaves ffmpeg unstarted.

ffmpeg is stopped after 30 seconds. The child process is that ffmpeg binary. It is not a sandbox for hostile code. The child receives only HOME, PATH, TMPDIR, LANG, and LC_ALL when those variables are set. Proxy variables are not copied.

When the output directory is not writable, the code is not_writable. A read-only filesystem returns read_only. A full filesystem returns no_space. ffmpeg is not started. A path that cannot be read returns not_readable.

After `hermes plugins remove`, `plugins/sound-cut` is gone. The directory `installs/.../plugin-deps/sound-cut-<hash>` remains. On the check machine, `du -sk` of that `plugin-deps` directory was 4. After `hermes tools disable --platform` saves tool settings, `known_plugin_toolsets` keeps the name `sound-cut`. An always `plugin_rule` line in config.yaml also remains.

The installed plugin directory, including `.git`, is 460 kilobytes by `du -sk`.

ogg export needs an ffmpeg build that includes libvorbis. Without that encoder the tool returns `encoder_missing` and leaves no new file.
