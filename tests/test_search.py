"""Ordinary requests for a sound effect land on the right tool."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from helpers import PLUGIN

QUERIES = (
    ("trim silence from a sound effect", "sound_cut_trim"),
    ("estimated tempo and peak of a wav", "sound_cut_inspect"),
    ("midi track note count", "sound_cut_midi"),
)


def _catalog():
    src = os.environ.get("HERMES_SRC")
    if not src or not (Path(src) / "tools" / "tool_search_catalog.py").is_file():
        pytest.skip("set HERMES_SRC to a Hermes source tree")
    sys.path.insert(0, src)
    from tools.tool_search_catalog import build_catalog, search_catalog

    defs = []
    for schema in PLUGIN.schemas.ALL_SCHEMAS:
        defs.append({
            "type": "function",
            "function": {
                "name": schema["name"],
                "description": schema["description"],
                "parameters": schema["parameters"],
            },
        })
    for name, description in (
        ("weather_today", "Weather forecast for a city today."),
        ("list_issues", "List issues in a repository and leave a comment."),
        ("send_email", "Send an email message to a teammate."),
    ):
        defs.append({"type": "function", "function": {"name": name, "description": description}})
    return build_catalog(defs), search_catalog


def test_three_ordinary_phrases_rank_the_tool():
    catalog, search_catalog = _catalog()
    for query, expected in QUERIES:
        ranked = [entry.name for entry in search_catalog(catalog, query, limit=5)]
        assert expected in ranked, (query, ranked)


def test_phrases_are_written_in_the_skill():
    text = (Path(__file__).resolve().parents[1] / "skills" / "sound-cut" / "SKILL.md").read_text(encoding="utf-8")
    for query, _expected in QUERIES:
        assert query in text
