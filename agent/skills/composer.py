"""
Composer — plain-English vibe → Nemotron → 3 distinct MIDI compositions.
"""

import os
import logging
from pathlib import Path

import pretty_midi

from agent.config import NEMOTRON_MAX_TOKENS, NEMOTRON_TEMPERATURE
from agent.nemotron_client import chat_json_array
from agent.skills.continuation_gen import (
    generate_midi_from_params,
    generate_drum_track,
    _infer_drum_style,
)

logger = logging.getLogger(__name__)

STUB_MODE = os.getenv("STUB_MODE", "false").lower() == "true"


def _heuristic_vibe_options(vibe: str) -> list[dict]:
    """Keyword-based fallbacks when Nemotron is unavailable."""
    t = vibe.lower()
    if "dark" in t or "trap" in t:
        key, chords, tempo = "D minor", ["Dm", "Gm", "Bb", "F"], 140
        vibes = ["dark trap", "heavy 808s", "minimal noir"]
        energies = ["maintain", "build", "drop"]
    elif "lo-fi" in t or "lofi" in t or "lo fi" in t:
        key, chords, tempo = "F minor", ["Fm", "Ab", "Eb", "Bb"], 82
        vibes = ["rainy lo-fi", "dusty keys", "late night"]
        energies = ["maintain", "build", "drop"]
    elif "house" in t or "dance" in t:
        key, chords, tempo = "A minor", ["Am", "F", "C", "G"], 124
        vibes = ["driving house", "club groove", "filter break"]
        energies = ["build", "maintain", "drop"]
    else:
        key, chords, tempo = "A minor", ["Am", "F", "C", "G"], 90
        vibes = ["melodic lead", "steady pocket", "sparse breakdown"]
        energies = ["build", "maintain", "drop"]

    root = key.split()[0]
    notes = [f"{root}3", f"{root}4"]
    if "m" in key.lower():
        notes.extend(["C4", "E4"] if root != "C" else ["Eb4", "G4"])
    else:
        notes.extend(["C4", "E4", "G4"])

    return [
        {
            "option": i,
            "vibe_label": vibes[i - 1],
            "description": f"{vibes[i - 1]} — {vibe[:80]}",
            "key": key,
            "tempo": tempo,
            "chord_progression": chords,
            "suggested_notes": notes,
            "instruments_to_add": ["bass"],
            "energy_direction": energies[i - 1],
            "arrangement_note": f"variation {i}",
        }
        for i in range(1, 4)
    ]


def _stub_vibe_options(vibe: str) -> list[dict]:
    return _heuristic_vibe_options(vibe)


def _vibe_to_options(vibe: str) -> list[dict]:
    """Ask Nemotron for 3 distinct interpretations of the same vibe text."""
    if STUB_MODE:
        logger.info("STUB_MODE: using stub vibe options")
        return _stub_vibe_options(vibe)

    prompt = f"""You are a world-class music producer and composer.

A producer wants THREE different original 8-bar sketches inspired by this vibe:
"{vibe}"

Each option must sound noticeably different (harmony, energy, or rhythm), while matching the vibe.

Respond ONLY with a valid JSON array of exactly 3 objects, no markdown:
[
  {{
    "option": 1,
    "vibe_label": "2-4 word label",
    "description": "one sentence",
    "key": "e.g. D minor",
    "tempo": 140,
    "chord_progression": ["Dm", "Bb", "F", "C"],
    "suggested_notes": ["D3", "F3", "A3", "C4"],
    "instruments_to_add": ["bass"],
    "energy_direction": "build",
    "arrangement_note": "what makes this unique"
  }}
]"""

    try:
        logger.info("Asking Nemotron for 3 vibe variations...")
        options = chat_json_array(
            prompt,
            task="main",
            max_tokens=NEMOTRON_MAX_TOKENS,
            temperature=NEMOTRON_TEMPERATURE,
        )
        return options[:3]
    except Exception as e:
        logger.error(f"Nemotron vibe translation failed: {e}")
        return _heuristic_vibe_options(vibe)


def compose_from_vibe(vibe_description: str, output_dir: str) -> list:
    """
    Full composition pipeline from a plain English vibe.
    Returns list of dicts with filepath, description, musical params.
    """
    logger.info(f"Composing from vibe: '{vibe_description}'")

    options = _vibe_to_options(vibe_description)
    drum_style = _infer_drum_style(vibe_description)
    Path(output_dir).mkdir(exist_ok=True)
    results = []

    for opt in options[:3]:
        i = int(opt.get("option", len(results) + 1))
        filename = f"composition_v{i}.mid"
        filepath = str(Path(output_dir) / filename)
        tempo = float(opt.get("tempo", 90))

        try:
            opt["role"] = {1: "melody", 2: "bass", 3: "harmony"}.get(i, "melody")
            fake_analysis = {
                "key": opt.get("key", "A minor"),
                "tempo": tempo,
                "chord_progression": opt.get("chord_progression", []),
                "source_type": "vibe",
                "energy": 0.65,
            }
            from agent.skills.continuation_gen import generate_matched_continuation
            generate_matched_continuation(opt, fake_analysis, filepath, tempo)
            drum_track = generate_drum_track(
                tempo=tempo,
                energy=0.7 if opt.get("energy_direction") != "drop" else 0.4,
                style=drum_style,
            )
            midi_with_drums = pretty_midi.PrettyMIDI(filepath)
            midi_with_drums.instruments.append(drum_track)
            midi_with_drums.write(filepath)

            results.append({
                "option": i,
                "variation": i,
                "filename": filename,
                "filepath": filepath,
                "description": opt.get("description", vibe_description),
                "vibe": opt.get("vibe_label", opt.get("vibe", "")),
                "key": opt.get("key", ""),
                "tempo": tempo,
                "chord_progression": opt.get("chord_progression", []),
                "energy_direction": opt.get("energy_direction", "maintain"),
            })
        except Exception as e:
            logger.error(f"Composition variation {i} failed: {e}")

    return results
