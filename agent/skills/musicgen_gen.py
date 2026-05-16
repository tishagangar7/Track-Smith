"""
MusicGen via Replicate — audio continuation from verse MP3 or prompt-only for MIDI.

Set REPLICATE_API_TOKEN in .env (https://replicate.com/account/api-tokens).
Uses meta/musicgen melody mode when source audio exists; text-only otherwise.

This replaces Magenta on Apple Silicon (no TensorFlow 2.9 / arm64 issues).
"""

import logging
import os
import tempfile
from pathlib import Path

import librosa
import soundfile as sf

logger = logging.getLogger(__name__)

# Set after 402 insufficient credit — skip further Replicate calls this session
_replicate_billing_blocked = False

# Melody-capable MusicGen bundle on Replicate
_MUSICGEN_MELODY = (
    "meta/musicgen:671ac645ce5e552cc63a54a2bbff63fcf798043055d2dac5fc9e36a837eedcfb"
)


def musicgen_available() -> bool:
    if _replicate_billing_blocked:
        return False
    return bool(os.getenv("REPLICATE_API_TOKEN", "").strip())


def _build_prompt(params: dict) -> str:
    section = (params.get("section_type") or params.get("vibe") or "section").replace("_", " ")
    key = params.get("key", "C major")
    energy = params.get("energy_direction", "maintain")
    desc = params.get("description", "")
    parts = [
        f"{section} for a {key} track",
        f"energy {energy}",
        "instrumental, professional production, no vocals",
    ]
    if desc:
        parts.append(desc[:200])
    return ", ".join(parts)


def _section_duration_sec(params: dict, tempo: float) -> int:
    bars = int(params.get("bars") or 8)
    beats = bars * 4
    sec = beats * 60.0 / max(tempo, 40.0)
    return int(max(8, min(30, round(sec))))


def _prepare_audio_primer(source_path: str, tempo: float) -> tuple[str, float]:
    """Last ~8s of verse as WAV for MusicGen continuation conditioning."""
    y, sr = librosa.load(source_path, sr=32000, mono=True)
    primer_sec = min(8.0, max(2.0, len(y) / sr * 0.4))
    tail = y[int(max(0, len(y) - primer_sec * sr)) :]
    fd, wav_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    sf.write(wav_path, tail, sr)
    return wav_path, primer_sec


def _run_replicate(prompt: str, duration: int, primer_wav: str | None, continuation: bool) -> str:
    import replicate

    inp: dict = {
        "prompt": prompt,
        "duration": duration,
        "model_version": "melody",
        "continuation": continuation,
        "classifier_free_guidance": 3,
    }
    if primer_wav:
        inp["input_audio"] = open(primer_wav, "rb")

    global _replicate_billing_blocked
    try:
        out = replicate.run(_MUSICGEN_MELODY, input=inp)
    except Exception as e:
        err = str(e).lower()
        if "402" in err or "insufficient credit" in err:
            _replicate_billing_blocked = True
            logger.error(
                "Replicate: insufficient credit — add billing at replicate.com/account/billing"
            )
        raise
    finally:
        if primer_wav:
            try:
                os.unlink(primer_wav)
            except OSError:
                pass

    if isinstance(out, (list, tuple)):
        out = out[0]
    if not isinstance(out, str):
        raise RuntimeError(f"Unexpected Replicate output: {out!r}")
    return out


def _download_wav(url: str) -> str:
    import urllib.request

    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    urllib.request.urlretrieve(url, path)
    return path


def generate_section_with_musicgen(
    params: dict,
    output_path: str,
    tempo: float,
    analysis: dict | None = None,
) -> None:
    """
    Generate continuation WAV via MusicGen, then transcribe to MIDI.
    """
    if not musicgen_available():
        raise ImportError("REPLICATE_API_TOKEN not set — add to .env")

    from agent.skills.audio_to_midi import wav_to_section_midi

    prompt = _build_prompt(params)
    duration = _section_duration_sec(params, tempo)
    source = (analysis or {}).get("source_path")
    primer_wav = None
    primer_sec = 0.0
    continuation = False

    if source and (analysis or {}).get("source_type") == "audio" and Path(source).is_file():
        primer_wav, primer_sec = _prepare_audio_primer(source, tempo)
        continuation = True
        logger.info(f"MusicGen continuation from verse tail ({primer_sec:.1f}s)")

    try:
        audio_url = _run_replicate(prompt, duration, primer_wav, continuation)
        wav_path = _download_wav(audio_url)
        try:
            wav_to_section_midi(
                wav_path,
                output_path,
                tempo,
                params=params,
                trim_start_sec=primer_sec if continuation else 0.0,
            )
        finally:
            try:
                os.unlink(wav_path)
            except OSError:
                pass
    except Exception:
        if primer_wav and Path(primer_wav).exists():
            try:
                os.unlink(primer_wav)
            except OSError:
                pass
        raise

    logger.info(f"MusicGen section → {output_path}")
