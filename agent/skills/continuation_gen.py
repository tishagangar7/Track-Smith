"""
Continuation Generator —
Step 1: Nemotron reasons about 3 musical directions from an analysis
Step 2: Generates real MIDI files for each direction
"""

import os
import json
import logging
import requests
import numpy as np
import pretty_midi
from pathlib import Path
from typing import Union

from agent.config import (
    NVIDIA_API_KEY, NVIDIA_BASE_URL, NEMOTRON_MODEL,
    NEMOTRON_TIMEOUT, NEMOTRON_MAX_TOKENS, NEMOTRON_TEMPERATURE
)

logger = logging.getLogger(__name__)

STUB_MODE = os.getenv("STUB_MODE", "false").lower() == "true"

# ── GM drum note numbers ──────────────────────────────────────────────────────
KICK      = 36
SNARE     = 38
CLAP      = 39
CLOSED_HH = 42
OPEN_HH   = 46

# ── Music theory helpers ──────────────────────────────────────────────────────
PITCH_NAMES = ["C", "C#", "D", "D#", "E", "F",
               "F#", "G", "G#", "A", "A#", "B"]

CHORD_ROOT_MAP = {
    "C": 60, "C#": 61, "Db": 61, "D": 62, "D#": 63, "Eb": 63,
    "E": 64, "F": 65, "F#": 66, "Gb": 66, "G": 67, "G#": 68,
    "Ab": 68, "A": 69, "A#": 70, "Bb": 70, "B": 71,
    "Am": 69, "Dm": 62, "Em": 64, "Bm": 71, "Fm": 65,
    "Gm": 67, "Cm": 60, "Gm": 67,
}

CHORD_INTERVALS = {
    "major": [0, 4, 7],
    "minor": [0, 3, 7],
    "dim":   [0, 3, 6],
    "aug":   [0, 4, 8],
}

NOTE_NAME_TO_MIDI = {}
for octave in range(0, 9):
    for i, name in enumerate(PITCH_NAMES):
        num = (octave + 1) * 12 + i
        if 0 <= num <= 127:
            NOTE_NAME_TO_MIDI[f"{name}{octave}"] = num


def chord_to_notes(chord_name: str, octave_offset: int = 0) -> list:
    """Convert chord name like 'Am' or 'C' to MIDI note numbers."""
    import re
    match = re.match(r"([A-G][#b]?)(m|maj|dim|aug)?", chord_name)
    if not match:
        return [60, 64, 67]

    root_str = match.group(1)
    quality = match.group(2) or "major"
    if quality == "m":
        quality = "minor"

    root = CHORD_ROOT_MAP.get(root_str, 60) + (octave_offset * 12)
    intervals = CHORD_INTERVALS.get(quality, [0, 4, 7])
    return [root + i for i in intervals]


# ── Step 1: Nemotron reasoning ────────────────────────────────────────────────

def reason_with_nemotron(analysis: dict, artist_prompt: str = None) -> list:
    """
    Ask Nemotron to reason about 3 musical continuation directions.
    Returns list of 3 parameter dicts.
    """
    if STUB_MODE:
        logger.info("STUB_MODE: skipping Nemotron call in reason_with_nemotron")
        return [
            {
                "option": i,
                "description": f"Stub continuation {i}",
                "vibe": ["melodic build", "steady groove", "gentle drop"][i - 1],
                "key": analysis.get("key", "A minor"),
                "tempo": 120,
                "energy_direction": ["build", "maintain", "drop"][i - 1],
                "chord_progression": ["Am", "F", "C", "G"],
                "suggested_notes": ["A3", "C4", "E4", "G4"],
                "instruments_to_add": ["bass"] if i == 1 else [],
                "arrangement_note": "stub",
            }
            for i in range(1, 4)
        ]

    artist_context = (
        f"\nThe artist says: \"{artist_prompt}\"\n"
        f"Use this as the primary creative direction for all 3 options."
        if artist_prompt else ""
    )

    prompt = f"""You are an expert music producer and composer.

A producer dropped a MIDI file with these characteristics:
- Key: {analysis['key']}
- Tempo: {analysis['tempo']} BPM
- Duration: {analysis['duration']}s
- Instruments: {', '.join(analysis['instruments'])}
- Energy: {analysis['energy']} (0=low, 1=high)
- Chord progression: {analysis.get('chord_progression', [])}
{artist_context}
Generate 3 distinct 8-bar continuation options. Each should take the music somewhere different.

Respond ONLY with a valid JSON array of 3 objects, no other text:
[
  {{
    "option": 1,
    "description": "one sentence describing this continuation",
    "vibe": "2-3 word label",
    "key": "key e.g. A minor",
    "tempo": 90,
    "energy_direction": "build/drop/maintain",
    "chord_progression": ["Am", "F", "C", "G"],
    "suggested_notes": ["A3", "C4", "E4", "G4"],
    "instruments_to_add": ["bass"],
    "arrangement_note": "what changes structurally"
  }}
]"""

    headers = {
        "Authorization": f"Bearer {NVIDIA_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": NEMOTRON_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": NEMOTRON_MAX_TOKENS,
        "temperature": NEMOTRON_TEMPERATURE,
    }

    logger.info(f"Asking Nemotron for continuation directions{' (with artist prompt)' if artist_prompt else ''}...")
    response = requests.post(
        f"{NVIDIA_BASE_URL}/chat/completions",
        headers=headers,
        json=payload,
        timeout=NEMOTRON_TIMEOUT,
    )
    response.raise_for_status()

    content = response.json()["choices"][0]["message"]["content"].strip()
    content = content.strip("```json").strip("```").strip()

    return json.loads(content)


# ── Step 2: Generate MIDI from params ────────────────────────────────────────

def generate_midi_from_params(params: dict, output_path: str, tempo: float):
    """Generate a real MIDI file from Nemotron's musical parameters."""
    midi = pretty_midi.PrettyMIDI(initial_tempo=tempo)
    spb = 60.0 / tempo  # seconds per beat

    # harmony track
    harmony = pretty_midi.Instrument(program=0, name="Harmony")
    chord_prog = params.get("chord_progression", ["C", "Am", "F", "G"])
    beats_per_chord = 2.0

    for i, chord in enumerate(chord_prog * 2):
        start = i * beats_per_chord * spb
        end = start + beats_per_chord * spb
        for pitch in chord_to_notes(chord, octave_offset=-1):
            harmony.notes.append(pretty_midi.Note(
                velocity=70,
                pitch=min(127, max(0, pitch)),
                start=start,
                end=end - 0.05
            ))
    midi.instruments.append(harmony)

    # melody track
    melody_inst = pretty_midi.Instrument(program=0, name="Melody")
    suggested = params.get("suggested_notes", [])
    melody_pitches = [NOTE_NAME_TO_MIDI[n] for n in suggested if n in NOTE_NAME_TO_MIDI]

    if not melody_pitches:
        root = CHORD_ROOT_MAP.get(params.get("key", "C").split()[0], 60)
        melody_pitches = [root + i for i in [0, 2, 4, 5, 7, 9, 11]]

    total_dur = len(chord_prog) * 2 * beats_per_chord * spb * 2
    note_dur = spb * 0.5
    energy = params.get("energy_direction", "maintain")
    base_vel = 80
    t, idx = 0.0, 0

    while t < total_dur - note_dur:
        pitch = melody_pitches[idx % len(melody_pitches)]
        if energy == "build":
            velocity = min(127, base_vel + int((t / total_dur) * 40))
        elif energy == "drop":
            velocity = max(40, base_vel - int((t / total_dur) * 40))
        else:
            velocity = base_vel + np.random.randint(-10, 10)

        melody_inst.notes.append(pretty_midi.Note(
            velocity=int(velocity),
            pitch=min(127, max(0, pitch)),
            start=t,
            end=t + note_dur - 0.02
        ))
        t += note_dur * np.random.choice([1, 1, 1, 2])
        idx += 1
    midi.instruments.append(melody_inst)

    # bass track
    if "bass" in params.get("instruments_to_add", []):
        bass = pretty_midi.Instrument(program=32, name="Bass")
        for i, chord in enumerate(chord_prog * 2):
            start = i * beats_per_chord * spb
            end = start + beats_per_chord * spb
            root_notes = chord_to_notes(chord, octave_offset=-2)
            bass.notes.append(pretty_midi.Note(
                velocity=85,
                pitch=min(127, max(0, root_notes[0])),
                start=start,
                end=end - 0.05
            ))
        midi.instruments.append(bass)

    midi.write(output_path)
    logger.info(f"MIDI written: {output_path}")


# ── Drum generation ───────────────────────────────────────────────────────────

def _infer_drum_style(text: str) -> str:
    """Infer drum style from artist prompt text."""
    t = text.lower()
    if "trap" in t:
        return "trap"
    if "house" in t:
        return "house"
    if "lo-fi" in t or "lofi" in t or "lo fi" in t:
        return "lo-fi"
    return "default"


def generate_drum_track(tempo: float, energy: float, style: str) -> pretty_midi.Instrument:
    """
    Generate a 4-bar MIDI drum pattern on the GM drum channel (is_drum=True).
    energy (0.0-1.0) scales velocity between 60 and 115.
    style: "trap" | "house" | "lo-fi" | "default"
    """
    drums = pretty_midi.Instrument(program=0, is_drum=True, name="Drums")
    spb = 60.0 / tempo
    base_vel = int(60 + energy * 55)  # 60 (quiet) to 115 (loud)
    hit_dur = 0.05

    def hit(pitch, t, vel_offset=0):
        start = max(0.0, float(t))
        v = min(127, max(1, base_vel + int(vel_offset)))
        drums.notes.append(pretty_midi.Note(
            velocity=v, pitch=pitch, start=start, end=start + hit_dur
        ))

    for bar in range(4):
        b = bar * 4 * spb  # bar start in seconds

        if style == "trap":
            hit(KICK, b)
            if bar > 0:
                hit(KICK, b + 2.5 * spb, -5)
                if energy > 0.5:
                    hit(KICK, b + 1.75 * spb, -10)
            hit(SNARE, b + spb)
            hit(SNARE, b + 3 * spb)
            if energy > 0.6:
                hit(CLAP, b + spb, -5)
                hit(CLAP, b + 3 * spb, -5)
            # 8th-note triplet hi-hats (3 per beat)
            for beat in range(4):
                for trip in range(3):
                    hit(CLOSED_HH, b + beat * spb + trip * spb / 3,
                        vel_offset=0 if trip == 0 else -15)

        elif style == "house":
            for beat in range(4):
                hit(KICK, b + beat * spb)
            hit(SNARE, b + spb)
            hit(SNARE, b + 3 * spb)
            for eighth in range(8):
                pitch = OPEN_HH if eighth % 2 == 0 else CLOSED_HH
                hit(pitch, b + eighth * spb / 2,
                    vel_offset=0 if eighth % 2 == 0 else -15)

        elif style == "lo-fi":
            def jitter():
                return float(np.random.uniform(-0.010, 0.010))

            hit(KICK, b + jitter())
            hit(KICK, b + 2 * spb + jitter(), -5)
            hit(SNARE, b + spb + jitter())
            hit(SNARE, b + 3 * spb + jitter())
            for beat in range(4):
                if np.random.random() > 0.3:
                    vel_off = int(np.random.uniform(-20, 0))
                    hit(CLOSED_HH, b + beat * spb + jitter(), vel_off)
                    if np.random.random() > 0.6:
                        hit(CLOSED_HH, b + beat * spb + spb / 2 + jitter(), vel_off - 10)

        else:  # default
            hit(KICK, b)
            hit(KICK, b + 2 * spb)
            hit(SNARE, b + spb)
            hit(SNARE, b + 3 * spb)
            for eighth in range(8):
                hit(CLOSED_HH, b + eighth * spb / 2, -10)

    return drums


# ── Suggest mode (plain text, no MIDI) ───────────────────────────────────────

def _suggest_with_nemotron(analysis: dict, artist_prompt: str = None) -> str:
    """Ask Nemotron for plain-text production suggestions. No JSON, no MIDI generation."""
    if STUB_MODE:
        logger.info("STUB_MODE: skipping Nemotron call in _suggest_with_nemotron")
        return (
            "1. Add a sub bass on beats 1 and 3\n"
            "2. Bring in hi-hats on the upbeats\n"
            "3. Try a Rhodes piano for the chords"
        )

    context = f"\nArtist direction: \"{artist_prompt}\"" if artist_prompt else ""

    prompt = f"""You are an expert music producer giving creative direction.

MIDI analysis:
- Key: {analysis['key']} · Tempo: {analysis['tempo']} BPM
- Duration: {analysis['duration']}s · Energy: {analysis['energy']:.2f}
- Chords: {' → '.join(analysis.get('chord_progression', []))}{context}

Give 3 specific, actionable ideas for where this track could go next.
Plain text, numbered list, one sentence per idea. No JSON."""

    headers = {
        "Authorization": f"Bearer {NVIDIA_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": NEMOTRON_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 300,
        "temperature": NEMOTRON_TEMPERATURE,
    }

    response = requests.post(
        f"{NVIDIA_BASE_URL}/chat/completions",
        headers=headers,
        json=payload,
        timeout=NEMOTRON_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()


# ── Main pipeline ─────────────────────────────────────────────────────────────

def generate_continuations(
    analysis: dict,
    output_dir: str,
    prompt: str = None,
    mode: str = "full",
) -> Union[list, str]:
    """
    mode='full'    → Nemotron reasoning + MIDI generation (harmony + melody + bass + drums).
                     Returns list of result dicts.
    mode='suggest' → Nemotron reasoning only, plain-text string. No MIDI files written.
                     Returns a string.
    """
    if mode == "suggest":
        try:
            return _suggest_with_nemotron(analysis, artist_prompt=prompt)
        except Exception as e:
            logger.error(f"Nemotron suggest failed: {e}")
            return "Could not reach Nemotron — check API key and model name."

    # ── mode == "full" ────────────────────────────────────────────────────────
    Path(output_dir).mkdir(exist_ok=True)
    drum_style = _infer_drum_style(prompt or "")

    try:
        options = reason_with_nemotron(analysis, artist_prompt=prompt)
    except Exception as e:
        logger.error(f"Nemotron failed, using fallback: {e}")
        options = [
            {
                "option": i, "description": f"Continuation {i}",
                "vibe": v, "key": analysis["key"],
                "tempo": analysis["tempo"], "energy_direction": d,
                "chord_progression": ["C", "Am", "F", "G"],
                "suggested_notes": ["C4", "E4", "G4"],
                "instruments_to_add": [],
            }
            for i, (v, d) in enumerate(
                [("melodic build", "build"), ("steady groove", "maintain"), ("gentle drop", "drop")], 1
            )
        ]

    results = []
    for opt in options[:3]:
        filename = f"continuation_{opt.get('option', 1)}.mid"
        filepath = str(Path(output_dir) / filename)

        try:
            track_tempo = float(opt.get("tempo", analysis["tempo"]))
            generate_midi_from_params(opt, filepath, track_tempo)

            # Append drum track to the same MIDI file
            drum_track = generate_drum_track(
                tempo=track_tempo,
                energy=analysis["energy"],
                style=drum_style,
            )
            midi_with_drums = pretty_midi.PrettyMIDI(filepath)
            midi_with_drums.instruments.append(drum_track)
            midi_with_drums.write(filepath)
            logger.info(f"Drums appended ({drum_style}) to {filename}")

            results.append({
                "option": opt.get("option"),
                "filename": filename,
                "filepath": filepath,
                "description": opt.get("description", ""),
                "vibe": opt.get("vibe", ""),
                "key": opt.get("key", ""),
                "tempo": opt.get("tempo", analysis["tempo"]),
                "chord_progression": opt.get("chord_progression", []),
            })
        except Exception as e:
            logger.error(f"MIDI generation failed for option {opt.get('option')}: {e}")

    return results
