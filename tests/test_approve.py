"""The public pre_tool_call hook and Hermes's dispatcher."""

from __future__ import annotations

import contextvars
import json
import os
import sys
from pathlib import Path

import pytest

from helpers import PLUGIN, call, tone, write_wav

HERMES_SRC = Path(os.environ["HERMES_SRC"]) if os.environ.get("HERMES_SRC") else None


@pytest.fixture
def hermes(tmp_path, monkeypatch):
    home = Path(os.path.realpath(tmp_path / "hermes-home"))
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    for name in (
        "HERMES_INTERACTIVE",
        "HERMES_GATEWAY_SESSION",
        "HERMES_EXEC_ASK",
        "HERMES_YOLO_MODE",
        "HERMES_CRON_SESSION",
        "HERMES_SINGLE_QUERY_SESSION",
        "HERMES_SESSION_PLATFORM",
        "HERMES_PLUGIN_HOST_PROCESS",
    ):
        monkeypatch.delenv(name, raising=False)
    if HERMES_SRC is None or not (HERMES_SRC / "hermes_cli" / "plugins.py").is_file():
        pytest.skip("set HERMES_SRC to a Hermes source tree")
    monkeypatch.syspath_prepend(str(HERMES_SRC))
    sys.modules.pop("hermes_cli.plugins", None)
    try:
        import hermes_cli.plugins as hp
    except Exception as exc:
        pytest.skip("Hermes source could not be imported: " + str(exc))
    mgr = hp.PluginManager(scope_key=str(home))
    mgr._discovered = True
    mgr._hooks["pre_tool_call"] = [PLUGIN.tools.on_pre_tool_call]
    monkeypatch.setattr(hp, "get_plugin_manager", lambda: mgr)
    monkeypatch.setattr(hp, "_plugin_manager", mgr)
    PLUGIN.gates.clear()
    yield hp
    PLUGIN.gates.clear()


def _ready(tmp_path):
    root = Path(os.path.realpath(tmp_path / "job"))
    root.mkdir()
    out = root / "out"
    out.mkdir()
    wav = write_wav(root / "tone.wav", tone(44100, 0.3))
    return {"input_path": str(wav), "output_dir": str(out), "output_name": "cut.wav"}, out / "cut.wav"


def test_rule_key_changes_with_the_arguments(root):
    wav = write_wav(root / "tone.wav", tone(44100, 0.2))
    out = root / "out"
    out.mkdir()
    first = {"input_path": str(wav), "output_dir": str(out), "output_name": "a.wav"}
    second = {"input_path": str(wav), "output_dir": str(out), "output_name": "b.wav"}
    left = PLUGIN.tools.on_pre_tool_call("sound_cut_trim", first, session_id="s", task_id="t")
    right = PLUGIN.tools.on_pre_tool_call("sound_cut_trim", second, session_id="s", task_id="t")
    again = PLUGIN.tools.on_pre_tool_call("sound_cut_trim", dict(first), session_id="s", task_id="t")
    assert left["rule_key"] != right["rule_key"]
    assert left["rule_key"] == again["rule_key"]
    assert len(left["rule_key"].split(":", 1)[1]) == 16


def test_cron_context_and_mark_block_without_the_process_environment(root, monkeypatch):
    monkeypatch.delenv("HERMES_CRON_SESSION", raising=False)
    wav = write_wav(root / "tone.wav", tone(44100, 0.2))
    out = root / "out"
    out.mkdir()
    args = {"input_path": str(wav), "output_dir": str(out)}
    var = contextvars.ContextVar("HERMES_CRON_SESSION", default="")
    token = var.set("1")
    try:
        directive, body = call("sound_cut_trim", args)
        assert directive["action"] == "block"
        assert body["code"] == "approval_blocked"
        assert not (out / "tone-trim.wav").exists()
    finally:
        var.reset(token)
    class Marked:
        current_cron_execution = staticmethod(lambda: object())

    PLUGIN.attendance.bind_context(Marked())
    try:
        reason = PLUGIN.attendance.unattended_reason()
        assert reason == "a cron job"
        directive, body = call("sound_cut_trim", args)
        assert directive["action"] == "block"
        assert body["wrote"] is False
        assert not (out / "tone-trim.wav").exists()
    finally:
        PLUGIN.attendance.bind_context(None)


def test_write_directive_approves_and_a_read_is_silent(hermes, tmp_path):
    args, _output = _ready(tmp_path)
    details = hermes._get_pre_tool_call_directive_details("sound_cut_trim", args)
    assert details.action == "approve"
    assert details.message
    assert "\n" not in details.message
    assert "`" not in details.message
    assert "Command: " in details.message
    assert details.rule_key.startswith("sound_cut_trim:")
    read = hermes._get_pre_tool_call_directive_details("sound_cut_inspect", {"input_path": args["input_path"]})
    assert read.action is None and read.message is None


def test_denied_gate_and_other_plugin_do_not_write(hermes, tmp_path):
    args, output = _ready(tmp_path)
    block_message, _modified = hermes._dispatch_pre_tool_call_hooks("sound_cut_trim", args)
    assert block_message and "BLOCKED" in block_message
    assert not output.exists()

    def veto(**_kwargs):
        return {"action": "block", "message": "other plugin blocked this write"}

    import hermes_cli.plugins as hp

    hp.get_plugin_manager()._hooks["pre_tool_call"] = [PLUGIN.tools.on_pre_tool_call, veto]
    PLUGIN.gates.clear()
    block_message, _modified = hermes._dispatch_pre_tool_call_hooks("sound_cut_trim", args)
    assert block_message and "other plugin" in block_message
    assert not output.exists()


def test_cron_dispatch_blocks(hermes, tmp_path, monkeypatch):
    args, output = _ready(tmp_path)
    for env in (
        {"HERMES_CRON_SESSION": "1"},
        {"HERMES_SINGLE_QUERY_SESSION": "1"},
        {"HERMES_SESSION_PLATFORM": "webhook"},
        {"HERMES_SESSION_PLATFORM": "msgraph_webhook"},
        {"HERMES_SESSION_PLATFORM": "api_server"},
        {"HERMES_PLUGIN_HOST_PROCESS": "1"},
    ):
        for key in (
            "HERMES_CRON_SESSION",
            "HERMES_SINGLE_QUERY_SESSION",
            "HERMES_SESSION_PLATFORM",
            "HERMES_PLUGIN_HOST_PROCESS",
        ):
            monkeypatch.delenv(key, raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        PLUGIN.gates.clear()
        block_message, _modified = hermes._dispatch_pre_tool_call_hooks("sound_cut_trim", args)
        assert block_message and "BLOCKED" in block_message, env
        assert "always" in block_message
        assert not output.exists()


def test_yolo_and_approvals_off_do_not_block(hermes, tmp_path, monkeypatch):
    args, output = _ready(tmp_path)
    details = hermes._get_pre_tool_call_directive_details("sound_cut_trim", args)
    assert details.action == "approve"
    import tools.approval as approval

    monkeypatch.setenv("HERMES_SESSION_KEY", "sound-cut-test")
    approval.enable_session_yolo("sound-cut-test")
    try:
        block_message, _modified = hermes._dispatch_pre_tool_call_hooks("sound_cut_trim", args)
        assert block_message is None
    finally:
        approval.disable_session_yolo("sound-cut-test")
    import tools.approval_context as approval_context

    monkeypatch.setattr(approval_context, "_get_approval_mode", lambda: "off")
    PLUGIN.gates.clear()
    block_message, _modified = hermes._dispatch_pre_tool_call_hooks("sound_cut_trim", dict(args))
    assert block_message is None
    assert not output.exists()


def test_dispatcher_block_does_not_call_the_handler(hermes, tmp_path, monkeypatch):
    args, output = _ready(tmp_path)
    monkeypatch.setenv("HERMES_CRON_SESSION", "1")
    block_message, _modified = hermes._dispatch_pre_tool_call_hooks("sound_cut_trim", args)
    assert block_message
    body = json.loads(PLUGIN.tools.HANDLERS["sound_cut_trim"](args, session_id="", task_id=""))
    assert body["wrote"] is False
    assert not output.exists()
