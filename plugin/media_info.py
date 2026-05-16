"""Shared helpers for media drop zone and playback."""

from pathlib import Path

import mido

from agent.skills.input_analyzer import AUDIO_EXT, MIDI_EXT, input_type_for_path

MEDIA_FILTER = "Media (*.mid *.midi *.mp3 *.wav *.m4a *.flac)"


def is_supported_media(path: str) -> bool:
    return Path(path).suffix.lower() in MIDI_EXT | AUDIO_EXT


def count_midi_notes(path: str) -> int:
    try:
        mid = mido.MidiFile(path)
        return sum(
            1
            for track in mid.tracks
            for msg in track
            if msg.type == "note_on" and msg.velocity > 0
        )
    except Exception:
        return -1


def bpm_from_midi(path: str) -> float:
    try:
        import pretty_midi
        from agent.skills.midi_analyzer import estimate_bpm
        midi = pretty_midi.PrettyMIDI(path)
        return estimate_bpm(midi, path)
    except Exception:
        return 120.0


def describe_media(path: str) -> tuple[str, str]:
    """Return (source_type, short label for UI)."""
    kind = input_type_for_path(path)
    name = Path(path).name
    if kind == "audio":
        try:
            import librosa
            dur = librosa.get_duration(path=path)
            return "audio", f"{name}\n({dur:.1f}s · audio)"
        except Exception:
            return "audio", f"{name}\n(audio)"
    if kind == "midi":
        n = count_midi_notes(path)
        if n < 0:
            return "midi", name
        if n == 0:
            return "midi", f"{name}\n(0 notes — need export with notes)"
        return "midi", f"{name}\n({n} notes)"
    return "unknown", name
