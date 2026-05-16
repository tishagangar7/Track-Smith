"""
Config — Nemotron / NVIDIA API settings.

Hackathon requirement: use NVIDIA Nemotron family models via
https://integrate.api.nvidia.com/v1 (API key from build.nvidia.com → View Code).

Default models (both available on integrate.api):
  - nvidia/nvidia-nemotron-nano-9b-v2          — fast (suggest, light tasks)
  - nvidia/llama-3.3-nemotron-super-49b-v1.5   — main (fill, vibe, mix reasoning)
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── NVIDIA / Nemotron ─────────────────────────────────────────────────────────
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
NVIDIA_BASE_URL = os.getenv("NVIDIA_API_BASE", "https://integrate.api.nvidia.com/v1")

# Hackathon Nemotron models (override in .env if needed)
NEMOTRON_MODEL_FAST = os.getenv(
    "NEMOTRON_MODEL_FAST",
    "nvidia/nvidia-nemotron-nano-9b-v2",
)
NEMOTRON_MODEL_MAIN = os.getenv(
    "NEMOTRON_MODEL_MAIN",
    "nvidia/llama-3.3-nemotron-super-49b-v1.5",
)
# Back-compat: single var maps to main model
NEMOTRON_MODEL = os.getenv("NEMOTRON_MODEL", NEMOTRON_MODEL_MAIN)

NEMOTRON_TIMEOUT = int(os.getenv("NEMOTRON_TIMEOUT", "120"))

# ── Audio / MusicGen ──────────────────────────────────────────────────────────
AUDIO_SERVER_URL = os.getenv("AUDIO_SERVER_URL", "")   # e.g. http://100.77.70.20:8001
AUDIO_DURATION = int(os.getenv("AUDIO_DURATION", "8"))  # seconds
NEMOTRON_MAX_TOKENS = int(os.getenv("NEMOTRON_MAX_TOKENS", "1500"))
NEMOTRON_TEMPERATURE = float(os.getenv("NEMOTRON_TEMPERATURE", "0.6"))

# Nemotron-only fallback chain (no Meta Llama non-Nemotron models)
NEMOTRON_MODEL_FALLBACKS = [
    m.strip()
    for m in os.getenv(
        "NEMOTRON_MODEL_FALLBACKS",
        ",".join([
            NEMOTRON_MODEL_MAIN,
            NEMOTRON_MODEL_FAST,
            "nvidia/llama-3.3-nemotron-super-49b-v1",
            "nvidia/nemotron-4-340b-instruct",
        ]),
    ).split(",")
    if m.strip()
]

# ── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Folders ───────────────────────────────────────────────────────────────────
WATCHED_FOLDER = os.getenv("WATCHED_FOLDER", "./watched")
OUTPUT_FOLDER = os.getenv("OUTPUT_FOLDER", "./output")

# ── Modes ─────────────────────────────────────────────────────────────────────
DJ_MODE = os.getenv("DJ_MODE", "false").lower() == "true"
STUB_MODE = os.getenv("STUB_MODE", "false").lower() == "true"

OPENCLAW_CONFIG = {
    "env": {"NVIDIA_API_KEY": NVIDIA_API_KEY},
    "models": {
        "providers": {
            "nvidia": {
                "baseUrl": NVIDIA_BASE_URL,
                "api": "openai-completions",
            }
        }
    },
    "agents": {
        "defaults": {
            "model": {"primary": NEMOTRON_MODEL_MAIN}
        }
    },
}


def validate():
    """Check all required env vars are set before starting."""
    missing = []
    if not NVIDIA_API_KEY:
        missing.append("NVIDIA_API_KEY")
    if not TELEGRAM_TOKEN:
        missing.append("TELEGRAM_TOKEN")
    if not TELEGRAM_CHAT_ID:
        missing.append("TELEGRAM_CHAT_ID")

    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}\n"
            f"Copy .env.example to .env and fill in the values."
        )
