"""
In-app MIDI playback panel.
Uses fluidsynth (CoreAudio) + TimGM6mb soundfont — no DAW required.
"""

import time
import mido
import fluidsynth
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QSlider, QLabel, QProgressBar,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, pyqtSlot

SOUNDFONT = str(Path(__file__).parents[3] / "venv" / "lib" / "python3.12" / "site-packages" / "pretty_midi" / "TimGM6mb.sf2")

# Fallback paths
_SF2_CANDIDATES = [
    SOUNDFONT,
    "/opt/anaconda3/lib/python3.12/site-packages/pretty_midi/TimGM6mb.sf2",
    "/opt/homebrew/Cellar/fluid-synth/2.5.4/share/fluid-synth/sf2/VintageDreamsWaves-v2.sf2",
]


def _find_soundfont() -> str:
    for p in _SF2_CANDIDATES:
        if Path(p).exists():
            return p
    raise FileNotFoundError("No soundfont (.sf2) found. Install pretty_midi: pip install pretty_midi")


# ── Playback worker ───────────────────────────────────────────────────────────

class _PlayerWorker(QThread):
    position = pyqtSignal(float, float)   # (elapsed_sec, total_sec)
    done     = pyqtSignal()
    error    = pyqtSignal(str)

    def __init__(self, midi_path: str, soundfont: str, loop: bool,
                 bpm_scale: float, volume: float):
        super().__init__()
        self.midi_path  = midi_path
        self.soundfont  = soundfont
        self.loop       = loop
        self.bpm_scale  = bpm_scale   # user_bpm / original_bpm
        self.volume     = volume      # 0.0 – 1.0
        self._stop      = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            self._play()
        except Exception as exc:
            self.error.emit(str(exc))

    def _play(self):
        sf2 = self.soundfont
        mid = mido.MidiFile(self.midi_path)

        # Pre-calculate total duration at the scaled tempo
        base_tempo = 500_000  # 120 BPM default
        for track in mid.tracks:
            for msg in track:
                if msg.type == "set_tempo":
                    base_tempo = msg.tempo
                    break
            else:
                continue
            break

        tpb   = mid.ticks_per_beat
        total = sum(
            mido.tick2second(msg.time, tpb, base_tempo)
            for msg in mido.merge_tracks(mid.tracks)
        ) / self.bpm_scale

        # Init synth
        fs   = fluidsynth.Synth()
        sfid = fs.sfload(sf2)
        fs.start(driver="coreaudio")

        # Load GM presets for all 16 channels
        for ch in range(16):
            bank = 128 if ch == 9 else 0
            fs.program_select(ch, sfid, bank, 0)

        # Set master volume
        gain = max(0.1, min(2.0, self.volume * 2.0))
        fs.setting("synth.gain", gain)

        elapsed   = 0.0
        cur_tempo = base_tempo

        try:
            while True:
                for msg in mido.merge_tracks(mid.tracks):
                    if self._stop:
                        return

                    delta = mido.tick2second(msg.time, tpb, cur_tempo) / self.bpm_scale
                    if delta > 0:
                        time.sleep(delta)
                        elapsed += delta
                        self.position.emit(min(elapsed, total), total)

                    if msg.type == "set_tempo":
                        cur_tempo = msg.tempo

                    elif msg.type == "note_on":
                        ch  = getattr(msg, "channel", 0)
                        vel = int(msg.velocity * self.volume)
                        if vel > 0:
                            fs.noteon(ch, msg.note, vel)
                        else:
                            fs.noteoff(ch, msg.note)

                    elif msg.type == "note_off":
                        ch = getattr(msg, "channel", 0)
                        fs.noteoff(ch, msg.note)

                if not self.loop:
                    break

                # reset for next loop
                elapsed   = 0.0
                cur_tempo = base_tempo
                for ch in range(16):
                    for note in range(128):
                        fs.noteoff(ch, note)

        finally:
            for ch in range(16):
                for note in range(128):
                    fs.noteoff(ch, note)
            time.sleep(0.3)
            fs.delete()

        self.done.emit()


# ── Player panel widget ───────────────────────────────────────────────────────

class PlayerPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._midi_path: str | None = None
        self._worker: _PlayerWorker | None = None
        self._soundfont = _find_soundfont()
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(6)

        header = QLabel("PLAYBACK")
        header.setObjectName("section_header")
        layout.addWidget(header)

        # ── play / loop row ───────────────────────────────────────────────────
        row1 = QHBoxLayout()

        self.play_btn = QPushButton("▶  Play")
        self.play_btn.setObjectName("fl_btn")
        self.play_btn.clicked.connect(self._toggle_play)
        self.play_btn.setEnabled(False)
        row1.addWidget(self.play_btn, stretch=1)

        self.loop_btn = QPushButton("↺")
        self.loop_btn.setCheckable(True)
        self.loop_btn.setObjectName("secondary")
        self.loop_btn.setToolTip("Loop")
        self.loop_btn.setFixedWidth(36)
        row1.addWidget(self.loop_btn)

        layout.addLayout(row1)

        # ── progress bar ──────────────────────────────────────────────────────
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        layout.addWidget(self.progress)

        self.time_label = QLabel("0:00 / 0:00")
        self.time_label.setObjectName("section_header")
        layout.addWidget(self.time_label)

        # ── volume ────────────────────────────────────────────────────────────
        vol_row = QHBoxLayout()
        vol_row.addWidget(QLabel("Vol"))
        self.vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(80)
        vol_row.addWidget(self.vol_slider, stretch=1)
        self.vol_label = QLabel("80%")
        self.vol_label.setFixedWidth(34)
        self.vol_slider.valueChanged.connect(lambda v: self.vol_label.setText(f"{v}%"))
        vol_row.addWidget(self.vol_label)
        layout.addLayout(vol_row)

        # ── tempo ─────────────────────────────────────────────────────────────
        bpm_row = QHBoxLayout()
        bpm_row.addWidget(QLabel("BPM"))
        self.bpm_slider = QSlider(Qt.Orientation.Horizontal)
        self.bpm_slider.setRange(60, 200)
        self.bpm_slider.setValue(120)
        bpm_row.addWidget(self.bpm_slider, stretch=1)
        self.bpm_label = QLabel("120")
        self.bpm_label.setFixedWidth(34)
        self.bpm_slider.valueChanged.connect(lambda v: self.bpm_label.setText(str(v)))
        bpm_row.addWidget(self.bpm_label)
        layout.addLayout(bpm_row)

    # ── public API ────────────────────────────────────────────────────────────

    def load(self, midi_path: str, original_bpm: float = 120.0):
        self._stop_worker()
        self._midi_path     = midi_path
        self._original_bpm  = original_bpm
        self.bpm_slider.setValue(int(original_bpm))
        self.play_btn.setEnabled(True)
        self.play_btn.setText("▶  Play")
        self.progress.setValue(0)
        self.time_label.setText("0:00 / 0:00")

    # ── internal ──────────────────────────────────────────────────────────────

    def _toggle_play(self):
        if self._worker and self._worker.isRunning():
            self._stop_worker()
        else:
            self._start_playback()

    def _start_playback(self):
        if not self._midi_path:
            return

        original_bpm = getattr(self, "_original_bpm", 120.0)
        user_bpm     = self.bpm_slider.value()
        bpm_scale    = user_bpm / original_bpm
        volume       = self.vol_slider.value() / 100.0

        self._worker = _PlayerWorker(
            self._midi_path, self._soundfont,
            loop=self.loop_btn.isChecked(),
            bpm_scale=bpm_scale,
            volume=volume,
        )
        self._worker.position.connect(self._on_position)
        self._worker.done.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

        self.play_btn.setText("⏹  Stop")

    def _stop_worker(self):
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait(2000)
        self._worker = None
        self.play_btn.setText("▶  Play")

    @pyqtSlot(float, float)
    def _on_position(self, elapsed: float, total: float):
        pct = int((elapsed / total) * 1000) if total > 0 else 0
        self.progress.setValue(pct)
        self.time_label.setText(f"{_fmt(elapsed)} / {_fmt(total)}")

    def _on_done(self):
        self.play_btn.setText("▶  Play")
        self.progress.setValue(0)
        self.time_label.setText("0:00 / 0:00")

    def _on_error(self, err: str):
        self.play_btn.setText("▶  Play")
        self.time_label.setText(f"Error: {err[:40]}")

    def closeEvent(self, event):
        self._stop_worker()
        super().closeEvent(event)


def _fmt(sec: float) -> str:
    s = int(sec)
    return f"{s // 60}:{s % 60:02d}"
