"""
Continuation Generator — v3
Nemotron returns structured musical decisions (genre/mood/patterns/intensities).
A deterministic MIDI engine renders 6 named tracks: Drums, Bass, Chords, Lead, Percs, FX.
All melodic content is locked to the detected key. Output loops cleanly.
"""

import os
import json
import logging
import numpy as np
import pretty_midi
from pathlib import Path
from typing import Union

from agent.config import NEMOTRON_MAX_TOKENS, NEMOTRON_TEMPERATURE
from agent.nemotron_client import chat_completion, chat_json_array
from agent.openclaw_client import openclaw
from agent.music_theory import (
    diatonic_progression,
    melody_pitches_for_key,
    chord_to_pitches,
    parse_key,
    scale_pitch_classes,
)

logger = logging.getLogger(__name__)

STUB_MODE = os.getenv("STUB_MODE", "false").lower() == "true"
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# ── GM drum note numbers ──────────────────────────────────────────────────────
KICK      = 36
SNARE     = 38
CLAP      = 39
CLOSED_HH = 42
OPEN_HH   = 46
RIM       = 37   # side stick
SHAKER    = 70   # maracas

# ── Music theory helpers ──────────────────────────────────────────────────────
PITCH_NAMES = ["C", "C#", "D", "D#", "E", "F",
               "F#", "G", "G#", "A", "A#", "B"]

CHORD_ROOT_MAP = {
    "C": 60, "C#": 61, "Db": 61, "D": 62, "D#": 63, "Eb": 63,
    "E": 64, "F": 65, "F#": 66, "Gb": 66, "G": 67, "G#": 68,
    "Ab": 68, "A": 69, "A#": 70, "Bb": 70, "B": 71,
    "Am": 69, "Dm": 62, "Em": 64, "Bm": 71, "Fm": 65,
    "Gm": 67, "Cm": 60,
}

CHORD_INTERVALS = {
    "major": [0, 4, 7],
    "minor": [0, 3, 7],
    "dim":   [0, 3, 6],
    "aug":   [0, 4, 8],
}

NOTE_NAME_TO_MIDI: dict = {}
for _oct in range(0, 9):
    for _i, _nm in enumerate(PITCH_NAMES):
        _num = (_oct + 1) * 12 + _i
        if 0 <= _num <= 127:
            NOTE_NAME_TO_MIDI[f"{_nm}{_oct}"] = _num

# ── Valid pattern values (for sanitizing Nemotron output) ─────────────────────
_DRUM_PATTERNS  = {"trap_triplet", "boom_bap", "four_on_floor", "broken"}
_BASS_PATTERNS  = {"sub_root", "808_glide", "walking", "syncopated"}
_LEAD_MOTIFS    = {"ascending", "descending", "call_response", "static"}
_FX_TYPES       = {"riser", "atmospheric_pad", "noise_sweep", "none"}

# ── Contrasting fallback plans (genre + pattern combos guaranteed distinct) ────
_CONTRAST_SWAPS = [
    {
        "genre": "lo-fi", "mood": "melancholic", "vibe": "chill lo-fi loop",
        "description": "Lo-fi boom bap with jazzy walking bass",
        "drum_pattern": "boom_bap", "bass_pattern": "walking",
        "lead_motif": "call_response", "fx_type": "none",
        "pad_intensity": 0.7, "lead_density": 0.3, "perc_intensity": 0.4,
    },
    {
        "genre": "ambient", "mood": "ethereal", "vibe": "ambient atmosphere",
        "description": "Evolving ambient pad with riser and sparse broken rhythm",
        "drum_pattern": "broken", "bass_pattern": "sub_root",
        "lead_motif": "ascending", "fx_type": "atmospheric_pad",
        "pad_intensity": 0.9, "lead_density": 0.2, "perc_intensity": 0.1,
    },
    {
        "genre": "house", "mood": "uplifting", "vibe": "deep house groove",
        "description": "Four-on-the-floor house with syncopated bass and chords",
        "drum_pattern": "four_on_floor", "bass_pattern": "syncopated",
        "lead_motif": "static", "fx_type": "riser",
        "pad_intensity": 0.5, "lead_density": 0.5, "perc_intensity": 0.6,
    },
]


# ── Scale / note helpers ──────────────────────────────────────────────────────

def _filter_to_scale(pitches: list, key: str) -> list:
    """Remove MIDI note numbers not in the key's diatonic scale."""
    pcs = set(scale_pitch_classes(key))
    return [p for p in pitches if p % 12 in pcs]


def _scale_ascending(key: str, lo: int = 48, hi: int = 84) -> list:
    """All diatonic notes in ascending order within [lo, hi]."""
    pcs = set(scale_pitch_classes(key))
    return [p for p in range(lo, hi + 1) if p % 12 in pcs]


def chord_to_notes(chord_name: str, octave_offset: int = 0) -> list:
    """Convert chord name like 'Am' or 'C' to MIDI note numbers (legacy helper)."""
    import re
    m = re.match(r"([A-G][#b]?)(m|maj|dim|aug)?", chord_name)
    if not m:
        return [60, 64, 67]
    root_str = m.group(1)
    quality = m.group(2) or "major"
    if quality == "m":
        quality = "minor"
    root = CHORD_ROOT_MAP.get(root_str, 60) + (octave_offset * 12)
    intervals = CHORD_INTERVALS.get(quality, [0, 4, 7])
    return [root + i for i in intervals]


def _detect_track_roles(midi: pretty_midi.PrettyMIDI) -> set:
    """Detect which musical roles already exist in a MIDI (melody/harmony/bass/drums)."""
    roles = set()
    for inst in midi.instruments:
        if inst.is_drum:
            roles.add("drums")
            continue
        if not inst.notes:
            continue
        pitches = [n.pitch for n in inst.notes]
        avg_pitch = sum(pitches) / len(pitches)
        if avg_pitch < 52:
            roles.add("bass")
        else:
            starts = sorted(n.start for n in inst.notes)
            simultaneous = sum(
                1 for i in range(len(starts) - 1)
                if abs(starts[i] - starts[i + 1]) < 0.05
            )
            roles.add("harmony" if simultaneous > len(starts) * 0.2 else "melody")
    return roles


def _loop_instrument(inst: pretty_midi.Instrument, target_dur: float) -> pretty_midi.Instrument:
    """Loop/trim an instrument's notes to fill exactly target_dur seconds."""
    if not inst.notes:
        return inst
    src_dur = max(n.end for n in inst.notes)
    if src_dur <= 0:
        return inst
    new_inst = pretty_midi.Instrument(
        program=inst.program, is_drum=inst.is_drum, name=inst.name
    )
    sorted_notes = sorted(inst.notes, key=lambda n: n.start)
    offset = 0.0
    while offset < target_dur:
        for note in sorted_notes:
            ns = note.start + offset
            ne = min(note.end + offset, target_dur)
            if ns >= target_dur:
                break
            new_inst.notes.append(pretty_midi.Note(
                velocity=note.velocity, pitch=note.pitch, start=ns, end=ne
            ))
        offset += src_dur
    return new_inst


# ── Analysis context formatter ────────────────────────────────────────────────

def _format_analysis_context(analysis: dict) -> str:
    lines = [
        f"- Key: {analysis.get('key', 'Unknown')}",
        f"- Tempo: {analysis.get('tempo', 120)} BPM",
        f"- Duration: {analysis.get('duration', 0)}s",
        f"- Instruments: {', '.join(analysis.get('instruments', []))}",
        f"- Energy: {analysis.get('energy', 0)} (0=low, 1=high)",
        f"- Chord progression: {analysis.get('chord_progression', [])}",
    ]
    if analysis.get("source_type") == "audio":
        lines.insert(0, "- Source: audio file")
        af = analysis.get("audio_features") or {}
        if af:
            lines.append(
                f"- Audio character: {af.get('brightness', '')} · "
                f"centroid ~{af.get('spectral_centroid_mean', '?')} · "
                f"onset density {af.get('onset_density', '?')}"
            )
    else:
        lines.insert(0, "- Source: MIDI file")
        if analysis.get("has_notes"):
            sample = analysis.get("note_events", [])[:12]
            note_str = ", ".join(f"{e.get('name','?')}@{e.get('start_beat',0)}b" for e in sample)
            if note_str:
                lines.append(f"- Input notes (sample): {note_str}")
            pcs = analysis.get("pitch_classes", [])
            if pcs:
                lines.append(f"- Pitch classes: {', '.join(pcs)}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 1: NEMOTRON — structured musical decisions
# ═══════════════════════════════════════════════════════════════════════════════

def _fallback_plans(analysis: dict, artist_prompt: str = None) -> list:
    """Three genre-distinct fallback plans locked to the analyzed track."""
    key = analysis.get("key", "A minor")
    energy = float(analysis.get("energy", 0.5))
    chords = list(analysis.get("chord_progression") or diatonic_progression(key))
    while len(chords) < 4:
        chords = chords + chords
    chords = chords[:4]

    genre1 = "trap" if energy > 0.6 else "lo-fi"
    suffix = f" ({artist_prompt[:50]})" if artist_prompt else ""
    return [
        {
            "option": 1,
            "description": f"Dark {genre1} loop in {key}{suffix}",
            "vibe": f"{genre1} vibes",
            "genre": genre1,
            "mood": "dark",
            "chord_progression": chords,
            "bars": 8,
            "drum_pattern": "trap_triplet" if genre1 == "trap" else "boom_bap",
            "bass_pattern": "808_glide" if genre1 == "trap" else "walking",
            "lead_density": min(0.8, energy + 0.1),
            "lead_motif": "descending",
            "pad_intensity": 0.5,
            "perc_intensity": 0.4,
            "fx_type": "atmospheric_pad",
        },
        {
            "option": 2,
            "description": f"Boom bap groove in {key}{suffix}",
            "vibe": "classic boom bap",
            "genre": "lo-fi",
            "mood": "melancholic",
            "chord_progression": chords,
            "bars": 8,
            "drum_pattern": "boom_bap",
            "bass_pattern": "walking",
            "lead_density": max(0.15, energy * 0.6),
            "lead_motif": "call_response",
            "pad_intensity": 0.6,
            "perc_intensity": 0.5,
            "fx_type": "none",
        },
        {
            "option": 3,
            "description": f"Atmospheric ambient loop in {key}{suffix}",
            "vibe": "atmospheric",
            "genre": "ambient",
            "mood": "melancholic",
            "chord_progression": chords,
            "bars": 8,
            "drum_pattern": "broken",
            "bass_pattern": "sub_root",
            "lead_density": 0.2,
            "lead_motif": "ascending",
            "pad_intensity": 0.8,
            "perc_intensity": 0.2,
            "fx_type": "riser",
        },
    ]


def reason_with_nemotron(analysis: dict, artist_prompt: str = None) -> list:
    """
    Ask Nemotron for 3 structured musical decision plans.
    Returns list of 3 plan dicts. Each plan is rendered by the MIDI engine.
    Nemotron NEVER generates raw notes — only genre/mood/pattern decisions.
    """
    # Compute shared context first so sanitize/uniqueness can use it in both paths
    key = analysis.get("key", "A minor")
    tempo = float(analysis.get("tempo", 120))
    energy = float(analysis.get("energy", 0.5))
    chords = list(analysis.get("chord_progression") or diatonic_progression(key))
    while len(chords) < 4:
        chords = chords + chords
    chords = chords[:4]

    react_iterations = 0  # total Reason→Act→Observe cycles completed

    if STUB_MODE:
        logger.info("STUB_MODE: using fallback plans")
        result = _fallback_plans(analysis, artist_prompt)
    else:
        energy_label = "low" if energy < 0.4 else ("high" if energy > 0.7 else "medium")
        artist_ctx = f'\nArtist direction: "{artist_prompt}"' if artist_prompt else ""
        ctx = _format_analysis_context(analysis)

        # ── STEP 1: REASON — Nemotron identifies what this continuation needs ──
        logger.info("ReAct Step 1: Nemotron reasoning about track...")
        openclaw.call_nemotron("ReAct Step 1: track reasoning")
        _reason_system = (
            "You are an expert music producer assistant. /no_think\n"
            "Respond with plain text only. No JSON, no markdown."
        )
        _reason_prompt = (
            f"Given this track analysis, identify what this continuation needs:\n"
            f"Key: {key} | Tempo: {tempo} BPM | Energy: {energy:.2f} ({energy_label}){artist_ctx}\n"
            f"{ctx}\n\n"
            f"Think step by step:\n"
            f"1. Key compatibility: which scales or modes complement {key}?\n"
            f"2. Energy matching: what intensity and tempo feel suit energy={energy:.2f}?\n"
            f"3. Genre consistency: what genres or moods complement this track?\n\n"
            f"Be concise — 3-5 sentences. This analysis guides plan generation."
        )
        try:
            reasoning = chat_completion(
                _reason_prompt,
                task="fast",
                max_tokens=256,
                temperature=0.7,
                system_prompt=_reason_system,
            )
            logger.info("ReAct Step 1 complete: %s", reasoning[:120].replace("\n", " "))
        except Exception as _e:
            logger.warning("ReAct Step 1 failed (%s) — skipping reasoning context", _e)
            reasoning = ""

        # ── Shared prompts for STEP 2 (ACT) ───────────────────────────────────
        system_prompt = (
            "You are a music producer's AI assistant. "
            "Given an analysis of an input track, decide the genre, mood, "
            "and intensity of each instrument layer. "
            "Output ONLY the structured JSON — never raw notes. "
            "The MIDI engine handles all note generation deterministically. "
            "/no_think\n"
            "Respond with ONLY valid JSON array. No markdown fences."
        )

        few_shot = """\
EXAMPLE (A minor, 90 BPM, energy=0.45):
[
  {
    "option": 1, "description": "Dark trap loop with 808 glide bass", "vibe": "trap vibes",
    "genre": "trap", "mood": "dark", "chord_progression": ["Am", "F", "C", "G"],
    "bars": 8, "drum_pattern": "trap_triplet", "bass_pattern": "808_glide",
    "lead_density": 0.4, "lead_motif": "descending",
    "pad_intensity": 0.5, "perc_intensity": 0.4, "fx_type": "atmospheric_pad"
  },
  {
    "option": 2, "description": "Lo-fi boom bap with walking bass", "vibe": "chill loop",
    "genre": "lo-fi", "mood": "melancholic", "chord_progression": ["Am", "F", "C", "G"],
    "bars": 8, "drum_pattern": "boom_bap", "bass_pattern": "walking",
    "lead_density": 0.3, "lead_motif": "call_response",
    "pad_intensity": 0.6, "perc_intensity": 0.5, "fx_type": "none"
  },
  {
    "option": 3, "description": "Broken ambient loop with riser", "vibe": "atmospheric",
    "genre": "ambient", "mood": "melancholic", "chord_progression": ["Am", "F", "C", "G"],
    "bars": 8, "drum_pattern": "broken", "bass_pattern": "sub_root",
    "lead_density": 0.2, "lead_motif": "ascending",
    "pad_intensity": 0.8, "perc_intensity": 0.2, "fx_type": "riser"
  }
]
END EXAMPLE"""

        base_prompt = f"""\
Analyze this track and return 3 distinct producer loop plans.

TRACK ANALYSIS:
{ctx}
Key: {key} | Tempo: {tempo} BPM | Energy: {energy:.2f} ({energy_label}){artist_ctx}

Rules:
- chord_progression: MUST stay in {key} — do not invent chords outside this key
- bars: always 8
- drum_pattern: trap_triplet | boom_bap | four_on_floor | broken
- bass_pattern: sub_root | 808_glide | walking | syncopated
- lead_motif: ascending | descending | call_response | static
- fx_type: riser | atmospheric_pad | noise_sweep | none
- Each option must be a DIFFERENT genre/mood

DIVERSITY REQUIREMENT — this is critical:
Generate exactly 3 MUSICALLY DISTINCT options. They MUST differ meaningfully:
- Option 1: faithful to the original style and energy level
- Option 2: contrast — significantly higher or lower energy, or a different feel entirely
- Option 3: unexpected — genre blend or mood shift the producer would not expect
If all 3 share the same genre and drum_pattern you have failed the task.

{few_shot}

Generate 3 plans for THIS track. Respond ONLY with a valid JSON array of 3 objects:
[
  {{
    "option": 1, "description": "one sentence", "vibe": "2-3 words",
    "genre": "trap|house|lo-fi|drill|ambient",
    "mood": "dark|uplifting|melancholic|aggressive",
    "chord_progression": {json.dumps(chords)},
    "bars": 8,
    "drum_pattern": "trap_triplet|boom_bap|four_on_floor|broken",
    "bass_pattern": "sub_root|808_glide|walking|syncopated",
    "lead_density": 0.1-1.0,
    "lead_motif": "ascending|descending|call_response|static",
    "pad_intensity": 0.1-1.0,
    "perc_intensity": 0.0-1.0,
    "fx_type": "riser|atmospheric_pad|noise_sweep|none"
  }}
]"""

        # Prepend STEP 1 reasoning as additional context for STEP 2
        act_base = (
            f"Musical requirements identified:\n{reasoning}\n\n{base_prompt}"
            if reasoning else base_prompt
        )

        # ── STEP 2 + 3: ACT → OBSERVE loop (max 2 revisions) ─────────────────
        _MAX_REVISIONS = 2
        result = None
        revision_feedback = ""

        for _attempt in range(_MAX_REVISIONS + 1):
            react_iterations = _attempt + 1

            # ACT
            logger.info(
                "ReAct Step 2: Nemotron generating musical plan... (attempt %d)", _attempt + 1
            )
            openclaw.call_nemotron(f"ReAct Step 2: plan generation attempt {_attempt + 1}")

            act_prompt = (
                f"{act_base}\n\n"
                f"REVISION REQUIRED — previous plan had this issue:\n{revision_feedback}\n"
                f"Fix this specific issue in your new plan."
                if revision_feedback else act_base
            )

            if DEBUG:
                logger.debug(
                    "=== Nemotron PROMPT (attempt %d) ===\n%s\n=== END ===",
                    _attempt + 1, act_prompt,
                )

            try:
                candidate = chat_json_array(
                    act_prompt,
                    task="main",
                    max_tokens=NEMOTRON_MAX_TOKENS,
                    temperature=0.9,
                    system_prompt=system_prompt,
                )
            except Exception as _e:
                logger.error("ReAct Step 2 failed on attempt %d: %s", _attempt + 1, _e)
                if result is None:
                    raise
                break  # keep last good result

            if DEBUG:
                logger.debug(
                    "=== Nemotron RAW (attempt %d) ===\n%s\n=== END ===",
                    _attempt + 1, candidate,
                )

            result = candidate

            # Skip OBSERVE on the final allowed attempt — just use what we have
            if _attempt >= _MAX_REVISIONS:
                logger.info("ReAct: max revisions reached — using best plan")
                break

            # OBSERVE — Nemotron evaluates its own plan
            logger.info("ReAct Step 3: Nemotron evaluating plan...")
            openclaw.call_nemotron("ReAct Step 3: self-evaluation")

            plan_summary = "\n".join(
                f"Option {p.get('option', i + 1)}: genre={p.get('genre', '?')} | "
                f"drums={p.get('drum_pattern', '?')} | bass={p.get('bass_pattern', '?')} | "
                f"mood={p.get('mood', '?')} | chords={p.get('chord_progression', '?')}"
                for i, p in enumerate(candidate[:3])
            )
            observe_prompt = (
                f"Review this musical plan against the original track analysis.\n\n"
                f"ORIGINAL TRACK: Key: {key} | Tempo: {tempo} BPM | Energy: {energy:.2f} ({energy_label})\n\n"
                f"PROPOSED PLANS:\n{plan_summary}\n\n"
                f"Evaluate:\n"
                f"1. Do chord progressions stay in {key}?\n"
                f"2. Is energy level appropriate for energy={energy:.2f}?\n"
                f"3. Are the 3 options musically distinct (different genre + drum pattern)?\n\n"
                f"If the plan is good, respond with exactly: APPROVED\n"
                f"If there is an issue, respond with: REVISE: [one-sentence description of the specific problem]"
            )
            observe_system = (
                "You are a music theory expert reviewing AI-generated production plans. /no_think\n"
                "Respond with ONLY 'APPROVED' or 'REVISE: [issue]'. Nothing else."
            )

            try:
                evaluation = chat_completion(
                    observe_prompt,
                    task="fast",
                    max_tokens=80,
                    temperature=0.3,
                    system_prompt=observe_system,
                ).strip()
                logger.info("ReAct Step 3 evaluation: %s", evaluation[:100])
            except Exception as _e:
                logger.warning("ReAct Step 3 failed (%s) — accepting plan", _e)
                evaluation = "APPROVED"

            if evaluation.upper().startswith("APPROVED"):
                logger.info("ReAct approved plan after %d iteration(s)", _attempt + 1)
                break
            elif evaluation.upper().startswith("REVISE"):
                revision_feedback = (
                    evaluation[evaluation.index(":") + 1:].strip()
                    if ":" in evaluation else evaluation
                )
                logger.info("ReAct requesting revision: %s", revision_feedback)
                # loop continues to next attempt
            else:
                logger.warning("ReAct Step 3 unexpected response %r — accepting plan", evaluation)
                break

    # Tag plans with ReAct iteration count for result metadata
    for plan in result:
        plan["_react_iterations"] = react_iterations

    # Sanitize fields — runs for both STUB_MODE and live paths
    for plan in result:
        plan.setdefault("bars", 8)
        plan.setdefault("chord_progression", chords)
        if plan.get("drum_pattern") not in _DRUM_PATTERNS:
            plan["drum_pattern"] = "boom_bap"
        if plan.get("bass_pattern") not in _BASS_PATTERNS:
            plan["bass_pattern"] = "sub_root"
        if plan.get("lead_motif") not in _LEAD_MOTIFS:
            plan["lead_motif"] = "call_response"
        if plan.get("fx_type") not in _FX_TYPES:
            plan["fx_type"] = "none"
        plan["lead_density"]  = float(np.clip(plan.get("lead_density",  0.3), 0.0, 1.0))
        plan["pad_intensity"]  = float(np.clip(plan.get("pad_intensity",  0.5), 0.0, 1.0))
        plan["perc_intensity"] = float(np.clip(plan.get("perc_intensity", 0.3), 0.0, 1.0))

    # Uniqueness check: if 2+ options share identical (genre, drum_pattern), swap duplicates
    seen_pairs: dict[tuple, int] = {}
    for i, plan in enumerate(result):
        pair = (plan.get("genre", ""), plan.get("drum_pattern", ""))
        if pair in seen_pairs:
            used_genres = {p.get("genre", "") for j, p in enumerate(result) if j != i}
            swap = next(
                (s for s in _CONTRAST_SWAPS if s["genre"] not in used_genres),
                _CONTRAST_SWAPS[i % len(_CONTRAST_SWAPS)],
            )
            plan.update(swap)
            logger.info(
                "Uniqueness fix: option %d swapped to %s/%s",
                i + 1, swap["genre"], swap["drum_pattern"],
            )
        else:
            seen_pairs[pair] = i

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 2: DETERMINISTIC MIDI ENGINE — 6 track builders
# ═══════════════════════════════════════════════════════════════════════════════

def _build_drums(plan: dict, bars: int, tempo: float) -> pretty_midi.Instrument:
    """
    Drums (program=0, is_drum=True).
    Patterns: trap_triplet | boom_bap | four_on_floor | broken
    Strictly quantized to 16th-note grid.
    """
    drums = pretty_midi.Instrument(program=0, is_drum=True, name="Aux - Drums")
    spb  = 60.0 / tempo
    pattern  = plan.get("drum_pattern", "boom_bap")
    energy   = float(plan.get("_energy", 0.5))
    base_vel = int(65 + energy * 40)  # 65-105
    HIT = 0.04

    def hit(pitch: int, t: float, vo: int = 0) -> None:
        v = max(1, min(127, base_vel + vo))
        t = max(0.0, float(t))
        drums.notes.append(pretty_midi.Note(v, pitch, t, t + HIT))

    for bar in range(bars):
        b = bar * 4 * spb  # bar start

        if pattern == "trap_triplet":
            hit(KICK,      b,                  +5)
            hit(KICK,      b + 2.5 * spb,       -8)
            if energy > 0.5:
                hit(KICK,  b + 1.75 * spb,     -18)
            hit(SNARE,     b + 2 * spb,         +3)
            hit(CLAP,      b + 2 * spb,          -5)
            for beat in range(4):
                tb = b + beat * spb
                hit(CLOSED_HH, tb,               0)
                hit(CLOSED_HH, tb + spb / 3,   -20)
                hit(CLOSED_HH, tb + spb * 2/3, -15)

        elif pattern == "boom_bap":
            hit(KICK,  b,             +5)
            hit(KICK,  b + 2 * spb,  -3)
            hit(SNARE, b + spb,       +5)
            hit(SNARE, b + 3 * spb,  +2)
            for e in range(8):
                hit(CLOSED_HH, b + e * spb / 2, 0 if e % 2 == 0 else -15)

        elif pattern == "four_on_floor":
            for beat in range(4):
                hit(KICK, b + beat * spb, 0)
            hit(SNARE, b +     spb, +5)
            hit(SNARE, b + 3 * spb, +5)
            for e in range(8):
                if e % 2 == 1:
                    p = OPEN_HH if e % 4 == 3 else CLOSED_HH
                    hit(p, b + e * spb / 2, -10)

        elif pattern == "broken":
            hit(KICK,  b,                 +5)
            hit(KICK,  b + 1.5  * spb,   -10)
            hit(KICK,  b + 3.25 * spb,    -8)
            hit(SNARE, b + 3    * spb,    +5)
            for s in [0, 2, 5, 7]:
                hit(CLOSED_HH, b + s * spb / 4, -12)

        else:
            hit(KICK,  b,             0)
            hit(KICK,  b + 2 * spb, -3)
            hit(SNARE, b +     spb,  0)
            hit(SNARE, b + 3 * spb,  0)
            for e in range(8):
                hit(CLOSED_HH, b + e * spb / 2, -15)

    return drums


def _build_bass(
    plan: dict,
    chords: list,
    bars: int,
    tempo: float,
    key: str,
    scale_pcs: set,
) -> pretty_midi.Instrument:
    """
    Bass line (program=38, synth bass 1). Velocity 90-100.
    Patterns: sub_root | 808_glide | walking | syncopated
    Root notes always locked to scale.
    """
    bass = pretty_midi.Instrument(program=38, name="Aux - Bass")
    spb     = 60.0 / tempo
    pattern = plan.get("bass_pattern", "sub_root")

    def root_of(chord_name: str) -> int:
        cands = chord_to_pitches(chord_name, octave=2)
        r = next((p for p in cands if p % 12 in scale_pcs), cands[0])
        return int(np.clip(r, 28, 52))

    for bar in range(bars):
        chord_name = chords[bar % len(chords)]
        bs = bar * 4 * spb        # bar start
        be = (bar + 1) * 4 * spb  # bar end (exclusive — next bar's downbeat)
        root = root_of(chord_name)

        if pattern == "sub_root":
            # Whole note — ends just before next bar to loop cleanly
            bass.notes.append(pretty_midi.Note(95, root, bs, be - 0.03))

        elif pattern == "808_glide":
            # Long note on root — high velocity, slides into next bar slightly
            bass.notes.append(pretty_midi.Note(102, root, bs, be - 0.02))

        elif pattern == "walking":
            # Quarter notes walking up the scale from root
            scale_bass = sorted(p for p in range(28, 53) if p % 12 in scale_pcs)
            ri = min(range(len(scale_bass)), key=lambda i: abs(scale_bass[i] - root))
            for beat in range(4):
                t = bs + beat * spb
                p = scale_bass[(ri + beat) % len(scale_bass)]
                v = 95 if beat == 0 else 82
                bass.notes.append(pretty_midi.Note(v, p, t, t + spb * 0.85))

        elif pattern == "syncopated":
            # Beat 1, "and of 2" (1.5 beats in), beat 4
            for beat_off in [0.0, 1.5, 3.0]:
                t = bs + beat_off * spb
                if t >= be - 0.02:
                    continue
                bass.notes.append(pretty_midi.Note(93, root, t, t + spb * 0.4))

        else:
            bass.notes.append(pretty_midi.Note(90, root, bs, be - 0.03))

    return bass


def _build_chords(
    plan: dict,
    chords: list,
    bars: int,
    tempo: float,
    scale_pcs: set,
) -> pretty_midi.Instrument:
    """
    Chords/pads (program=89, new age pad). Root+3rd+5th+octave voicing.
    Velocity 50-70 — sits behind lead.
    """
    pad = pretty_midi.Instrument(program=89, name="Aux - Chords")
    spb           = 60.0 / tempo
    pad_intensity = float(plan.get("pad_intensity", 0.6))
    base_vel      = int(50 + pad_intensity * 20)  # 50-70

    for bar in range(bars):
        chord_name = chords[bar % len(chords)]
        bs = bar * 4 * spb
        be = (bar + 1) * 4 * spb

        # Root+3rd+5th in octave 3 plus root an octave higher
        pitches = chord_to_pitches(chord_name, octave=3)
        all_pitches = pitches + [pitches[0] + 12]  # add root octave up

        for pitch in all_pitches:
            if pitch % 12 in scale_pcs and 0 <= pitch <= 127:
                v = max(1, min(127, base_vel + int(np.random.randint(-4, 4))))
                pad.notes.append(pretty_midi.Note(v, pitch, bs, be - 0.04))

    return pad


def _build_lead(
    plan: dict,
    chords: list,
    bars: int,
    tempo: float,
    key: str,
    scale_pcs: set,
) -> pretty_midi.Instrument:
    """
    Lead melody (program=81, lead synth saw). Velocity 75-90.
    Sparse memorable phrases shaped by lead_motif. All notes in scale.
    Motifs: ascending | descending | call_response | static
    """
    lead      = pretty_midi.Instrument(program=81, name="Aux - Lead")
    spb       = 60.0 / tempo
    density   = float(plan.get("lead_density", 0.3))
    motif     = plan.get("lead_motif", "call_response")
    total_dur = bars * 4 * spb
    s16       = spb / 4  # 16th note duration

    if density < 0.05:
        return lead

    # Ascending scale in octave 4-5 range (MIDI 60-84)
    scale_notes = _scale_ascending(key, 60, 84)
    if not scale_notes:
        return lead

    root_pc, _ = parse_key(key)
    root_note  = next((p for p in scale_notes if p % 12 == root_pc), scale_notes[0])
    root_idx   = scale_notes.index(root_note)

    # Notes per 2-bar phrase
    notes_per_phrase = max(2, int(density * 16))
    phrase_dur       = 2 * 4 * spb  # 2 bars

    def ascending_phrase(start_idx: int, n: int) -> list:
        return [scale_notes[min(start_idx + i, len(scale_notes) - 1)] for i in range(n)]

    def descending_phrase(start_idx: int, n: int) -> list:
        return [scale_notes[max(start_idx - i, 0)] for i in range(n)]

    t          = 0.0
    phrase_idx = 0

    while t < total_dur - s16:
        p_end = min(t + phrase_dur, total_dur)
        p_dur = p_end - t
        spacing  = p_dur / notes_per_phrase
        note_dur = spacing * 0.72  # slight staccato

        if motif == "ascending":
            phrase = ascending_phrase(root_idx, notes_per_phrase)

        elif motif == "descending":
            top = min(root_idx + 6, len(scale_notes) - 1)
            phrase = descending_phrase(top, notes_per_phrase)

        elif motif == "call_response":
            if phrase_idx % 2 == 0:
                phrase = ascending_phrase(root_idx, notes_per_phrase)
            else:
                phrase = descending_phrase(
                    min(root_idx + 3, len(scale_notes) - 1),
                    notes_per_phrase,
                )

        elif motif == "static":
            # Hit chord tones on the current chord
            bar_now    = int(t / (4 * spb))
            chord_name = chords[bar_now % len(chords)]
            tones      = [p for p in chord_to_pitches(chord_name, octave=4)
                          if p % 12 in scale_pcs and 0 <= p <= 127]
            if not tones:
                tones = [root_note]
            phrase = [tones[i % len(tones)] for i in range(notes_per_phrase)]

        else:
            phrase = ascending_phrase(root_idx, notes_per_phrase)

        for i, pitch in enumerate(phrase):
            note_t = t + i * spacing
            if note_t >= total_dur - s16:
                break
            v     = int(np.clip(82 + int(np.random.randint(-7, 7)), 75, 90))
            end_t = min(note_t + note_dur - 0.02, total_dur - 0.02)
            lead.notes.append(pretty_midi.Note(v, pitch, note_t, end_t))

        t          = p_end
        phrase_idx += 1

    return lead


def _build_percs(plan: dict, bars: int, tempo: float) -> pretty_midi.Instrument:
    """
    Percussion layer (program=0, is_drum=True).
    Shakers on 8ths, claps on 2+4, rim shots as accents.
    perc_intensity < 0.1 returns empty instrument.
    """
    percs     = pretty_midi.Instrument(program=0, is_drum=True, name="Aux - Percs")
    intensity = float(plan.get("perc_intensity", 0.3))

    if intensity < 0.1:
        return percs

    spb      = 60.0 / tempo
    base_vel = int(45 + intensity * 40)  # 45-85
    HIT      = 0.03

    def hit(pitch: int, t: float, vo: int = 0) -> None:
        v = max(1, min(127, base_vel + vo))
        t = max(0.0, float(t))
        percs.notes.append(pretty_midi.Note(v, pitch, t, t + HIT))

    for bar in range(bars):
        b = bar * 4 * spb

        # Claps on beats 2 and 4 (always when intensity >= 0.1)
        hit(CLAP, b + spb,     +8)
        hit(CLAP, b + 3 * spb, +8)

        # Shakers on 8th notes
        if intensity >= 0.3:
            for e in range(8):
                hit(SHAKER, b + e * spb / 2, 0 if e % 2 == 0 else -18)

        # Rim shot accents on select 16th positions (sparse)
        if intensity >= 0.55:
            for s in [1, 5, 9, 13]:
                if np.random.random() > 0.55:
                    hit(RIM, b + s * spb / 4, -12)

    return percs


def _build_fx(
    plan: dict,
    bars: int,
    tempo: float,
    key: str,
    scale_pcs: set,
) -> pretty_midi.Instrument:
    """
    FX layer (program=88, new age / program=95 sweep).
    Types: riser | atmospheric_pad | noise_sweep | none
    """
    fx_type   = plan.get("fx_type", "none")
    fx        = pretty_midi.Instrument(program=88, name="Aux - FX")
    spb       = 60.0 / tempo
    total_dur = bars * 4 * spb

    if fx_type == "none":
        return fx

    root_pc, _ = parse_key(key)

    if fx_type == "riser":
        # Rising scale notes, one per bar, crescendo in velocity
        scale_low = _scale_ascending(key, 36, 72)
        if scale_low:
            step = max(1, len(scale_low) // bars)
            for bar in range(bars):
                p = scale_low[min(bar * step, len(scale_low) - 1)]
                bs = bar * 4 * spb
                be = min((bar + 1) * 4 * spb, total_dur - 0.02)
                v  = int(35 + (bar / max(bars - 1, 1)) * 65)  # 35→100
                fx.notes.append(pretty_midi.Note(v, p, bs, be))

    elif fx_type == "atmospheric_pad":
        # Very soft sustained root + fifth
        root  = next((p for p in range(36, 60) if p % 12 == root_pc), 48)
        fifth = next((p for p in range(36, 60) if p % 12 == (root_pc + 7) % 12), root + 7)
        for pitch, vel in [(root, 30), (fifth, 25)]:
            if 0 <= pitch <= 127:
                fx.notes.append(pretty_midi.Note(vel, pitch, 0.0, total_dur - 0.02))

    elif fx_type == "noise_sweep":
        # Ascending notes every 2 bars to simulate a sweep build
        scale_low = _scale_ascending(key, 36, 72)
        n = min(bars // 2, len(scale_low))
        for i in range(n):
            p  = scale_low[int(i * len(scale_low) / max(n, 1))]
            bs = i * 2 * 4 * spb
            be = min((i + 1) * 2 * 4 * spb, total_dur - 0.02)
            v  = int(25 + (i / max(n - 1, 1)) * 55)
            if bs < total_dur:
                fx.notes.append(pretty_midi.Note(v, p, bs, be))

    return fx


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 3: LOOP RENDERER — assemble all tracks into one MIDI
# ═══════════════════════════════════════════════════════════════════════════════

def _render_producer_loop(
    plan: dict,
    analysis: dict,
    output_path: str,
    tempo: float,
    original_midi_path: str = None,
) -> None:
    """
    Render a full 6-track producer loop from a Nemotron plan dict.
    Tracks: Aux - Drums | Aux - Bass | Aux - Chords | Aux - Lead | Aux - Percs | Aux - FX
    Optionally prepends original MIDI tracks so the producer hears both together.
    """
    key    = plan.get("chord_progression") and analysis.get("key", "A minor") or analysis.get("key", "A minor")
    key    = analysis.get("key", "A minor")
    chords = plan.get("chord_progression") or analysis.get("chord_progression") or diatonic_progression(key)
    while len(chords) < 4:
        chords = chords + chords
    chords = chords[:4]

    bars       = int(plan.get("bars", 8))
    scale_pcs  = set(scale_pitch_classes(key))
    energy     = float(analysis.get("energy", 0.5))

    # Inject energy so drum builder can scale velocities
    p = dict(plan)
    p["_energy"] = energy

    # Build all 6 tracks
    drums  = _build_drums(p, bars, tempo)
    bass   = _build_bass(p, chords, bars, tempo, key, scale_pcs)
    chords_track = _build_chords(p, chords, bars, tempo, scale_pcs)
    lead   = _build_lead(p, chords, bars, tempo, key, scale_pcs)
    percs  = _build_percs(p, bars, tempo)
    fx     = _build_fx(p, bars, tempo, key, scale_pcs)

    midi = pretty_midi.PrettyMIDI(initial_tempo=tempo)

    # Prepend original tracks so FL sees original + AI together
    if original_midi_path:
        try:
            orig = pretty_midi.PrettyMIDI(original_midi_path)
            for inst in orig.instruments:
                midi.instruments.append(inst)
            logger.info(f"Prepended {len(orig.instruments)} original tracks")
        except Exception as e:
            logger.warning(f"Could not load original MIDI: {e}")

    # Add AI tracks (skip empty)
    for track in [drums, bass, chords_track, lead, percs, fx]:
        if track.notes:
            midi.instruments.append(track)

    openclaw.log_midi_write(output_path)
    midi.write(output_path)
    ai_names = [t.name for t in [drums, bass, chords_track, lead, percs, fx] if t.notes]
    logger.info(
        f"Loop rendered: {key} @ {tempo} BPM, {bars} bars, chords={chords}\n"
        f"  Tracks: {', '.join(ai_names)} → {output_path}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# LEGACY API — kept for composer.py and other callers
# ═══════════════════════════════════════════════════════════════════════════════

def _infer_drum_style(text: str) -> str:
    t = text.lower()
    if "trap" in t:
        return "trap"
    if "house" in t:
        return "house"
    if "lo-fi" in t or "lofi" in t:
        return "lo-fi"
    return "default"


def generate_drum_track(tempo: float, energy: float, style: str) -> pretty_midi.Instrument:
    """
    Generate a 4-bar MIDI drum pattern. Legacy function used by composer.py.
    style: "trap" | "house" | "lo-fi" | "default"
    """
    pattern_map = {
        "trap": "trap_triplet",
        "lo-fi": "boom_bap",
        "house": "four_on_floor",
        "default": "boom_bap",
    }
    plan = {"drum_pattern": pattern_map.get(style, "boom_bap"), "_energy": energy}
    inst = _build_drums(plan, bars=4, tempo=tempo)
    inst.name = "Drums"
    return inst


def generate_midi_from_params(params: dict, output_path: str, tempo: float) -> None:
    """
    Generate MIDI from old-format params dict. Legacy function used by composer.py.
    Validates all notes against key scale.
    """
    key       = params.get("key", "C major")
    chords    = params.get("chord_progression", ["C", "Am", "F", "G"])
    energy    = params.get("energy_direction", "maintain")
    scale_pcs = set(scale_pitch_classes(key))

    while len(chords) < 4:
        chords = chords + chords
    chords = chords[:4]

    # Build a minimal plan and render
    plan = {
        "drum_pattern": "boom_bap",
        "bass_pattern": "sub_root",
        "lead_density": 0.4 if energy != "drop" else 0.2,
        "lead_motif": "ascending" if energy == "build" else "call_response",
        "pad_intensity": 0.55,
        "perc_intensity": 0.3,
        "fx_type": "none",
        "chord_progression": chords,
        "bars": 8,
        "_energy": 0.6,
    }
    fake_analysis = {
        "key": key, "tempo": tempo, "chord_progression": chords,
        "source_type": "vibe", "energy": 0.6,
    }
    _render_producer_loop(plan, fake_analysis, output_path, tempo)


def generate_matched_continuation(
    params: dict,
    analysis: dict,
    output_path: str,
    tempo: float,
    original_midi_path: str = None,
) -> None:
    """
    Build a continuation MIDI from old-format params. Legacy function used by composer.py.
    Converts old params to new plan format, then renders via _render_producer_loop.
    """
    key    = params.get("key") or analysis.get("key", "A minor")
    chords = params.get("chord_progression") or analysis.get("chord_progression")
    if not chords:
        chords = diatonic_progression(key)
    while len(chords) < 4:
        chords = chords + chords
    chords = chords[:4]

    energy_dir  = params.get("energy_direction", "maintain")
    energy_val  = float(analysis.get("energy", 0.5))
    role        = params.get("role", "melody")

    # Map old "role" to patterns
    role_to_bass = {"bass": "sub_root", "harmony": "sub_root", "melody": "walking"}
    role_to_lead = {"melody": "call_response", "bass": "static", "harmony": "ascending"}

    plan = {
        "drum_pattern": "trap_triplet" if energy_val > 0.6 else "boom_bap",
        "bass_pattern": role_to_bass.get(role, "sub_root"),
        "lead_density": max(0.2, energy_val * 0.7),
        "lead_motif":   role_to_lead.get(role, "call_response"),
        "pad_intensity": 0.55,
        "perc_intensity": 0.3 if energy_val > 0.4 else 0.1,
        "fx_type": "none",
        "chord_progression": chords,
        "bars": 8,
        "_energy": energy_val,
    }
    _render_producer_loop(plan, analysis, output_path, tempo, original_midi_path)


# ═══════════════════════════════════════════════════════════════════════════════
# LOCAL QWEN REFINEMENT — validates + corrects Nemotron's musical plan
# ═══════════════════════════════════════════════════════════════════════════════

_LOCAL_MODEL_URL = os.getenv("LOCAL_MODEL_URL", "").rstrip("/")
_LOCAL_MODEL_TIMEOUT = int(os.getenv("LOCAL_MODEL_TIMEOUT", "30"))


def refine_with_local_model(nemotron_plans: list, analysis: dict) -> list:
    """
    Pass Nemotron's plan list to a local Qwen instance for validation/correction.

    Qwen checks:
    - chord_progression valid in detected key
    - energy / genre consistency with track analysis
    - pattern field values within allowed enums

    Returns corrected plan list. If LOCAL_MODEL_URL unset or unreachable,
    returns nemotron_plans unchanged (graceful degradation).
    """
    if not _LOCAL_MODEL_URL:
        logger.debug("LOCAL_MODEL_URL not set — skipping local refinement")
        return nemotron_plans

    import requests as _req

    key    = analysis.get("key", "A minor")
    energy = float(analysis.get("energy", 0.5))
    tempo  = float(analysis.get("tempo", 120))

    system_prompt = (
        "You are a music theory validator for a producer AI. "
        "You receive a JSON array of musical loop plans and an analysis of the input track. "
        "Your job: check each plan for correctness and return the fixed JSON array. "
        "Fix any chord_progression chords that are outside the detected key. "
        "Fix any pattern field values that are not in the allowed enum. "
        "Adjust genre/mood if clearly inconsistent with the energy level. "
        "Do NOT change bars, lead_density, pad_intensity, perc_intensity — only correct wrong values. "
        "Return ONLY the corrected JSON array. No explanation, no markdown fences."
    )

    user_msg = f"""\
TRACK ANALYSIS:
- Key: {key}
- Tempo: {tempo} BPM
- Energy: {energy:.2f} (0=quiet, 1=loud)

ALLOWED ENUM VALUES:
- drum_pattern:  trap_triplet | boom_bap | four_on_floor | broken
- bass_pattern:  sub_root | 808_glide | walking | syncopated
- lead_motif:    ascending | descending | call_response | static
- fx_type:       riser | atmospheric_pad | noise_sweep | none

PLANS TO VALIDATE:
{json.dumps(nemotron_plans, indent=2)}

Return the corrected JSON array only."""

    payload = {
        "model": os.getenv("LOCAL_MODEL_NAME", "qwen"),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_msg},
        ],
        "max_tokens": 1200,
        "temperature": 0.2,
    }

    try:
        logger.info("Local Qwen: validating and refining Nemotron plan...")
        resp = _req.post(
            f"{_LOCAL_MODEL_URL}/v1/chat/completions",
            json=payload,
            timeout=_LOCAL_MODEL_TIMEOUT,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        raw = raw.strip("```json").strip("```").strip()

        if DEBUG:
            logger.debug("=== Local Qwen RAW ===\n%s\n=== END ===", raw)

        refined = json.loads(raw)
        if not isinstance(refined, list):
            raise ValueError("Local model returned non-list JSON")

        # Re-apply sanitization in case Qwen introduced bad values
        for plan in refined:
            plan.setdefault("bars", 8)
            if plan.get("drum_pattern")  not in _DRUM_PATTERNS:  plan["drum_pattern"]  = "boom_bap"
            if plan.get("bass_pattern")  not in _BASS_PATTERNS:  plan["bass_pattern"]  = "sub_root"
            if plan.get("lead_motif")    not in _LEAD_MOTIFS:    plan["lead_motif"]    = "call_response"
            if plan.get("fx_type")       not in _FX_TYPES:       plan["fx_type"]       = "none"
            plan["lead_density"]  = float(np.clip(plan.get("lead_density",  0.3), 0.0, 1.0))
            plan["pad_intensity"]  = float(np.clip(plan.get("pad_intensity",  0.5), 0.0, 1.0))
            plan["perc_intensity"] = float(np.clip(plan.get("perc_intensity", 0.3), 0.0, 1.0))

        logger.info("Local Qwen: plan validated and refined ✓")
        return refined

    except Exception as e:
        logger.warning(f"Local Qwen refinement failed ({e}) — using Nemotron plan unchanged")
        return nemotron_plans


# ═══════════════════════════════════════════════════════════════════════════════
# SUGGEST MODE — plain-text suggestions, no MIDI
# ═══════════════════════════════════════════════════════════════════════════════

def _suggest_with_nemotron(analysis: dict, artist_prompt: str = None) -> str:
    if STUB_MODE:
        return (
            "1. Add a sub bass on beats 1 and 3\n"
            "2. Bring in hi-hats on the upbeats\n"
            "3. Try a Rhodes piano for the chords"
        )
    context = f'\nArtist direction: "{artist_prompt}"' if artist_prompt else ""
    ctx     = _format_analysis_context(analysis)
    prompt  = f"""You are an expert music producer giving creative direction.

Analysis:
{ctx}{context}

Give 3 specific, actionable ideas for where this track could go next.
Plain text, numbered list, one sentence per idea. No JSON."""

    from agent.nemotron_client import chat_completion
    return chat_completion(
        prompt, task="fast", max_tokens=300, temperature=NEMOTRON_TEMPERATURE
    )


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN PIPELINE
# ═══════════════════════════════════════════════════════════════════════════════

def generate_continuations(
    analysis: dict,
    output_dir: str,
    prompt: str = None,
    mode: str = "full",
    original_midi_path: str = None,
) -> Union[list, str]:
    """
    mode='full'    → Nemotron musical decisions + 6-track MIDI rendering.
                     Returns list of result dicts with filepath, description, vibe etc.
    mode='suggest' → Nemotron plain-text suggestions only. Returns a string.

    original_midi_path: when provided, original MIDI tracks are prepended to
    each output file so the producer hears their loop + the AI complement.
    """
    if mode == "suggest":
        try:
            return _suggest_with_nemotron(analysis, artist_prompt=prompt)
        except Exception as e:
            logger.error(f"Nemotron suggest failed: {e}")
            return "Could not reach Nemotron — check API key and model name."

    # ── mode == "full" ────────────────────────────────────────────────────────
    Path(output_dir).mkdir(exist_ok=True)

    song_key    = analysis.get("key", "A minor")
    song_tempo  = float(analysis.get("tempo", 120))
    song_chords = analysis.get("chord_progression") or diatonic_progression(song_key)

    try:
        logger.info("Nemotron: generating musical plan...")
        plans = reason_with_nemotron(analysis, artist_prompt=prompt)
        logger.info("Nemotron: musical plan generated ✓")
    except Exception as e:
        logger.error(f"Nemotron failed, using fallback plans: {e}")
        plans = _fallback_plans(analysis, prompt)

    # Two-model pipeline: local Qwen validates + refines Nemotron's output
    openclaw.call_local_model("Qwen plan validation")
    plans = refine_with_local_model(plans, analysis)

    results = []
    for i, plan in enumerate(plans[:3]):
        option_n = plan.get("option", i + 1)
        filename = f"continuation_{option_n}.mid"
        filepath = str(Path(output_dir) / filename)

        try:
            # Lock key/tempo/chords to analyzed values
            plan = dict(plan)
            plan.setdefault("chord_progression", song_chords)
            plan["bars"] = int(plan.get("bars", 8))

            logger.info(
                f"Engine: rendering 6-track loop — option {option_n} "
                f"[{plan.get('genre','?')}|{plan.get('drum_pattern','?')}|"
                f"{plan.get('bass_pattern','?')}]"
            )
            _render_producer_loop(plan, analysis, filepath, song_tempo, original_midi_path)

            results.append({
                "option":           option_n,
                "filename":         filename,
                "filepath":         filepath,
                "description":      plan.get("description", ""),
                "vibe":             plan.get("vibe", ""),
                "genre":            plan.get("genre", ""),
                "mood":             plan.get("mood", ""),
                "key":              song_key,
                "tempo":            song_tempo,
                "chord_progression": plan.get("chord_progression", song_chords),
                "drum_pattern":     plan.get("drum_pattern", ""),
                "bass_pattern":     plan.get("bass_pattern", ""),
                "react_iterations": plan.get("_react_iterations", 1),
            })
        except Exception as e:
            logger.error(f"Loop render failed for option {option_n}: {e}", exc_info=True)

    return results
