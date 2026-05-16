"""
Slash command router. Parses input, dispatches to the right command module.

All command functions are synchronous and meant to run in a QThread worker.
"""

from pathlib import Path


def route(raw: str, midi_path: str | None, style_context: str | None, output_dir: str) -> dict:
    """
    Parse a slash command string and dispatch to the right handler.

    Returns a dict with at minimum:
        type: "text" | "files" | "error" | "style"
        message: str
    And optionally:
        files: list[dict]   — for type="files"
        style: str          — for type="style" (new style to store)
        analysis: dict      — analysis result for reference
    """
    raw = raw.strip()
    if not raw.startswith("/"):
        return {
            "type": "text",
            "message": (
                "Commands:\n"
                "  /fill           — generate MIDI continuation from loaded file\n"
                "  /vibe <text>    — compose from a text description\n"
                "  /suggest        — get 3 text ideas (no MIDI)\n"
                "  /analyze        — read key, tempo, energy, chords\n"
                "  /mix            — generate a complementary stem\n"
                "  /style <artist> — nudge generation toward an artist reference\n"
                "  /help           — show this"
            ),
        }

    parts = raw.split(maxsplit=1)
    cmd = parts[0].lower()
    args = parts[1].strip() if len(parts) > 1 else ""

    from plugin.commands import analyze, vibe, suggest, fill, style, mix

    if cmd == "/analyze":
        if not midi_path:
            return {"type": "error", "message": "No MIDI loaded — drop a .mid file first"}
        return analyze.run(midi_path)

    elif cmd == "/vibe":
        return vibe.run(args, output_dir)

    elif cmd == "/suggest":
        return suggest.run(midi_path, prompt=args or None, style_context=style_context)

    elif cmd == "/fill":
        return fill.run(midi_path, prompt=args or None, style_context=style_context, output_dir=output_dir)

    elif cmd == "/mix":
        return mix.run(midi_path, prompt=args or None, style_context=style_context, output_dir=output_dir)

    elif cmd == "/style":
        result = style.run(args)
        if result["type"] == "text" and "style" in result:
            result["type"] = "style"
        return result

    elif cmd in ("/help", "/?"):
        return route("", midi_path, style_context, output_dir)

    else:
        return {"type": "error", "message": f"Unknown command: {cmd}\nType /help for available commands"}
