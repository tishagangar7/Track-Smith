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


def build_musicgen_prompt(analysis: dict, prompt: str | None = None) -> str:
    key = analysis.get("key", "C major")
    tempo = analysis.get("tempo", 120)
    energy = analysis.get("energy", 0.5)
    chords = " ".join((analysis.get("chord_progression") or [])[:4])

    if energy > 0.7:
        energy_word = "energetic"
    elif energy < 0.3:
        energy_word = "calm"
    else:
        energy_word = "groovy"

    parts = [f"{energy_word} music in {key} at {tempo} BPM"]
    if chords:
        parts.append(f"chord progression: {chords}")
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
            timeout=120.0,
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
