"""
Aux — Autonomous Music Agent
Entry point. Starts the folder watcher and Telegram bot concurrently.
"""

import os
import logging
import threading
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    logger.info("🎛  Aux starting...")
    logger.info(f"   NVIDIA API : {'✅ set' if os.getenv('NVIDIA_API_KEY') else '❌ NOT SET — add to .env'}")
    logger.info(f"   Telegram   : {'✅ set' if os.getenv('TELEGRAM_TOKEN') else '❌ NOT SET — add to .env'}")
    logger.info(f"   DJ Mode    : {'ON' if os.getenv('DJ_MODE', 'false') == 'true' else 'OFF'}")
    logger.info(f"   Watching   : {os.getenv('WATCHED_FOLDER', './watched')}")
    logger.info(f"   Output     : {os.getenv('OUTPUT_FOLDER', './output')}")

    from agent.watcher import start_watcher
    from bot.telegram_bot import start_bot

    # folder watcher runs in background thread
    watcher_thread = threading.Thread(target=start_watcher, daemon=True)
    watcher_thread.start()
    logger.info("👀 Folder watcher running")

    # telegram bot runs in main thread (blocking)
    logger.info("🤖 Telegram bot starting — waiting for commands...")
    start_bot()


if __name__ == "__main__":
    main()
