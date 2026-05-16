"""MIDI preview helpers — soundfont discovery and note detection for playback."""

from pathlib import Path
import sys

import mido


def find_soundfont() -> str | None:
    try:
        import pretty_midi

        sf = Path(pretty_midi.__file__).parent / "TimGM6mb.sf2"
        if sf.exists():
            return str(sf)
    except Exception:
        pass
    for base in (
        Path(__file__).resolve().parents[1] / "assets",
        Path(sys.prefix) / "lib",
    ):
        if not base.exists():
            continue
        for sf in base.rglob("TimGM6mb.sf2"):
            return str(sf)
    for sp in sys.path:
        sf = Path(sp) / "pretty_midi" / "TimGM6mb.sf2"
        if sf.exists():
            return str(sf)
    return None


def count_midi_notes(path: str) -> int:
    """Count note_on events (mido). Returns -1 if file unreadable."""
    try:
        mid = mido.MidiFile(path)
        merged = mido.merge_tracks(mid.tracks)
        return sum(
            1 for msg in merged if msg.type == "note_on" and msg.velocity > 0
        )
    except Exception:
        return -1


def count_midi_notes_pretty(path: str) -> int:
    try:
        import pretty_midi

        midi = pretty_midi.PrettyMIDI(path)
        return sum(len(i.notes) for i in midi.instruments)
    except Exception:
        return 0


def midi_has_notes(path: str) -> bool:
    n = count_midi_notes(path)
    if n > 0:
        return True
    if n == 0:
        return count_midi_notes_pretty(path) > 0
    return False


def native_us_per_beat(path: str, default_bpm: float = 120.0) -> int:
    """Read first set_tempo from MIDI, else derive from default_bpm."""
    try:
        mid = mido.MidiFile(path)
        for track in mid.tracks:
            for msg in track:
                if msg.type == "set_tempo":
                    return int(msg.tempo)
    except Exception:
        pass
    return int(60_000_000 / max(default_bpm, 1.0))
