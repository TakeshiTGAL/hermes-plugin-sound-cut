"""Sound Cut trims, slices, converts, and loops a game sound effect on this computer."""

from pathlib import Path

from . import attendance, schemas, tools
from .version import __version__  # noqa: F401

_SKILL = Path(__file__).resolve().parent / "skills" / "sound-cut" / "SKILL.md"
_SKILL_DESCRIPTION = (
    "Trim silence, cut a span, convert, or loop a game sound effect. "
    "Measure length, peak, and estimated tempo, or MIDI tracks and notes."
)


def register(ctx) -> None:
    from .cli import handle, setup_parser

    attendance.bind_context(ctx)
    for schema in schemas.ALL_SCHEMAS:
        ctx.register_tool(
            name=schema["name"],
            toolset="sound-cut",
            schema=schema,
            handler=tools.HANDLERS[schema["name"]],
            emoji="🔊",
        )
    ctx.register_skill("sound-cut", _SKILL, description=_SKILL_DESCRIPTION)
    ctx.register_hook("pre_tool_call", tools.on_pre_tool_call)
    ctx.register_cli_command(
        name="sound-cut",
        help="Measure or prepare a game sound effect",
        setup_fn=setup_parser,
        handler_fn=handle,
        description="Print one tool result as JSON. This command does not approve a write.",
    )
