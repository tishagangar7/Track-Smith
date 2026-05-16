"""
Watcher — monitors /watched folder for new MIDI files.
When a file is dropped, it enters a 60-second pairing window.
If the artist sends a Telegram message within that window, the pipeline
runs with their text as creative context. Otherwise it runs automatically.
"""

import threading
import time
import logging
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from agent.config import WATCHED_FOLDER, OUTPUT_FOLDER, DJ_MODE
from agent.skills.midi_analyzer import analyze_midi
from agent.skills.continuation_gen import generate_continuations
from agent.skills.dj_engine import DJEngine
from agent.pairing import add_pending, remove, is_pending, set_timer
from bot.telegram_bot import notify, notify_document

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

Path(WATCHED_FOLDER).mkdir(exist_ok=True)
Path(OUTPUT_FOLDER).mkdir(exist_ok=True)

# module-level reference so the bot can call run_pipeline without a circular import
_handler: "MIDIDropHandler | None" = None


def get_handler() -> "MIDIDropHandler | None":
    return _handler


class MIDIDropHandler(FileSystemEventHandler):
    def __init__(self):
        global _handler
        self.dj = DJEngine() if DJ_MODE else None
        self.processing = set()
        _handler = self

    def on_created(self, event):
        if event.is_directory:
            return

        path = Path(event.src_path)
        if path.suffix.lower() not in [".mid", ".midi"]:
            return
        if str(path) in self.processing:
            return

        self.processing.add(str(path))
        logger.info(f"🎵 New MIDI detected: {path.name}")

        add_pending(str(path))
        notify(
            f"🎵 *New MIDI dropped:* `{path.name}`\n"
            f"💬 Reply with a vibe now (e.g. _dark trap heavy 808s_) to guide the AI.\n"
            f"⏳ Auto-processing in 60s if no message."
        )

        set_timer(str(path), _timeout_check, args=(self, str(path)))

    def run_pipeline(self, filepath: str, prompt: str = None, mode: str = "full"):
        """Run the full analysis + continuation pipeline in a background thread."""
        def _run():
            path = Path(filepath)
            try:
                label = f" — _{prompt}_" if prompt else ""
                notify(f"⏳ Analyzing `{path.name}`{label}...")
                analysis = analyze_midi(filepath)
                logger.info(f"Analysis: {analysis}")

                result = generate_continuations(
                    analysis, output_dir=OUTPUT_FOLDER, prompt=prompt, mode=mode,
                    original_midi_path=filepath,
                )

                if self.dj and mode == "full":
                    self.dj.add_track(filepath, analysis)
                    self.dj.maybe_transition()

                if mode == "suggest":
                    notify(f"Here's what I'd try next:\n\n{result}")
                else:
                    _send_full_results(analysis, result)

            except Exception as e:
                logger.error(f"Pipeline error for {path.name}: {e}")
                notify(f"❌ Error processing `{path.name}`:\n{str(e)}")
            finally:
                self.processing.discard(filepath)

        threading.Thread(target=_run, daemon=True).start()


def _timeout_check(handler: MIDIDropHandler, filepath: str):
    """Called after 60s — process without prompt if not yet claimed by the bot."""
    if not is_pending(filepath):
        return  # already consumed by a paired text message
    remove(filepath)
    logger.info(f"⏰ Pairing timeout — processing {Path(filepath).name} without prompt")
    handler.run_pipeline(filepath, prompt=None)


def _send_full_results(analysis: dict, continuations: list):
    """
    For mode='full': send one text message + one .mid document per continuation.
    Filename in Telegram is DAW-friendly: aux_continuation_{key}_{bpm}bpm.mid
    """
    for c in continuations:
        key = c.get("key", "?")
        bpm = c.get("tempo", "?")
        vibe = c.get("vibe", "")
        description = c.get("description", "")
        filepath = c.get("filepath", "")

        msg = (
            f"Here's your next 4 bars 🎵\n"
            f"Key: {key} | {bpm} BPM | {vibe}\n"
            f"{description}"
        )

        # Strip characters that break filenames; keep it readable in a DAW browser
        key_safe = key.replace(" ", "_").replace("#", "sharp").replace("/", "-")
        daw_filename = f"aux_continuation_{key_safe}_{bpm}bpm.mid"

        notify(msg)
        if filepath and Path(filepath).exists():
            notify_document(filepath, filename=daw_filename)


def start_watcher():
    """Start the folder watcher — runs forever."""
    handler = MIDIDropHandler()
    observer = Observer()
    observer.schedule(handler, WATCHED_FOLDER, recursive=False)
    observer.start()

    logger.info(f"👀 Watching: {Path(WATCHED_FOLDER).resolve()}")
    logger.info(f"🎛  DJ Mode: {'ON' if DJ_MODE else 'OFF'}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
