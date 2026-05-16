"""
Aux Plugin — desktop companion app entry point.
Run with: python plugin_main.py
"""

import os
import sys
import logging
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent
OUTPUT_DIR = str(REPO_ROOT / "plugin_output")


def _check_env():
    key = os.getenv("NVIDIA_API_KEY", "")
    if not key:
        logger.warning("NVIDIA_API_KEY not set — Nemotron calls will fail. Add it to .env")
    else:
        logger.info("NVIDIA_API_KEY: set")
    stub = os.getenv("STUB_MODE", "false").lower() == "true"
    if stub:
        logger.info("STUB_MODE=true — Nemotron calls skipped (testing mode)")


def main():
    _check_env()

    try:
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import Qt
    except ImportError:
        sys.exit(
            "PyQt6 not installed.\n"
            "Run: pip install PyQt6\n"
            "Then re-launch: python plugin_main.py"
        )

    app = QApplication(sys.argv)
    app.setApplicationName("Aux")
    app.setOrganizationName("Aux")

    from plugin.app import AuxApp
    window = AuxApp(output_dir=OUTPUT_DIR)
    window.show()

    logger.info(f"Aux plugin started. Output: {OUTPUT_DIR}")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
