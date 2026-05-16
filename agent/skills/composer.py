"""
Composer — takes a plain English vibe description,
asks Nemotron to translate it into musical parameters,
then generates 3 original MIDI tracks.
"""

import os
import json
import logging
import requests
from pathlib import Path

from agent.config import (
    NVIDIA_API_KEY, NVIDIA_BASE_URL, NEMOTRON_MODEL,
    NEMOTRON_TIMEOUT, NEMOTRON_TEMPERATURE
)
from agent.skills.continuation_gen import generate_midi_from_params

logger = logging.getLogger(__name__)


def compose_from_vibe(vibe_description: str, output_dir: str) -> list:
    """
    Full composition pipeline from a plain English vibe.

    Example:
        compose_from_vibe("dark rainy 3am Tokyo lo-fi 85 BPM", "./output")

    Returns list of dicts with filepath, description, musical params.
    """
    logger.info(f"Composing from vibe: '{vibe_description}'")

    # step 1: Nemotron translates vibe into musical parameters
    params = _vibe_to_params(vibe_description)
    logger.info(f"Nemotron params: {params}")

    # step 2: generate 3 variations with different energy directions
    Path(output_dir).mkdir(exist_ok=True)
    results = []
    energy_directions = ["maintain", "build", "drop"]

    for i, energy in enumerate(energy_directions, 1):
        filename = f"composition_v{i}.mid"
        filepath = str(Path(output_dir) / filename)

        variation = {**params, "energy_direction": energy, "option": i}

        try:
            generate_midi_from_params(variation, filepath, float(params.get("tempo", 90)))
            results.append({
                "variation": i,
                "filename": filename,
                "filepath": filepath,
                "description": params.get("description", vibe_description),
                "vibe": params.get("vibe_label", ""),
                "key": params.get("key", ""),
                "tempo": params.get("tempo", 90),
                "mood": params.get("mood", ""),
                "chord_progression": params.get("chord_progression", []),
                "energy_direction": energy,
                "reference_artists": params.get("reference_artists", []),
                "production_style": params.get("production_style", ""),
            })
        except Exception as e:
            logger.error(f"Composition variation {i} failed: {e}")

    return results


def _vibe_to_params(vibe: str) -> dict:
    """
    Ask Nemotron to translate a human vibe description
    into precise musical parameters.
    """
    prompt = f"""You are a world-class music producer and composer.

A producer wants to create an original track with this vibe:
"{vibe}"

Translate this into precise musical composition parameters.

Respond ONLY with valid JSON, no markdown, no extra text:
{{
  "vibe_label": "3-word label e.g. 'dark lo-fi'",
  "description": "one sentence describing the sound",
  "mood": "emotional quality e.g. melancholic",
  "key": "e.g. D minor",
  "tempo": 85,
  "time_signature": "4/4",
  "chord_progression": ["Dm", "Bb", "F", "C"],
  "suggested_notes": ["D3", "F3", "A3", "C4", "D4"],
  "instruments": ["Rhodes piano", "bass", "lo-fi drums"],
  "instruments_to_add": ["bass", "strings"],
  "energy_direction": "maintain",
  "arrangement_note": "sparse intro, melody enters bar 5",
  "reference_artists": ["Nujabes", "J Dilla"],
  "production_style": "lo-fi hip hop"
}}"""

    headers = {
        "Authorization": f"Bearer {NVIDIA_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": NEMOTRON_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 600,
        "temperature": NEMOTRON_TEMPERATURE,
    }

    try:
        logger.info("Asking Nemotron to translate vibe...")
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

    except Exception as e:
        logger.error(f"Nemotron vibe translation failed: {e}")
        # sensible fallback so the pipeline doesn't break
        return {
            "vibe_label": "custom vibe",
            "description": vibe,
            "mood": "expressive",
            "key": "A minor",
            "tempo": 90,
            "chord_progression": ["Am", "F", "C", "G"],
            "suggested_notes": ["A3", "C4", "E4", "G4"],
            "instruments_to_add": ["bass"],
            "energy_direction": "maintain",
            "arrangement_note": "full arrangement",
            "reference_artists": [],
            "production_style": "original",
        }
