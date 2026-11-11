"""One assertion set for each row of the build table."""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path

from helpers import PLUGIN, ROOT

_PUBLIC = {".py", ".md", ".yaml", ".yml", ".json", ".txt", ".toml"}


def _public_files():
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if "tests" in path.parts or "__pycache__" in path.parts or ".git" in path.parts:
            continue
        # A runner may drop a helper beside the plugin. It is not part of the plugin.
        if path.name.startswith("_") and not path.name.startswith("__"):
            continue
        if path.suffix in _PUBLIC or path.name in {"plugin.yaml", "SKILL.md"}:
            yield path


def test_checklist_01_missing_is_not_a_global_zero(root):
    body = PLUGIN.audio.inspect_file({"input_path": str(root / "absent.wav")})
    assert body["ok"] is False
    assert body["code"] == "missing"
    assert "other folders" in body["next"]


def test_checklist_02_a_filename_does_not_decide_the_tempo(root):
    from helpers import tone, write_wav

    path = write_wav(root / "tempo-120-bpm-loop.wav", tone(44100, 2.0))
    body = PLUGIN.audio.inspect_file({"input_path": str(path)})
    assert body["tempo_bpm_estimated"] is None
    assert body["tempo_kind"] == "estimated"


def test_checklist_03_symlink_ancestor_is_refused(root):
    from helpers import tone, write_wav

    real = root / "real"
    real.mkdir()
    link = root / "via"
    link.symlink_to(real, target_is_directory=True)
    wav = write_wav(root / "tone.wav", tone(44100, 0.2))
    body = PLUGIN.plan.build("trim", {"input_path": str(wav), "output_dir": str(link)})
    assert body["ok"] is False
    assert body["code"] == "symlink"
    assert list(real.iterdir()) == []


def test_checklist_04_allowlist_stops_an_unknown_field(root):
    from helpers import tone, write_wav

    wav = write_wav(root / "tone.wav", tone(44100, 0.2))
    out = root / "out"
    out.mkdir()
    body = PLUGIN.plan.build("convert", {
        "input_path": str(wav),
        "output_dir": str(out),
        "format": "aiff",
    })
    assert body["code"] == "bad_format"
    extra = PLUGIN.plan.build("trim", {
        "input_path": str(wav),
        "output_dir": str(out),
        "gain_db": 3,
    })
    assert extra["code"] == "bad_argument"


def test_checklist_05_read_tools_leave_the_directory_unchanged(root):
    from helpers import fingerprint, tone, write_wav

    wav = write_wav(root / "tone.wav", tone(44100, 0.2))
    before = fingerprint(root)
    assert PLUGIN.audio.inspect_file({"input_path": str(wav)})["ok"] is True
    assert fingerprint(root) == before


def test_checklist_06_approval_sentence():
    skill = (ROOT / "skills" / "sound-cut" / "SKILL.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    sentence = (
        "Before approval, write the input path, the output path, "
        "that no existing file is overwritten, and the full ffmpeg command."
    )
    assert sentence in skill
    assert "Before approval" in readme
    assert "full ffmpeg command" in readme
    assert "command field is the tool name" in readme


def test_checklist_07_readme_flow_text():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert 'hermes plugins install --yes-deps "file://${PWD}"' in readme
    assert "hermes plugins enable sound-cut" in readme
    assert "hermes sound-cut call sound_cut_inspect" in readme
    assert "env -u HERMES_HOME" in readme
    assert "sound_cut_inspect" in readme
    assert "sound_cut_follow" not in readme
    assert "sed -n" not in readme
    assert "#!/bin/sh" not in readme
    assert 'exec "' not in readme
    assert "command -v hermes" not in readme
    assert "importlib" not in readme
    assert "approval_denied" in readme
    assert "pre_tool_call" in readme
    assert "regular path named in the next field" in readme
    assert "30 seconds" in readme
    assert "set to host is refused" not in readme
    assert "/tmp/sound-cut-check.wav" not in readme
    assert "--force" not in readme


def test_checklist_08_search_phrases():
    text = " ".join(schema["description"] for schema in PLUGIN.schemas.ALL_SCHEMAS).lower()
    for phrase in (
        "trim silence from a sound effect",
        "estimated tempo and peak of a wav",
        "midi track note count",
    ):
        assert all(word in text for word in phrase.split())


def test_checklist_09_distinct_failures():
    codes = []
    for node in ast.walk(ast.parse((ROOT / "audio.py").read_text(encoding="utf-8"))):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in {
            "bad_argument",
            "missing",
            "symlink",
            "ffmpeg_missing",
            "decode_unsupported",
            "approval_blocked",
            "exists",
            "encoder_missing",
        }:
            codes.append(node.value)
    skill = (ROOT / "skills" / "sound-cut" / "SKILL.md").read_text(encoding="utf-8")
    for code in (
        "ffmpeg_missing",
        "encoder_missing",
        "exists",
        "symlink",
        "outside",
        "decode_unsupported",
        "approval_blocked",
        "approval_denied",
        "approval_not_sent",
        "timed_out",
        "empty_output",
        "bad_argument",
    ):
        assert code in skill
    assert "Pass an absolute path with no . or .. component." in skill
    assert "Keep the output inside output_dir." not in skill


def test_checklist_10_description_lengths():
    skill = (
        "Trim silence, cut a span, convert, or loop a game sound effect. "
        "Measure length, peak, and estimated tempo, or MIDI tracks and notes."
    )
    text = (ROOT / "skills" / "sound-cut" / "SKILL.md").read_text(encoding="utf-8")
    assert f"description: {skill}" in text
    register = (ROOT / "__init__.py").read_text(encoding="utf-8")
    assert "Trim silence, cut a span, convert, or loop a game sound effect." in register
    assert "Measure length, peak, and estimated tempo, or MIDI tracks and notes." in register
    assert len(skill) <= 223
    for schema in PLUGIN.schemas.ALL_SCHEMAS:
        sentence = schema["description"].split(". ")[0]
        if not sentence.endswith("."):
            sentence += "."
        assert len(sentence) <= 60, (schema["name"], len(sentence), sentence)
        assert not sentence.lower().startswith("read-only")
    joined = " ".join(schema["description"] for schema in PLUGIN.schemas.ALL_SCHEMAS).lower()
    for word in ("sound effect", "silence", "tempo", "midi", "loop"):
        assert word in joined


def test_checklist_13_public_text_has_no_japanese_and_no_kit_names():
    japanese = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
    pieces = (
        "APPROVE_" + "PATTERN",
        "BUILD_" + "CHECKLIST",
        "PLAY" + "BOOK",
        "COVERAGE_" + "MATRIX",
        "NOUS_" + "FEEDBACK",
        "AUDITOR_" + "PROMPT",
        "TEKNIUM_" + "STYLE",
        "pre" + "ship_check",
    )
    leaks = re.compile("/" + "Users" + "/|" + "takeshi" + "tgal|" + "shi" + "p/")
    for path in _public_files():
        text = path.read_text(encoding="utf-8")
        assert japanese.search(text) is None, path.name
        for piece in pieces:
            assert piece not in text, (path.name, piece)
        assert leaks.search(text) is None, path.name


def test_checklist_14_sibling_imports_are_relative():
    for path in ROOT.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in {
                "paths",
                "audio",
                "gates",
                "plan",
                "runner",
                "tools",
                "schemas",
                "attendance",
                "midi_read",
                "version",
                "cli",
            }:
                assert node.level == 1, path.name


def test_checklist_16_symlink_next_names_macos_prefixes():
    for name in ("audio.py", "midi_read.py", "plan.py", "runner.py"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "refusal_text" in text, name
    source = (ROOT / "paths.py").read_text(encoding="utf-8")
    assert "symlink_next" in source
    assert 'os.path.realpath("/tmp")' in source
    assert 'os.path.realpath("/var")' in source
    nxt = PLUGIN.paths.symlink_next(wrote=False)
    assert os.path.realpath("/tmp") in nxt
    assert os.path.realpath("/var") in nxt
    assert "Nothing was read through the link." in nxt
    written = PLUGIN.paths.symlink_next(wrote=True)
    assert "Nothing was written." in written


def test_checklist_15_no_network_client_and_no_private_hermes_imports():
    banned = (
        "urlopen(",
        "requests.",
        "tools." + "approval",
        "_" + "yolo" + "_active",
        "cron." + "jobs",
        "cron." + "execution_identity",
        "set" + "profile",
        "set" + "trace",
        "sys._get" + "frame",
        "_run_" + "approval_gate",
        "_dispatch_pre_" + "tool_call_hooks",
    )
    for path in ROOT.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for item in banned:
            assert item not in text, (path.name, item)


def test_schemas_mark_reads_and_writes():
    assert PLUGIN.schemas.INSPECT["annotations"]["readOnlyHint"] is True
    assert PLUGIN.schemas.MIDI["annotations"]["readOnlyHint"] is True
    for schema in (PLUGIN.schemas.TRIM, PLUGIN.schemas.SLICE, PLUGIN.schemas.CONVERT, PLUGIN.schemas.LOOP):
        assert schema["annotations"]["readOnlyHint"] is False


def test_register_binds_the_six_tools():
    seen = []

    class Ctx:
        current_cron_execution = staticmethod(lambda: object())

        def register_tool(self, **kwargs):
            seen.append(kwargs["name"])

        def register_skill(self, name, path, description=""):
            self.skill = (name, description)

        def register_hook(self, hook, fn):
            self.hook = hook

        def register_cli_command(self, **kwargs):
            self.cli = kwargs

    ctx = Ctx()
    PLUGIN.register(ctx)
    assert seen == [schema["name"] for schema in PLUGIN.schemas.ALL_SCHEMAS]
    assert ctx.skill[0] == "sound-cut"
    assert len(ctx.skill[1]) <= 223
    assert ctx.hook == "pre_tool_call"
    assert ctx.cli["name"] == "sound-cut"
    assert ctx.cli["handler_fn"] is PLUGIN.cli.handle
    assert "does not approve" in ctx.cli["description"]
    assert PLUGIN.attendance.unattended_reason() == "a cron job"

    class Missing:
        def register_tool(self, **kwargs):
            return None

        def register_skill(self, name, path, description=""):
            return None

        def register_hook(self, hook, fn):
            return None

        def register_cli_command(self, **kwargs):
            return None

    PLUGIN.register(Missing())
    assert PLUGIN.attendance.unattended_reason() is None

    class Raising(Missing):
        @staticmethod
        def current_cron_execution():
            raise RuntimeError("unreadable")

    PLUGIN.register(Raising())
    assert PLUGIN.attendance.unattended_reason() == "a turn whose cron mark could not be read"
    PLUGIN.attendance.bind_context(None)
