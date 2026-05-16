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


def _audio_server_error(resp: httpx.Response) -> str:
    try:
        detail = resp.json().get("detail")
    except Exception:
        detail = resp.text[:500]
    return f"Audio server returned {resp.status_code}: {detail or resp.reason_phrase}"


# keyword → specific instrument/texture descriptor (MusicGen responds to these)
_STYLE_MAP: list[tuple[set[str], str]] = [
    ({"trap", "drill"},
     "Roland TR-808 sub bass with long decay, triplet hi-hats, snare rolls, dark and brooding"),
    ({"808"},
     "Roland TR-808 pitch-sliding sub bass with long tail, deep chest-rattling low end"),
    ({"lo-fi", "lofi", "lo fi"},
     "Rhodes electric piano, vinyl crackle, dusty boom bap drums, warm tape saturation"),
    ({"dark"},
     "minor key, reverb-drenched, brooding atmosphere, sparse haunting notes"),
    ({"drake", "melodic"},
     "emotional piano melody, lush atmospheric pads, melodic and cinematic"),
    ({"house", "dance"},
     "four-on-the-floor kick, off-beat hi-hats, deep Chicago house organ"),
    ({"ambient", "atmospheric"},
     "evolving synth pads, slow attack, deep reverb wash, minimal percussion"),
    ({"jazz", "jazzy"},
     "walking upright bass, jazz chord voicings, brushed snare, swing groove"),
    ({"boom bap", "boom-bap"},
     "punchy sampled drums, crate-digging soul chops, NYC underground"),
    ({"afrobeats", "afro"},
     "talking drum, plucked kora, bouncy kick, bright synth stabs"),
    ({"r&b", "rnb", "soul"},
     "soulful Rhodes chords, warm bass guitar, soft brushed snare"),
    ({"rage", "pluggnb"},
     "icy tuned bells, heavy distorted 808, Atlanta melodic trap"),
]

_ENERGY_RHYTHM: dict[str, str] = {
    "high": "hard-hitting drums, punchy transients, driving rhythm",
    "mid":  "mid-tempo groove, balanced dynamics",
    "low":  "slow laid-back feel, soft dynamics, spacious mix",
}


def build_musicgen_prompt(analysis: dict, prompt: str | None = None) -> str:
    key = analysis.get("key", "C major")
    tempo = int(analysis.get("tempo") or 120)
    energy = float(analysis.get("energy") or 0.5)

    energy_tier = "high" if energy > 0.7 else ("low" if energy < 0.3 else "mid")
    rhythm_desc = _ENERGY_RHYTHM[energy_tier]

    raw = (prompt or "").lower()
    # Deduplicate: use dict to preserve insertion order, last-wins per keyword group
    seen_descriptors: dict[str, bool] = {}
    for keywords, descriptor in _STYLE_MAP:
        if any(kw in raw for kw in keywords) and descriptor not in seen_descriptors:
            seen_descriptors[descriptor] = True

    parts: list[str] = list(seen_descriptors.keys()) if seen_descriptors else []
    parts.append(rhythm_desc)
    parts.append(f"{key} key")
    parts.append(f"{tempo} BPM")
    parts.append("professional studio mix, high fidelity audio")

    # Append user free-text last for any extra nuance
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

    openclaw.call_musicgen("MusicGen audio generation")
    try:
        resp = httpx.post(
            f"{AUDIO_SERVER_URL}/generate",
            json=body,
            timeout=300.0,
        )
        resp.raise_for_status()
    except (httpx.ConnectError, httpx.TimeoutException, httpx.ConnectTimeout) as e:
        raise AudioServerOfflineError(f"Audio server unreachable: {e}") from e
    except httpx.HTTPStatusError as e:
        raise AudioServerOfflineError(_audio_server_error(e.response)) from e

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_bytes(resp.content)
    logger.info("[MusicGen] saved → %s", output_path)
    return output_path


def separate_stems(audio_path: str, output_dir: str) -> dict[str, str]:
    if not AUDIO_SERVER_URL:
        raise AudioServerOfflineError("AUDIO_SERVER_URL not configured")

    logger.info("[demucs] separating %s", Path(audio_path).name)
    openclaw.call_demucs("Demucs stem separation")

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
    except httpx.HTTPStatusError as e:
        raise AudioServerOfflineError(_audio_server_error(e.response)) from e

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
