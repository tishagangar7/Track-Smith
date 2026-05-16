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


def _fix_qt_plugin_path():
    """macOS/conda: Qt sometimes can't find the cocoa platform plugin."""
    if os.environ.get("QT_QPA_PLATFORM_PLUGIN_PATH"):
        return
    try:
        import PyQt6
        plugins = Path(PyQt6.__file__).parent / "Qt6" / "plugins"
        platforms = plugins / "platforms"
        if platforms.is_dir():
            os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(platforms)
            os.environ.setdefault("QT_PLUGIN_PATH", str(plugins))
    except Exception:
        pass


def _check_env():
    key = os.getenv("NVIDIA_API_KEY", "")
    if not key:
        logger.warning("NVIDIA_API_KEY not set — Nemotron calls will fail. Add it to .env")
    else:
        logger.info("NVIDIA_API_KEY: set")
    stub = os.getenv("STUB_MODE", "false").lower() == "true"
    if stub:
        logger.info("STUB_MODE=true — Nemotron calls skipped (testing mode)")
    else:
        from agent.config import NEMOTRON_MODEL_MAIN, NEMOTRON_MODEL_FAST
        logger.info(f"Nemotron main: {NEMOTRON_MODEL_MAIN}")
        logger.info(f"Nemotron fast: {NEMOTRON_MODEL_FAST}")


def main():
    _fix_qt_plugin_path()
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
