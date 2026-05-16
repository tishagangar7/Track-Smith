"""
Client for the DGX audio server (agent/audio_server.py).
Raises AudioServerOfflineError on connection failure so callers can fall back to MIDI.
"""
import io
import logging
import zipfile
from pathlib import Path

import httpx

from agent.config import AUDIO_DURATION, AUDIO_SERVER_URL

logger = logging.getLogger(__name__)


class AudioServerOfflineError(Exception):
    pass


# Keyword → producer-grade descriptor. Checked in order; multiple can match.
_STYLE_MAP: list[tuple[set[str], str]] = [
    ({"trap", "drill"},         "trap drums, 808 sub bass, triplet hi-hats"),
    ({"808"},                   "heavy 808 sub bass, trap drums"),
    ({"lo-fi", "lofi", "lo fi"}, "lo-fi hip hop, jazzy piano, dusty drums, vinyl warmth"),
    ({"dark"},                  "dark, moody, minor key atmosphere"),
    ({"drake", "melodic"},      "melodic, emotional, atmospheric pads, vocal chops"),
    ({"jazz", "jazzy"},         "jazz piano, walking bass, brushed drums"),
    ({"house", "dance"},        "four-on-the-floor kick, punchy synth bass, dance music"),
    ({"ambient", "atmospheric"}, "ambient textural pads, reverb wash, slow attack"),
    ({"r&b", "rnb", "soul"},    "R&B, soulful smooth chords, vocal chops"),
    ({"rage", "pluggnb"},       "pluggnb, icy bells, heavy bass, Atlanta"),
    ({"boom bap", "boom-bap"},  "boom bap, sampled drums, punchy snare, NYC hip hop"),
]

_ENERGY_DESCRIPTORS = {
    "high":  "hard-hitting, high energy",
    "mid":   "mid-tempo, groovy",
    "low":   "mellow, soft, introspective",
}


def build_musicgen_prompt(analysis: dict, prompt: str | None = None) -> str:
    key = analysis.get("key", "C major")
    tempo = int(analysis.get("tempo") or 120)
    energy = analysis.get("energy", 0.5)

    # Energy tier
    if energy > 0.7:
        energy_desc = _ENERGY_DESCRIPTORS["high"]
    elif energy < 0.3:
        energy_desc = _ENERGY_DESCRIPTORS["low"]
    else:
        energy_desc = _ENERGY_DESCRIPTORS["mid"]

    # Match style keywords against prompt (case-insensitive)
    raw = (prompt or "").lower()
    genre_tags: list[str] = []
    for keywords, descriptor in _STYLE_MAP:
        if any(kw in raw for kw in keywords):
            genre_tags.append(descriptor)

    parts: list[str] = []

    if genre_tags:
        parts.extend(genre_tags)
        parts.append(energy_desc)
    else:
        # No keywords — lead with energy + generic beat descriptor
        parts.append(f"{energy_desc} beat")

    parts.append(key)
    parts.append(f"{tempo} BPM")

    # Append any free-text from the user verbatim at the end
    if prompt:
        parts.append(prompt)

    return ", ".join(parts)


_AUDIO_EXTS = {".wav", ".mp3", ".aiff", ".flac", ".ogg", ".m4a"}


def generate_audio_continuation(
    analysis: dict,
    output_path: str,
    prompt: str | None = None,
    duration: int | None = None,
    original_audio_path: str | None = None,
) -> str:
    if not AUDIO_SERVER_URL:
        raise AudioServerOfflineError("AUDIO_SERVER_URL not configured")

    mg_prompt = build_musicgen_prompt(analysis, prompt)
    dur = duration if duration is not None else AUDIO_DURATION

    body: dict = {"prompt": mg_prompt, "duration": dur}

    # Melody conditioning: encode reference audio as base64 if it's an audio file
    ref_path = Path(original_audio_path) if original_audio_path else None
    if ref_path and ref_path.exists() and ref_path.suffix.lower() in _AUDIO_EXTS:
        import base64
        body["reference_audio_b64"] = base64.b64encode(ref_path.read_bytes()).decode()
        logger.info("[MusicGen] melody conditioning from %s  prompt=%r  duration=%ds",
                    ref_path.name, mg_prompt, dur)
    else:
        logger.info("[MusicGen] text-only  prompt=%r  duration=%ds", mg_prompt, dur)

    try:
        resp = httpx.post(
            f"{AUDIO_SERVER_URL}/generate",
            json=body,
            timeout=300.0,
        )
        resp.raise_for_status()
    except (httpx.ConnectError, httpx.TimeoutException, httpx.ConnectTimeout) as e:
        raise AudioServerOfflineError(f"Audio server unreachable: {e}") from e

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_bytes(resp.content)
    logger.info("[MusicGen] saved → %s", output_path)
    return output_path


def separate_stems(audio_path: str, output_dir: str) -> dict[str, str]:
    if not AUDIO_SERVER_URL:
        raise AudioServerOfflineError("AUDIO_SERVER_URL not configured")

    logger.info("[demucs] separating %s", Path(audio_path).name)

    try:
        with open(audio_path, "rb") as f:
            resp = httpx.post(
                f"{AUDIO_SERVER_URL}/stems",
                files={"file": (Path(audio_path).name, f, "audio/wav")},
                timeout=300.0,
            )
        resp.raise_for_status()
    except (httpx.ConnectError, httpx.TimeoutException, httpx.ConnectTimeout) as e:
        raise AudioServerOfflineError(f"Audio server unreachable: {e}") from e

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    stems: dict[str, str] = {}
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        for name in zf.namelist():
            stem_name = Path(name).stem
            out_path = out_dir / Path(name).name
            out_path.write_bytes(zf.read(name))
            stems[stem_name] = str(out_path)

    logger.info("[demucs] stems: %s", list(stems.keys()))
    return stems
