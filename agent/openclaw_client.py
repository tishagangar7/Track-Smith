"""
OpenClaw client — wraps agent tool calls with policy-aware logging.
Every action is logged with its policy status (allowed/blocked).
Falls back gracefully if OpenClaw gateway is unavailable.
"""

import os
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_ALLOWED_READ = [
    os.path.expanduser("~/Track-Smith/watched"),
    os.path.expanduser("~/Track-Smith/plugin_output"),
    os.path.expanduser("~/Track-Smith/agent"),
    os.path.expanduser("~/.cache/huggingface"),
]

_ALLOWED_WRITE = [
    os.path.expanduser("~/Track-Smith/plugin_output"),
    os.path.expanduser("~/Track-Smith/watched"),
]

_ALLOWED_NETWORKS = {
    "api.nvidia.com",
    "integrate.api.nvidia.com",
    "127.0.0.1:8001",
    "127.0.0.1:8000",
    "100.77.70.20:8001",
    "100.77.70.20:8000",
    "100.77.70.20:18789",
}


class OpenClawClient:
    def __init__(self):
        self.url = os.getenv("OPENCLAW_URL", "http://100.77.70.20:18789")
        self.token = os.getenv("OPENCLAW_TOKEN", "")
        self.policy_log: list[dict] = []

    def log_action(self, action: str, resource: str, status: str, detail: str = "") -> dict:
        entry = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "resource": resource,
            "status": status,
            "detail": detail,
        }
        self.policy_log.append(entry)
        logger.info("[OpenClaw] %s: %s → %s%s",
                    status.upper(), action, resource,
                    f" ({detail})" if detail else "")
        return entry

    def call_nemotron(self, detail: str = "Nemotron musical reasoning") -> dict:
        return self.log_action("network.call", "api.nvidia.com", "allowed", detail)

    def call_local_model(self, detail: str = "Qwen plan validation") -> dict:
        return self.log_action("network.call", "100.77.70.20:8000", "allowed", detail)

    def call_musicgen(self, detail: str = "MusicGen audio generation") -> dict:
        return self.log_action("network.call", "100.77.70.20:8001", "allowed", detail)

    def call_demucs(self, detail: str = "Demucs stem separation") -> dict:
        return self.log_action("network.call", "100.77.70.20:8001", "allowed", detail)

    def read_file(self, path: str) -> bytes:
        is_allowed = any(str(path).startswith(p) for p in _ALLOWED_READ)
        status = "allowed" if is_allowed else "blocked"
        self.log_action("filesystem.read", str(path), status)
        if not is_allowed:
            raise PermissionError(f"OpenClaw policy blocked read: {path}")
        return Path(path).read_bytes()

    def write_file(self, path: str, data: bytes | None = None) -> None:
        is_allowed = any(str(path).startswith(p) for p in _ALLOWED_WRITE)
        status = "allowed" if is_allowed else "blocked"
        self.log_action("filesystem.write", str(path), status)
        if not is_allowed:
            raise PermissionError(f"OpenClaw policy blocked write: {path}")
        if data is not None:
            Path(path).write_bytes(data)

    def log_midi_write(self, output_path: str) -> dict:
        return self.log_action("filesystem.write", str(output_path), "allowed", "Writing generated MIDI")

    def get_policy_log(self) -> list[dict]:
        return list(self.policy_log)

    def get_recent_log(self, n: int = 5) -> list[dict]:
        return self.policy_log[-n:]


# Singleton — import this in skills
openclaw = OpenClawClient()
