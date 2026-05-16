"""
Convert generated audio (WAV) into a PrettyMIDI section for FL export.
Uses librosa pitch tracking (no extra ML deps). Optional basic-pitch if installed.
"""

import logging
import tempfile
from pathlib import Path

import librosa
import numpy as np
import pretty_midi

from agent.music_theory import chord_to_pitches, diatonic_progression

logger = logging.getLogger(__name__)


def _quantize_time(t: float, tempo: float, steps_per_beat: int = 4) -> float:
    spb = 60.0 / tempo
    step = spb / steps_per_beat
    return round(t / step) * step


def _audio_to_notes_librosa(wav_path: str, tempo: float) -> list[tuple[int, float, float, int]]:
    """Return list of (pitch, start, end, velocity)."""
    y, sr = librosa.load(wav_path, sr=22050, mono=True)
    f0, voiced, voiced_probs = librosa.pyin(
        y,
        fmin=librosa.note_to_hz("C2"),
        fmax=librosa.note_to_hz("C7"),
        sr=sr,
    )
    times = librosa.times_like(f0, sr=sr)
    notes: list[tuple[int, float, float, int]] = []
    i = 0
    while i < len(f0):
        if not voiced[i] or f0[i] is None or np.isnan(f0[i]):
            i += 1
            continue
        pitch = int(round(librosa.hz_to_midi(float(f0[i]))))
        pitch = max(36, min(84, pitch))
        start = float(times[i])
        j = i + 1
        while j < len(f0) and voiced[j] and f0[j] is not None and not np.isnan(f0[j]):
            p2 = int(round(librosa.hz_to_midi(float(f0[j]))))
            if abs(p2 - pitch) > 1:
                break
            j += 1
        end = float(times[min(j, len(times) - 1)])
        if end - start < 0.08:
            i = j
            continue
        vel = int(60 + 40 * float(voiced_probs[i] or 0.5))
        notes.append((pitch, start, end, vel))
        i = j
    return notes


def _try_basic_pitch(wav_path: str) -> pretty_midi.PrettyMIDI | None:
    try:
        from basic_pitch.inference import predict
        from basic_pitch import ICASSP_2022_MODEL_PATH
    except ImportError:
        return None
    try:
        _, midi_data, _ = predict(wav_path, ICASSP_2022_MODEL_PATH)
        return midi_data
    except Exception as e:
        logger.warning(f"basic-pitch failed: {e}")
        return None


def wav_to_section_midi(
    wav_path: str,
    output_path: str,
    tempo: float,
    params: dict | None = None,
    trim_start_sec: float = 0.0,
) -> None:
    """
    Write a multi-track MIDI section from generated audio.
    params: Nemotron section (key, chord_progression, bars) for harmony bed.
    """
    params = params or {}
    key = params.get("key", "C major")
    chords = params.get("chord_progression") or diatonic_progression(key)
    bars = int(params.get("bars") or 8)
    spb = 60.0 / tempo

    pm = pretty_midi.PrettyMIDI(initial_tempo=tempo)
    pm_bp = _try_basic_pitch(wav_path)
    if pm_bp and pm_bp.instruments:
        for inst in pm_bp.instruments:
            if inst.is_drum:
                continue
            new_inst = pretty_midi.Instrument(program=0, name="Generated")
            for note in inst.notes:
                if note.start < trim_start_sec:
                    continue
                new_inst.notes.append(
                    pretty_midi.Note(
                        velocity=note.velocity,
                        pitch=note.pitch,
                        start=max(0.0, note.start - trim_start_sec),
                        end=max(0.05, note.end - trim_start_sec),
                    )
                )
            if new_inst.notes:
                pm.instruments.append(new_inst)
                break
    else:
        raw = _audio_to_notes_librosa(wav_path, tempo)
        melody = pretty_midi.Instrument(program=0, name="Generated")
        for pitch, start, end, vel in raw:
            if start < trim_start_sec:
                continue
            t0 = max(0.0, start - trim_start_sec)
            t1 = max(t0 + 0.05, end - trim_start_sec)
            t0 = _quantize_time(t0, tempo)
            t1 = _quantize_time(t1, tempo)
            if t1 <= t0:
                t1 = t0 + 60.0 / tempo / 4
            melody.notes.append(
                pretty_midi.Note(velocity=vel, pitch=pitch, start=t0, end=t1)
            )
        if melody.notes:
            pm.instruments.append(melody)

    harmony = pretty_midi.Instrument(program=89, name="Harmony")
    bass = pretty_midi.Instrument(program=33, name="Bass")
    for bar in range(bars):
        chord = chords[bar % len(chords)]
        t0 = bar * 4 * spb
        for p in chord_to_pitches(chord, octave=3):
            harmony.notes.append(
                pretty_midi.Note(velocity=58, pitch=p, start=t0, end=t0 + 4 * spb - 0.05)
            )
        root = chord_to_pitches(chord, octave=2)[0]
        bass.notes.append(
            pretty_midi.Note(velocity=78, pitch=root, start=t0, end=t0 + 2 * spb - 0.02)
        )
        bass.notes.append(
            pretty_midi.Note(
                velocity=72, pitch=root, start=t0 + 2 * spb, end=t0 + 4 * spb - 0.02
            )
        )
    if harmony.notes:
        pm.instruments.insert(0, harmony)
    if bass.notes:
        pm.instruments.insert(0, bass)

    pm.write(output_path)
    logger.info(f"Audio→MIDI section saved → {output_path}")
