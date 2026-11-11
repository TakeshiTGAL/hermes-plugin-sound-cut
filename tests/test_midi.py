"""MIDI track and note counts. A set_tempo event is not an estimate."""

from __future__ import annotations

import os

import mido

from helpers import PLUGIN, ROOT, tone, write_wav

midi_read = PLUGIN.midi_read


def _midi(path, tempos=(100,), notes=((60, 64), (62, 0))):
    mid = mido.MidiFile()
    lead = mido.MidiTrack()
    drums = mido.MidiTrack()
    mid.tracks.extend([lead, drums])
    lead.append(mido.MetaMessage("track_name", name="Lead", time=0))
    for bpm in tempos:
        lead.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm), time=0))
    for note, velocity in notes:
        lead.append(mido.Message("note_on", note=note, velocity=velocity, time=0))
        if velocity:
            lead.append(mido.Message("note_off", note=note, velocity=0, time=100))
    drums.append(mido.MetaMessage("track_name", name="Drums", time=0))
    drums.append(mido.Message("note_on", note=36, velocity=80, time=0))
    mid.save(str(path))
    return path


def test_tracks_notes_and_file_tempo_are_separate(root):
    path = _midi(root / "line.mid")
    body = midi_read.read_midi({"input_path": str(path)})
    assert body["ok"] is True
    assert body["wrote"] is False
    assert body["track_count"] == 2
    assert body["note_count"] == 2
    assert body["tracks"][0]["name"] == "Lead"
    assert body["tracks"][0]["note_count"] == 1
    assert body["tracks"][1]["name"] == "Drums"
    assert body["set_tempo_bpm"] == [100.0]
    assert "not an estimate" in body["set_tempo_source"]
    assert body["tempo_bpm_estimated"] is None
    assert body["tempo_kind"] == "estimated"
    assert "tempo" not in body
    assert "bpm" not in body
    assert mido.tempo2bpm(500000) == 120.0


def test_audio_file_is_not_counted_as_midi(root):
    path = write_wav(root / "tone.wav", tone(44100, 0.2))
    body = midi_read.read_midi({"input_path": str(path)})
    assert body["code"] == "bad_format"
    assert "sound_cut_inspect" in body["next"]


def test_midi_file_is_not_decoded_as_audio(root):
    path = _midi(root / "line.mid")
    body = PLUGIN.audio.inspect_file({"input_path": str(path)})
    assert body["code"] == "bad_format"


def test_empty_garbage_unknown_and_too_large(root, monkeypatch):
    empty = root / "empty.mid"
    empty.write_bytes(b"")
    assert midi_read.read_midi({"input_path": str(empty)})["code"] == "empty_input"
    garbage = root / "nope.mid"
    garbage.write_bytes(b"not midi")
    assert midi_read.read_midi({"input_path": str(garbage)})["code"] == "midi_unreadable"
    path = _midi(root / "line.mid")
    assert midi_read.read_midi({"input_path": str(path), "play": True})["code"] == "bad_argument"
    monkeypatch.setattr(midi_read, "MAX_BYTES", 8)
    assert midi_read.read_midi({"input_path": str(path)})["code"] == "too_large"


def test_sixty_five_tracks_list_the_first_64(root):
    mid = mido.MidiFile()
    for index in range(65):
        track = mido.MidiTrack()
        track.append(mido.MetaMessage("track_name", name=f"t{index}", time=0))
        if index == 64:
            track.append(mido.Message("note_on", note=60, velocity=40, time=0))
        mid.tracks.append(track)
    path = root / "wide.mid"
    mid.save(str(path))
    body = midi_read.read_midi({"input_path": str(path)})
    assert body["ok"] is True
    assert body["track_count"] == 65
    assert body["tracks_listed"] == 64
    assert body["note_count"] == 1
    assert len(body["tracks"]) == 64
    assert body["tracks"][-1]["name"] == "t63"
    assert body["tracks_note"] == "tracks lists the first 64. track_count counted every track."
    skill = (ROOT / "skills" / "sound-cut" / "SKILL.md").read_text(encoding="utf-8")
    assert "each track name" not in skill
    assert "first 64" in skill


def test_symlink_midi_is_not_followed(root):
    path = _midi(root / "line.mid")
    link = root / "link.mid"
    link.symlink_to(path)
    body = midi_read.read_midi({"input_path": str(link)})
    assert body["code"] == "symlink"
    assert os.path.realpath("/tmp") in body["next"]
    assert path.stat().st_size > 0


def test_midi_hook_does_not_approve(root):
    path = _midi(root / "line.mid")
    directive = PLUGIN.tools.on_pre_tool_call(
        "sound_cut_midi", {"input_path": str(path)}, session_id="s", task_id="t"
    )
    assert directive is None
