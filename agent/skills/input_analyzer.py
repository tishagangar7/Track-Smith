"""
Unified input analysis — routes MIDI vs audio files to the right analyzer.
"""

from pathlib import Path

from agent.skills.midi_analyzer import analyze_midi
from agent.skills.audio_analyzer import analyze_audio

AUDIO_EXT = {".mp3", ".wav", ".m4a", ".flac", ".ogg"}
MIDI_EXT = {".mid", ".midi"}


def input_type_for_path(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext in AUDIO_EXT:
        return "audio"
    if ext in MIDI_EXT:
        return "midi"
    return "unknown"


def analyze_input(file_path: str) -> dict:
    """Analyze a dropped file (MIDI or audio)."""
    kind = input_type_for_path(file_path)
    if kind == "audio":
        return analyze_audio(file_path)
    if kind == "midi":
        return analyze_midi(file_path)
    raise ValueError(f"Unsupported file type: {Path(file_path).suffix}")


def empty_midi_error_message() -> str:
    return (
        "This MIDI has no notes. Export from FL with notes in the piano roll, "
        "drop an MP3 instead, or use /vibe to generate from scratch."
    )


def validate_input_for_generation(analysis: dict) -> str | None:
    """Return error message if input cannot be used for /fill, or None if OK."""
    if analysis.get("source_type") == "audio":
        return None
    if analysis.get("total_notes", 0) == 0:
        return empty_midi_error_message()
    return None
