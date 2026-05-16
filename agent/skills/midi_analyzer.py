"""
MIDI Analyzer — extracts key, BPM, energy, chords, and structure
from any MIDI file using pretty_midi.
"""

import numpy as np
import pretty_midi
import logging

logger = logging.getLogger(__name__)

# ── Key detection ─────────────────────────────────────────────────────────────
PITCH_NAMES = ["C", "C#", "D", "D#", "E", "F",
               "F#", "G", "G#", "A", "A#", "B"]

MAJOR_PROFILE = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09,
                 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]

MINOR_PROFILE = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53,
                 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]


def detect_key(midi: pretty_midi.PrettyMIDI) -> str:
    """Estimate key using Krumhansl-Schmuckler algorithm."""
    chroma = np.zeros(12)

    for instrument in midi.instruments:
        if not instrument.is_drum:
            for note in instrument.notes:
                chroma[note.pitch % 12] += note.end - note.start

    if chroma.sum() == 0:
        return "Unknown"

    chroma = chroma / chroma.sum()
    best_score = -np.inf
    best_key = "C major"

    for i in range(12):
        rotated = np.roll(chroma, -i)
        major_corr = np.corrcoef(rotated, MAJOR_PROFILE)[0, 1]
        minor_corr = np.corrcoef(rotated, MINOR_PROFILE)[0, 1]

        if major_corr > best_score:
            best_score = major_corr
            best_key = f"{PITCH_NAMES[i]} major"
        if minor_corr > best_score:
            best_score = minor_corr
            best_key = f"{PITCH_NAMES[i]} minor"

    return best_key


def compute_energy(midi: pretty_midi.PrettyMIDI) -> float:
    """Estimate energy from average velocity and note density."""
    velocities = []
    durations = []

    for instrument in midi.instruments:
        if not instrument.is_drum:
            for note in instrument.notes:
                velocities.append(note.velocity)
                durations.append(note.end - note.start)

    if not velocities:
        return 0.0

    avg_velocity = np.mean(velocities) / 127.0
    total_duration = midi.get_end_time()
    note_density = len(velocities) / total_duration if total_duration > 0 else 0
    normalized_density = min(note_density / 10.0, 1.0)

    return float(round((avg_velocity + normalized_density) / 2.0, 3))


def get_chord_progression(midi: pretty_midi.PrettyMIDI, num_chords: int = 4) -> list:
    """Estimate chord progression by sampling dominant pitch per segment."""
    end_time = midi.get_end_time()
    if end_time == 0:
        return []

    interval = end_time / num_chords
    chords = []

    for i in range(num_chords):
        start = i * interval
        end = start + interval
        chroma = np.zeros(12)

        for instrument in midi.instruments:
            if not instrument.is_drum:
                for note in instrument.notes:
                    if note.start < end and note.end > start:
                        chroma[note.pitch % 12] += 1

        if chroma.sum() > 0:
            chords.append(PITCH_NAMES[int(np.argmax(chroma))])

    return chords


def analyze_midi(file_path: str) -> dict:
    """
    Full analysis of a MIDI file.
    Returns a dict with all features Nemotron needs to reason about.
    """
    logger.info(f"Analyzing: {file_path}")

    try:
        midi = pretty_midi.PrettyMIDI(file_path)
    except Exception as e:
        raise ValueError(f"Could not parse MIDI: {e}")

    tempo_changes = midi.get_tempo_changes()
    tempos = tempo_changes[1] if len(tempo_changes[1]) > 0 else [120.0]
    avg_tempo = float(round(np.mean(tempos), 1))

    instruments = []
    for inst in midi.instruments:
        name = inst.name if inst.name else ("Drums" if inst.is_drum else "Instrument")
        instruments.append(name)

    total_notes = sum(len(i.notes) for i in midi.instruments)

    result = {
        "tempo": avg_tempo,
        "key": detect_key(midi),
        "duration": round(midi.get_end_time(), 2),
        "instruments": instruments if instruments else ["Piano"],
        "total_notes": total_notes,
        "energy": compute_energy(midi),
        "chord_progression": get_chord_progression(midi),
        "num_tracks": len(midi.instruments),
    }

    logger.info(f"Result: {result}")
    return result
