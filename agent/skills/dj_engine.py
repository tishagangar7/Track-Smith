"""
DJ Engine — autonomous DJ agent.
Maintains a track library, asks Nemotron what to play next,
and executes transitions. Runs forever until stopped.
"""

import json
import logging
import threading
import time
from pathlib import Path
from collections import deque

import requests

from agent.config import (
    NVIDIA_API_KEY, NVIDIA_BASE_URL, NEMOTRON_MODEL,
    NEMOTRON_TIMEOUT
)

logger = logging.getLogger(__name__)


class DJEngine:
    """
    Autonomous DJ agent.
    You add tracks. It decides what plays and when.
    """

    def __init__(self):
        self.library = {}           # filepath -> analysis dict
        self.queue = deque()
        self.history = []
        self.current_track = None
        self.is_playing = False
        self.lock = threading.Lock()
        logger.info("🎛 DJ Engine initialized")

    def add_track(self, filepath: str, analysis: dict):
        """Add a new track to the DJ library."""
        with self.lock:
            self.library[filepath] = analysis
            logger.info(
                f"Library +1: {Path(filepath).name} "
                f"({analysis.get('tempo', '?'):.0f} BPM · {analysis.get('key', '?')})"
            )

    def maybe_transition(self):
        """
        Called when a new track is added.
        If nothing is playing, start the set.
        """
        with self.lock:
            if not self.is_playing and len(self.library) > 0:
                self._start_set()

    def _start_set(self):
        """Begin the set with the first track in the library."""
        if not self.library:
            return

        first = list(self.library.keys())[0]
        self.current_track = first
        self.history.append(first)
        self.is_playing = True

        logger.info(f"▶ Set started: {Path(first).name}")
        self._notify_transition(None, first, "Set started")

        threading.Thread(target=self._pick_next_loop, daemon=True).start()

    def _pick_next_loop(self):
        """
        Background loop — continuously picks the next track.
        Simulates track duration with a sleep, then transitions.
        """
        while self.is_playing:
            # simulate track playing — in a real setup this would
            # wait for actual playback to near its end
            duration = self.library.get(self.current_track, {}).get("duration", 30)
            sleep_time = max(10, duration * 0.8)
            logger.info(f"⏳ Playing for {sleep_time:.0f}s before next decision...")
            time.sleep(sleep_time)

            if not self.is_playing:
                break

            next_track = self._ask_nemotron_next()
            if next_track:
                self._execute_transition(next_track)

    def _ask_nemotron_next(self) -> str:
        """
        Ask Nemotron which track to play next.
        Returns filepath of chosen track.
        """
        current_analysis = self.library.get(self.current_track, {})

        candidates = {
            path: analysis
            for path, analysis in self.library.items()
            if path != self.current_track and path not in self.history[-3:]
        }

        if not candidates:
            self.history = [self.current_track]
            candidates = {
                path: analysis
                for path, analysis in self.library.items()
                if path != self.current_track
            }

        if not candidates:
            return None

        candidate_list = [
            {
                "id": i,
                "filename": Path(path).name,
                "key": analysis.get("key", "?"),
                "tempo": round(analysis.get("tempo", 120), 1),
                "energy": analysis.get("energy", 0.5),
            }
            for i, (path, analysis) in enumerate(candidates.items())
        ]

        prompt = f"""You are an expert DJ making autonomous set decisions.

Current track:
- Key: {current_analysis.get('key', '?')}
- Tempo: {current_analysis.get('tempo', 120):.1f} BPM
- Energy: {current_analysis.get('energy', 0.5):.2f}

Candidate tracks:
{json.dumps(candidate_list, indent=2)}

Choose the best next track for a smooth, engaging set.
Consider: harmonic compatibility, BPM proximity, energy arc.

Respond ONLY with valid JSON, no other text:
{{
  "chosen_id": 0,
  "reason": "why this track works next",
  "transition_style": "crossfade/cut/filter_sweep",
  "energy_direction": "build/drop/maintain"
}}"""

        headers = {
            "Authorization": f"Bearer {NVIDIA_API_KEY}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": NEMOTRON_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 200,
            "temperature": 0.6,
        }

        try:
            logger.info("🤔 Asking Nemotron for next track...")
            response = requests.post(
                f"{NVIDIA_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
                timeout=NEMOTRON_TIMEOUT,
            )
            response.raise_for_status()

            content = response.json()["choices"][0]["message"]["content"].strip()
            content = content.strip("```json").strip("```").strip()
            decision = json.loads(content)

            chosen_id = decision.get("chosen_id", 0)
            paths = list(candidates.keys())

            if 0 <= chosen_id < len(paths):
                chosen = paths[chosen_id]
                logger.info(f"Nemotron: → {Path(chosen).name} ({decision.get('reason', '')})")
                self._notify_dj_decision(decision, Path(chosen).name)
                return chosen

        except Exception as e:
            logger.error(f"Nemotron DJ decision failed: {e}")
            # fallback: closest BPM
            current_bpm = current_analysis.get("tempo", 120)
            return min(
                candidates.keys(),
                key=lambda p: abs(candidates[p].get("tempo", 120) - current_bpm)
            )

        return list(candidates.keys())[0]

    def _execute_transition(self, to_path: str):
        """Execute the actual transition to the next track."""
        with self.lock:
            self.current_track = to_path
            self.history.append(to_path)

        to_analysis = self.library.get(to_path, {})
        logger.info(f"🔀 Now playing: {Path(to_path).name}")
        self._notify_transition(None, to_path, "Autonomous transition")

    def stop(self):
        """Stop the DJ set."""
        self.is_playing = False
        logger.info("⏹ DJ set stopped")

    def status(self) -> dict:
        return {
            "is_playing": self.is_playing,
            "current_track": Path(self.current_track).name if self.current_track else None,
            "library_size": len(self.library),
            "tracks_played": len(self.history),
        }

    # ── Telegram notifications ───────────────────────────────────────────────

    def _notify_transition(self, from_path, to_path, label: str):
        from bot.telegram_bot import notify
        to = self.library.get(to_path, {})
        from_name = Path(from_path).name if from_path else None
        to_name = Path(to_path).name

        msg = (
            f"🎛 *{label}*\n"
            f"{'`' + from_name + '` → ' if from_name else ''}` {to_name}`\n"
            f"🎼 {to.get('key', '?')} · "
            f"🥁 {to.get('tempo', '?'):.0f} BPM · "
            f"⚡ {to.get('energy', '?'):.2f}"
        )
        notify(msg)

    def _notify_dj_decision(self, decision: dict, chosen_name: str):
        from bot.telegram_bot import notify
        msg = (
            f"🤖 *Nemotron DJ*\n"
            f"Next: `{chosen_name}`\n"
            f"_{decision.get('reason', '')}_\n"
            f"Style: {decision.get('transition_style', 'crossfade')} · "
            f"{decision.get('energy_direction', 'maintain')}"
        )
        notify(msg)
