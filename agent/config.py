"""
Config — OpenClaw + Nemotron configuration.
All environment variables and model settings in one place.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── NVIDIA / Nemotron ─────────────────────────────────────────────────────────
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
NEMOTRON_MODEL = "nvidia/nemotron-4-340b-instruct"
NEMOTRON_TIMEOUT = 120       # seconds — 120B model can be slow on first call
NEMOTRON_MAX_TOKENS = 1500
NEMOTRON_TEMPERATURE = 0.8   # slightly creative for music tasks

# ── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Folders ───────────────────────────────────────────────────────────────────
WATCHED_FOLDER = os.getenv("WATCHED_FOLDER", "./watched")
OUTPUT_FOLDER = os.getenv("OUTPUT_FOLDER", "./output")

# ── Modes ─────────────────────────────────────────────────────────────────────
DJ_MODE = os.getenv("DJ_MODE", "false").lower() == "true"

# ── OpenClaw agent config (written to disk for OpenClaw to pick up) ───────────
OPENCLAW_CONFIG = {
    "env": {
        "NVIDIA_API_KEY": NVIDIA_API_KEY,
    },
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
            "model": {
                "primary": NEMOTRON_MODEL
            }
        }
    }
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
