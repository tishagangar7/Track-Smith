"""
MIDI Analyzer — extracts key, BPM, energy, chords, and structure
from any MIDI file using pretty_midi (with mido fallback for edge cases).
"""

import logging

import numpy as np
import pretty_midi

logger = logging.getLogger(__name__)

PITCH_NAMES = ["C", "C#", "D", "D#", "E", "F",
               "F#", "G", "G#", "A", "A#", "B"]

MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09,
                          2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53,
                          2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

# pitch classes for common triads (root = 0)
TRIAD_TEMPLATES = {
    "": [0, 4, 7],      # major
    "m": [0, 3, 7],     # minor
    "dim": [0, 3, 6],
}

NOTE_NAME_TO_PITCH = {}
for octave in range(0, 10):
    for i, name in enumerate(PITCH_NAMES):
        num = (octave + 1) * 12 + i
        if 0 <= num <= 127:
            NOTE_NAME_TO_PITCH[num] = f"{name}{octave}"


def pitch_to_name(pitch: int) -> str:
    return NOTE_NAME_TO_PITCH.get(pitch, f"{PITCH_NAMES[pitch % 12]}{pitch // 12 - 1}")


def detect_key_from_chroma(chroma: np.ndarray) -> str:
    """Krumhansl-Schmuckler — pick best root, then major vs minor at that root."""
    if chroma.sum() == 0:
        return "Unknown"
    chroma = chroma / chroma.sum()
    best_score = -np.inf
    best_key = "C major"
    for i in range(12):
        rotated = np.roll(chroma, -i)
        major_corr = float(np.corrcoef(rotated, MAJOR_PROFILE)[0, 1])
        minor_corr = float(np.corrcoef(rotated, MINOR_PROFILE)[0, 1])
        if minor_corr >= major_corr and minor_corr > best_score:
            best_score = minor_corr
            best_key = f"{PITCH_NAMES[i]} minor"
        elif major_corr > best_score:
            best_score = major_corr
            best_key = f"{PITCH_NAMES[i]} major"
    return best_key


def detect_key(midi: pretty_midi.PrettyMIDI) -> str:
    chroma = np.zeros(12)
    for instrument in midi.instruments:
        if not instrument.is_drum:
            for note in instrument.notes:
                chroma[note.pitch % 12] += note.end - note.start
    return detect_key_from_chroma(chroma)


def estimate_bpm(midi: pretty_midi.PrettyMIDI, file_path: str | None = None) -> float:
    """Best-effort BPM from MIDI content."""
    try:
        bpm = float(midi.estimate_tempo())
        if 40.0 <= bpm <= 300.0:
            return round(bpm, 1)
    except Exception:
        pass

    try:
        _, tempos = midi.get_tempo_changes()
        if len(tempos) > 0:
            bpm = float(np.median(tempos))
            if 40.0 <= bpm <= 300.0:
                return round(bpm, 1)
    except Exception:
        pass

    if file_path:
        import mido
        mid = mido.MidiFile(file_path)
        for track in mid.tracks:
            for msg in track:
                if msg.type == "set_tempo":
                    return round(60_000_000 / msg.tempo, 1)

    return 120.0


def compute_energy(midi: pretty_midi.PrettyMIDI) -> float:
    velocities = []
    for instrument in midi.instruments:
        if not instrument.is_drum:
            for note in instrument.notes:
                velocities.append(note.velocity)
    if not velocities:
        return 0.0
    avg_velocity = np.mean(velocities) / 127.0
    total_duration = midi.get_end_time()
    note_density = len(velocities) / total_duration if total_duration > 0 else 0
    normalized_density = min(note_density / 10.0, 1.0)
    return float(round((avg_velocity + normalized_density) / 2.0, 3))


def _chord_label_from_pitches(pitches: set[int]) -> str:
    """Map active pitch classes in a segment to a chord name like Am, F, C."""
    if not pitches:
        return "?"
    pcs = {p % 12 for p in pitches}
    best_name, best_score = "?", -1.0
    for root in range(12):
        for suffix, intervals in TRIAD_TEMPLATES.items():
            template = {(root + i) % 12 for i in intervals}
            score = len(pcs & template) / max(len(template), 1)
            if score > best_score and score >= 0.66:
                best_score = score
                best_name = f"{PITCH_NAMES[root]}{suffix}".replace("major", "").strip()
                if suffix == "" and not best_name.endswith("m"):
                    pass  # e.g. "C"
    if best_name == "?":
        # fallback: root pitch class only
        root = max(pcs, key=lambda p: sum(1 for x in pitches if x % 12 == p))
        best_name = PITCH_NAMES[root]
    return best_name


def get_chord_progression(
    midi: pretty_midi.PrettyMIDI,
    num_chords: int = 4,
    beats_per_chord: float = 2.0,
) -> list:
    """Chord labels from note onsets in each beat window (avoids smearing sustained parts)."""
    tempo = estimate_bpm(midi)
    spb = 60.0 / tempo
    window = beats_per_chord * spb
    chords = []
    for i in range(num_chords):
        start = i * window
        end = start + window
        pitches = set()
        for instrument in midi.instruments:
            if instrument.is_drum:
                continue
            for note in instrument.notes:
                if start <= note.start < end - 0.001:
                    pitches.add(note.pitch)
        if pitches:
            chords.append(_chord_label_from_pitches(pitches))
    return chords


def infer_key_from_chords(chords: list, chroma_key: str) -> str:
    """Prefer first minor chord as tonal center for producer-facing key label."""
    import re
    for label in chords:
        if not label or label == "?":
            continue
        m = re.match(r"^([A-G][#b]?)m$", label)
        if m:
            return f"{m.group(1)} minor"
        m = re.match(r"^([A-G][#b]?)$", label)
        if m and label:
            return f"{m.group(1)} major"
    return chroma_key


def extract_notes_with_mido(file_path: str, tempo: float = 120.0) -> list[dict]:
    import mido

    mid = mido.MidiFile(file_path)
    tpb = mid.ticks_per_beat
    us_per_beat = int(60_000_000 / tempo)
    merged = mido.merge_tracks(mid.tracks)

    tick = 0
    active: dict[tuple[int, int], tuple[float, int]] = {}
    events: list[dict] = []
    spb = 60.0 / tempo

    for msg in merged:
        tick += msg.time
        sec = mido.tick2second(tick, tpb, us_per_beat)
        beat = sec / spb
        ch = getattr(msg, "channel", 0)
        if msg.type == "note_on" and msg.velocity > 0:
            active[(ch, msg.note)] = (beat, msg.velocity)
        elif msg.type in ("note_off", "note_on") and (ch, msg.note) in active:
            start_beat, vel = active.pop((ch, msg.note))
            events.append({
                "pitch": msg.note,
                "start_beat": round(start_beat, 3),
                "duration_beats": round(max(0.05, beat - start_beat), 3),
                "velocity": vel,
                "is_drum": ch == 9,
                "name": pitch_to_name(msg.note),
            })

    return sorted(events, key=lambda e: e["start_beat"])


def _build_note_events(midi: pretty_midi.PrettyMIDI, tempo: float, max_events: int = 64) -> list[dict]:
    spb = 60.0 / tempo
    events = []
    for instrument in midi.instruments:
        for note in instrument.notes:
            events.append({
                "pitch": note.pitch,
                "start_beat": round(note.start / spb, 3),
                "duration_beats": round(max(0.05, (note.end - note.start) / spb), 3),
                "velocity": note.velocity,
                "is_drum": instrument.is_drum,
                "name": pitch_to_name(note.pitch),
            })
    events.sort(key=lambda e: e["start_beat"])
    return events[:max_events]


def _mido_events_to_pretty_midi(events: list[dict], tempo: float) -> pretty_midi.PrettyMIDI:
    midi = pretty_midi.PrettyMIDI(initial_tempo=tempo)
    melodic = pretty_midi.Instrument(program=0)
    drums = pretty_midi.Instrument(program=0, is_drum=True)
    spb = 60.0 / tempo
    for ev in events:
        start = ev["start_beat"] * spb
        end = start + ev["duration_beats"] * spb
        n = pretty_midi.Note(
            velocity=ev["velocity"],
            pitch=ev["pitch"],
            start=start,
            end=end,
        )
        if ev.get("is_drum"):
            drums.notes.append(n)
        else:
            melodic.notes.append(n)
    if melodic.notes:
        midi.instruments.append(melodic)
    if drums.notes:
        midi.instruments.append(drums)
    return midi


def analyze_midi(file_path: str) -> dict:
    logger.info(f"Analyzing MIDI: {file_path}")

    try:
        midi = pretty_midi.PrettyMIDI(file_path)
    except Exception as e:
        raise ValueError(f"Could not parse MIDI: {e}") from e

    avg_tempo = estimate_bpm(midi, file_path)

    total_notes = sum(len(i.notes) for i in midi.instruments)
    note_events = _build_note_events(midi, avg_tempo) if total_notes > 0 else []

    if total_notes == 0:
        note_events = extract_notes_with_mido(file_path, avg_tempo)
        if note_events:
            midi = _mido_events_to_pretty_midi(note_events, avg_tempo)
            total_notes = len(note_events)

    pitch_classes = sorted({PITCH_NAMES[e["pitch"] % 12] for e in note_events if not e.get("is_drum")})

    instruments = []
    for inst in midi.instruments:
        name = inst.name if inst.name else ("Drums" if inst.is_drum else "Instrument")
        instruments.append(name)

    chords = get_chord_progression(midi) if total_notes > 0 else []
    chroma_key = detect_key(midi)

    result = {
        "source_type": "midi",
        "tempo": avg_tempo,
        "key": infer_key_from_chords(chords, chroma_key),
        "duration": round(midi.get_end_time(), 2),
        "instruments": instruments if instruments else ["Piano"],
        "total_notes": total_notes,
        "has_notes": total_notes > 0,
        "energy": compute_energy(midi),
        "chord_progression": chords,
        "num_tracks": len(midi.instruments),
        "note_events": note_events,
        "pitch_classes": pitch_classes,
    }

    logger.info(f"MIDI result: total_notes={total_notes}, key={result['key']}, bpm={avg_tempo}")
    return result
