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
from agent.openclaw_client import openclaw

logger = logging.getLogger(__name__)


class AudioServerOfflineError(Exception):
    pass


# Keyword → producer-grade descriptor. Checked in order; multiple can match.
_STYLE_MAP: list[tuple[set[str], str]] = [
    # Genre keywords
    ({"trap", "drill"},          "trap drums, 808 sub bass, triplet hi-hats"),
    ({"808"},                    "heavy 808 sub bass, trap drums"),
    ({"lo-fi", "lofi", "lo fi"}, "lo-fi hip hop, jazzy piano, dusty drums, vinyl warmth"),
    ({"dark"},                   "dark, moody, minor key atmosphere"),
    ({"jazz", "jazzy"},          "jazz piano, walking bass, brushed drums"),
    ({"house", "dance"},         "four-on-the-floor kick, punchy synth bass, dance music"),
    ({"ambient", "atmospheric"},  "ambient textural pads, reverb wash, slow attack"),
    ({"r&b", "rnb", "soul"},     "R&B, soulful smooth chords, vocal chops"),
    ({"rage", "pluggnb"},        "pluggnb, icy bells, heavy bass, Atlanta"),
    ({"boom bap", "boom-bap"},   "boom bap, sampled drums, punchy snare, NYC hip hop"),
    # Artist names → sonic signature
    ({"taylor swift", "taylor"}, "pop, synth-pop, shimmering electric guitar, anthemic chorus, bright production"),
    ({"drake", "melodic"},       "melodic, emotional, atmospheric pads, vocal chops"),
    ({"kendrick", "kdot"},       "west coast hip hop, jazz samples, complex rhythms, layered percussion"),
    ({"weeknd", "the weeknd"},   "dark synth-pop, 80s retro, lush reverb, moody bass"),
    ({"billie", "billie eilish"}, "minimalist pop, whisper vocals, sub bass, sparse dark production"),
    ({"kanye", "ye"},            "soul samples, chopped vocals, maximalist layers, Chicago soul"),
    ({"future"},                 "trap, auto-tune melody, dark 808s, melodic rap"),
    ({"travis scott", "travis"}, "psychedelic trap, warped synths, 808 slides, layered ad-libs"),
    ({"sza"},                    "alt R&B, warm guitars, jazzy chords, dreamy atmosphere"),
    ({"metro boomin", "metro"},  "dark trap, cinematic strings, heavy 808s, orchestral elements"),
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

    # Lock to the detected chord progression so harmonics match the input
    chords = analysis.get("chord_progression") or []
    if chords:
        parts.append(f"chord progression {' '.join(chords)}")

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

    openclaw.log_action("network.call", "100.77.70.20:8001", "allowed", "MusicGen audio generation")
    try:
        resp = httpx.post(
            f"{AUDIO_SERVER_URL}/generate",
            json=body,
            timeout=httpx.Timeout(connect=5.0, read=300.0, write=60.0, pool=5.0),
        )
        resp.raise_for_status()
    except (httpx.ConnectError, httpx.TimeoutException, httpx.ConnectTimeout) as e:
        raise AudioServerOfflineError(f"Audio server unreachable: {e}") from e
    except httpx.HTTPStatusError as e:
        detail = ""
        try:
            detail = e.response.json().get("detail", "")
        except Exception:
            pass
        raise AudioServerOfflineError(f"Audio server error {e.response.status_code}: {detail}") from e

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_bytes(resp.content)
    logger.info("[MusicGen] saved → %s", output_path)
    return output_path


def combine_audio_with_continuation(
    original_path: str,
    continuation_path: str,
    output_path: str,
    crossfade_sec: float = 1.5,
) -> str:
    """Crossfade-combine original audio with generated continuation into one WAV."""
    import numpy as np
    import soundfile as sf
    import librosa

    TARGET_SR = 44100

    y_orig, _ = librosa.load(original_path, sr=TARGET_SR, mono=False)
    y_cont, _ = librosa.load(continuation_path, sr=TARGET_SR, mono=False)

    # Ensure stereo (2, samples)
    if y_orig.ndim == 1:
        y_orig = np.stack([y_orig, y_orig])
    if y_cont.ndim == 1:
        y_cont = np.stack([y_cont, y_cont])

    # Normalise both to -1..1 peak, then match levels to original
    orig_peak = np.abs(y_orig).max() or 1.0
    cont_peak = np.abs(y_cont).max() or 1.0
    y_cont = y_cont * (orig_peak / cont_peak)

    xfade = int(crossfade_sec * TARGET_SR)
    xfade = min(xfade, y_orig.shape[1], y_cont.shape[1])

    fade_out = np.linspace(1.0, 0.0, xfade, dtype=np.float32)
    fade_in  = np.linspace(0.0, 1.0, xfade, dtype=np.float32)

    body  = y_orig[:, :-xfade] if y_orig.shape[1] > xfade else y_orig[:, :0]
    blend = y_orig[:, -xfade:] * fade_out + y_cont[:, :xfade] * fade_in
    tail  = y_cont[:, xfade:]

    combined = np.concatenate([body, blend, tail], axis=1)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    sf.write(output_path, combined.T, TARGET_SR)
    logger.info("[combine] %s + %s → %s (%.1fs)",
                Path(original_path).name, Path(continuation_path).name,
                Path(output_path).name, combined.shape[1] / TARGET_SR)
    return output_path


def separate_stems(audio_path: str, output_dir: str) -> dict[str, str]:
    if not AUDIO_SERVER_URL:
        raise AudioServerOfflineError("AUDIO_SERVER_URL not configured")

    logger.info("[demucs] separating %s", Path(audio_path).name)
    openclaw.log_action("network.call", "100.77.70.20:8001", "allowed", "Demucs stem separation")

    try:
        with open(audio_path, "rb") as f:
            resp = httpx.post(
                f"{AUDIO_SERVER_URL}/stems",
                files={"file": (Path(audio_path).name, f, "audio/wav")},
                timeout=httpx.Timeout(connect=5.0, read=300.0, write=60.0, pool=5.0),
            )
        resp.raise_for_status()
    except (httpx.ConnectError, httpx.TimeoutException, httpx.ConnectTimeout) as e:
        raise AudioServerOfflineError(f"Audio server unreachable: {e}") from e
    except httpx.HTTPStatusError as e:
        detail = ""
        try:
            detail = e.response.json().get("detail", "")
        except Exception:
            pass
        raise AudioServerOfflineError(f"Audio server error {e.response.status_code}: {detail}") from e

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
