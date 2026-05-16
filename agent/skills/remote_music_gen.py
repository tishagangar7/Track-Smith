"""
Remote audio section generation.

Priority:
  1. DGX MusicGen server (free, local, best quality)
     Set DGX_MUSICGEN_URL=http://<dgx-ip>:7860 in .env
     Run scripts/dgx_musicgen_server.py on the DGX first.

  2. sunor.cc fallback (25 free credits on signup)
     Set SUNOR_API_KEY in .env

MUSIC_API_PROVIDER=auto  (auto | dgx | sunor | off)
"""

import logging
import os
import shutil
import tempfile
import time
import urllib.request

logger = logging.getLogger(__name__)

_SUNOR_BASE = "https://sunor.cc/api/v1"


# ── provider detection ────────────────────────────────────────────────────────

def _dgx_url() -> str:
    return os.getenv("DGX_MUSICGEN_URL", "").strip().rstrip("/")

def _sunor_key() -> str:
    return os.getenv("SUNOR_API_KEY", "").strip()

def _sunor_model() -> str:
    return os.getenv("SUNOR_MODEL", "udio").lower()

def available_providers() -> list[str]:
    providers = []
    if _dgx_url():
        providers.append("dgx")
    if _sunor_key():
        providers.append("sunor")
    return providers


# ── main entry point ──────────────────────────────────────────────────────────

def generate_section_remote(
    params: dict,
    output_path: str,
    tempo: float,
    analysis: dict | None = None,
) -> str:
    """
    Try DGX MusicGen first, then sunor.cc. Raises if both fail.
    Returns backend label: 'dgx_audio' or 'sunor_audio'.
    Saves audio as .wav or .mp3 at _audio_output_path(output_path).
    """
    api_provider = os.getenv("MUSIC_API_PROVIDER", "auto").lower()
    if api_provider == "off":
        raise RuntimeError("MUSIC_API_PROVIDER=off")

    # 1. DGX MusicGen (free, local)
    if api_provider in ("auto", "dgx") and _dgx_url():
        try:
            return _dgx_generate(params, output_path, tempo, analysis)
        except Exception as e:
            logger.warning(f"DGX MusicGen failed ({e}), trying sunor...")

    # 2. sunor.cc cloud
    if api_provider in ("auto", "sunor") and _sunor_key():
        return _sunor_generate_flow(params, output_path, tempo, analysis)

    raise RuntimeError("No remote music provider available. Set DGX_MUSICGEN_URL or SUNOR_API_KEY.")


# ── DGX MusicGen ──────────────────────────────────────────────────────────────

def _dgx_generate(params: dict, output_path: str, tempo: float, analysis: dict | None) -> str:
    import requests

    prompt = _build_musicgen_prompt(params, tempo, analysis)
    duration = _fill_duration_seconds(params, tempo)
    logger.info(f"DGX MusicGen: '{prompt[:80]}' ({duration}s)")

    r = requests.post(
        f"{_dgx_url()}/generate",
        json={"prompt": prompt, "duration": duration},
        timeout=300,  # generation can take ~60-90s on DGX
        stream=True,
    )
    r.raise_for_status()

    wav_dest = _audio_output_path(output_path, ext=".wav")
    with open(wav_dest, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)

    logger.info(f"DGX audio fill → {wav_dest}")
    return "dgx_audio"


def _build_musicgen_prompt(params: dict, tempo: float, analysis: dict | None) -> str:
    section = (params.get("section_type") or params.get("vibe") or "section").replace("_", " ")
    key = params.get("key", "C major")
    bpm = int(round(tempo))
    energy = (params.get("energy_direction") or "steady").lower()
    energy_words = {"build": "building energy", "drop": "chill relaxed", "maintain": "steady groove"}
    chords = params.get("chord_progression") or []
    chord_str = f", chords {' '.join(chords[:4])}" if chords else ""

    brightness = "dark atmospheric" if analysis and analysis.get("audio_features", {}).get("brightness") == "warm" else "bright"
    return (
        f"instrumental hip hop trap beat, {section}, {key} key, {bpm} BPM, "
        f"{energy_words.get(energy, energy)}, {brightness}{chord_str}, no vocals, producer beat"
    )


def _fill_duration_seconds(params: dict, tempo: float) -> int:
    bars = int(params.get("bars", 8))
    beats = bars * 4
    return max(10, min(60, int(beats * 60.0 / max(tempo, 1))))


# ── sunor.cc ──────────────────────────────────────────────────────────────────

def _sunor_generate_flow(params: dict, output_path: str, tempo: float, analysis: dict | None) -> str:
    import requests

    key = _sunor_key()
    model = _sunor_model()
    headers = {"x-api-key": key, "Content-Type": "application/json"}

    desc = _build_musicgen_prompt(params, tempo, analysis)
    logger.info(f"sunor.cc generate: model={model} prompt={desc[:80]}")

    body = {"model": model, "task_type": "music",
            "input": {"gpt_description_prompt": desc, "make_instrumental": True}}

    r = None
    for attempt in range(3):
        r = requests.post(f"{_SUNOR_BASE}/task", headers=headers, json=body, timeout=30)
        if r.status_code != 502:
            break
        logger.warning(f"sunor 502 attempt {attempt+1}/3, retrying...")
        time.sleep(3)

    if r.status_code == 401:
        raise RuntimeError("sunor.cc: invalid SUNOR_API_KEY")
    if r.status_code == 402:
        raise RuntimeError("sunor.cc: out of credits")
    r.raise_for_status()

    task_id = (r.json().get("data") or {}).get("task_id")
    if not task_id:
        raise RuntimeError(f"sunor.cc: no task_id: {r.json()}")

    for attempt in range(60):
        time.sleep(5)
        pr = requests.get(f"{_SUNOR_BASE}/task/{task_id}", headers={"x-api-key": key}, timeout=20)
        pr.raise_for_status()
        pd = pr.json().get("data", {})
        status = pd.get("status")
        if status == "success":
            clips = ((pd.get("output") or {}).get("result")) or []
            for clip in clips:
                url = clip.get("audio_url", "")
                if url:
                    mp3_src = _download_audio(url)
                    mp3_dest = _audio_output_path(output_path, ext=".mp3")
                    shutil.copy2(mp3_src, mp3_dest)
                    os.unlink(mp3_src)
                    return "sunor_audio"
            raise RuntimeError("sunor: success but no audio_url")
        if status in ("failure", "timeout"):
            raise RuntimeError(f"sunor: task {status}")
        logger.info(f"sunor poll {attempt+1}/60 [{status}]")

    raise RuntimeError("sunor: timed out after 5 min")


# ── utilities ─────────────────────────────────────────────────────────────────

def _audio_output_path(midi_path: str, ext: str = ".mp3") -> str:
    for old in (".mid", ".midi"):
        if midi_path.lower().endswith(old):
            return midi_path[:-len(old)] + ext
    return midi_path + ext


def _download_audio(url: str) -> str:
    fd, path = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)
    urllib.request.urlretrieve(url, path)
    return path


def check_credits() -> dict:
    import requests
    r = requests.get(f"{_SUNOR_BASE}/account/balance",
                     headers={"x-api-key": _sunor_key()}, timeout=10)
    r.raise_for_status()
    return r.json().get("data", {})
