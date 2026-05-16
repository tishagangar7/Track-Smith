"""
Pairing state — stores MIDIs dropped into the watched folder,
waiting for an artist text message within the pairing window.
Thread-safe; consumed by the watcher timeout or the Telegram handle_message handler.
"""

import threading
import time

PAIRING_WINDOW = 60  # seconds

_lock = threading.Lock()
_pending: dict = {}    # filepath -> unix timestamp
_timers: dict = {}     # filepath -> active threading.Timer
_callbacks: dict = {}  # filepath -> (callback_fn, args_tuple)


def add_pending(filepath: str):
    with _lock:
        _pending[filepath] = time.time()


def set_timer(filepath: str, callback, args: tuple = (), delay: float = PAIRING_WINDOW):
    """Start (or restart) the fallback timeout timer for a pending MIDI."""
    existing = _timers.pop(filepath, None)
    if existing:
        existing.cancel()
    t = threading.Timer(delay, callback, args=args)
    t.daemon = True
    t.start()
    _timers[filepath] = t
    _callbacks[filepath] = (callback, args)


def reset_timer(filepath: str, delay: float = PAIRING_WINDOW):
    """
    Cancel the current timer for filepath and start a fresh one with the same callback.
    No-op if no timer is registered for this file.
    """
    if filepath not in _callbacks:
        return
    callback, args = _callbacks[filepath]
    set_timer(filepath, callback, args=args, delay=delay)


def peek_latest() -> "str | None":
    """Return the most-recently-dropped pending filepath without consuming it."""
    now = time.time()
    with _lock:
        candidates = [
            (fp, ts) for fp, ts in _pending.items()
            if now - ts <= PAIRING_WINDOW
        ]
        if not candidates:
            return None
        fp, _ = max(candidates, key=lambda x: x[1])
        return fp


def consume_latest() -> "str | None":
    """
    Return and remove the most-recently-dropped pending MIDI within the pairing window.
    Cancels the associated timer. Returns None if nothing is waiting.
    """
    now = time.time()
    with _lock:
        candidates = [
            (fp, ts) for fp, ts in _pending.items()
            if now - ts <= PAIRING_WINDOW
        ]
        if not candidates:
            return None
        fp, _ = max(candidates, key=lambda x: x[1])
        del _pending[fp]

    # cancel timer outside the lock (cancel on an already-fired timer is a no-op)
    timer = _timers.pop(fp, None)
    if timer:
        timer.cancel()
    _callbacks.pop(fp, None)
    return fp


def remove(filepath: str):
    """Remove a pending MIDI and cancel its timer (called on timeout fire)."""
    with _lock:
        _pending.pop(filepath, None)
    timer = _timers.pop(filepath, None)
    if timer:
        timer.cancel()
    _callbacks.pop(filepath, None)


def is_pending(filepath: str) -> bool:
    with _lock:
        return filepath in _pending
