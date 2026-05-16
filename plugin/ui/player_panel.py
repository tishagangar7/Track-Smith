"""
In-app media playback: MP3/WAV via QMediaPlayer, MIDI via FluidSynth.
Seek, A/B compare (Original vs With Fill), combined preview.
"""

from __future__ import annotations

import time
from pathlib import Path

import mido
import fluidsynth

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QSlider, QLabel, QComboBox, QButtonGroup,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, pyqtSlot, QUrl, QTimer

try:
    from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
    _HAS_QTMULTIMEDIA = True
except ImportError:
    QMediaPlayer = None
    QAudioOutput = None
    _HAS_QTMULTIMEDIA = False

from plugin.media_info import count_midi_notes, bpm_from_midi
from plugin.midi_merge import merge_input_and_continuation
from plugin.ui.seek_slider import SeekSlider


def _find_soundfont() -> str | None:
    candidates = [
        str(Path(__file__).parents[3] / "venv" / "lib" / "python3.12" / "site-packages" / "pretty_midi" / "TimGM6mb.sf2"),
        "/opt/anaconda3/lib/python3.12/site-packages/pretty_midi/TimGM6mb.sf2",
    ]
    for p in candidates:
        if Path(p).exists():
            return p
    try:
        import pretty_midi
        sf = Path(pretty_midi.__file__).parent / "TimGM6mb.sf2"
        if sf.exists():
            return str(sf)
    except Exception:
        pass
    return None


def _fmt(sec: float) -> str:
    s = int(sec)
    return f"{s // 60}:{s % 60:02d}"


def _midi_duration_at_bpm(path: str, target_bpm: float) -> float:
    mid = mido.MidiFile(path)
    file_bpm = bpm_from_midi(path)
    scale = file_bpm / max(target_bpm, 1.0)
    base_tempo = 500_000
    for track in mid.tracks:
        for msg in track:
            if msg.type == "set_tempo":
                base_tempo = msg.tempo
                break
        else:
            continue
        break
    tpb = mid.ticks_per_beat
    total = sum(
        mido.tick2second(msg.time, tpb, base_tempo)
        for msg in mido.merge_tracks(mid.tracks)
    )
    return total * scale


class _MidiPlayerWorker(QThread):
    position = pyqtSignal(float, float)
    done = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(
        self, midi_path: str, soundfont: str, loop: bool,
        target_bpm: float, volume: float, start_sec: float = 0.0,
    ):
        super().__init__()
        self.midi_path = midi_path
        self.soundfont = soundfont
        self.loop = loop
        self.target_bpm = max(40.0, min(300.0, target_bpm))
        self.volume = max(0.0, min(1.0, volume))
        self.start_sec = max(0.0, start_sec)
        self._stop = False
        self._fs = None

    def stop(self):
        self._stop = True

    def set_volume(self, volume: float):
        self.volume = max(0.0, min(1.0, volume))
        if self._fs:
            self._fs.setting("synth.gain", max(0.05, min(2.0, self.volume * 1.25)))

    def run(self):
        try:
            self._play()
        except Exception as exc:
            self.error.emit(str(exc))

    def _play(self):
        mid = mido.MidiFile(self.midi_path)
        tpb = mid.ticks_per_beat
        us_per_beat = int(60_000_000 / self.target_bpm)
        total = _midi_duration_at_bpm(self.midi_path, self.target_bpm)
        messages = list(mido.merge_tracks(mid.tracks))

        fs = fluidsynth.Synth()
        self._fs = fs
        sfid = fs.sfload(self.soundfont)
        fs.start(driver="coreaudio")
        for ch in range(16):
            bank = 128 if ch == 9 else 0
            fs.program_select(ch, sfid, bank, 0)
        self.set_volume(self.volume)

        def _send(msg):
            if msg.type == "note_on":
                ch = getattr(msg, "channel", 0)
                if msg.velocity > 0:
                    fs.noteon(ch, msg.note, msg.velocity)
                else:
                    fs.noteoff(ch, msg.note)
            elif msg.type == "note_off":
                ch = getattr(msg, "channel", 0)
                fs.noteoff(ch, msg.note)

        try:
            while True:
                wall = 0.0
                for msg in messages:
                    delta = mido.tick2second(msg.time, tpb, us_per_beat)
                    wall += delta
                    if wall < self.start_sec:
                        _send(msg)

                play_t = self.start_sec
                wall = 0.0
                for msg in messages:
                    if self._stop:
                        return
                    delta = mido.tick2second(msg.time, tpb, us_per_beat)
                    t0, t1 = wall, wall + delta
                    wall = t1
                    if t1 <= self.start_sec:
                        continue
                    wait = delta if t0 >= self.start_sec else t1 - self.start_sec
                    if wait > 0:
                        time.sleep(wait)
                        play_t += wait
                        self.position.emit(min(play_t, total), total)
                    _send(msg)

                if not self.loop:
                    break
                self.start_sec = 0.0
                for ch in range(16):
                    for note in range(128):
                        fs.noteoff(ch, note)
        finally:
            for ch in range(16):
                for note in range(128):
                    fs.noteoff(ch, note)
            time.sleep(0.2)
            fs.delete()
            self._fs = None
        self.done.emit()


class PlayerPanel(QWidget):
    def __init__(self, output_dir: str = "plugin_output", parent=None):
        super().__init__(parent)
        self.output_dir = output_dir
        self._input_path: str | None = None
        self._input_type: str = "midi"
        self._input_bpm: float = 120.0
        self._continuation_path: str | None = None
        self._continuation_bpm: float = 120.0
        self._file_bpm: float = 120.0
        self._playback_mode: str = "combined"
        self._soundfont: str | None = None
        self._worker: QThread | None = None
        self._audio_player: QMediaPlayer | None = None
        self._audio_out: QAudioOutput | None = None
        self._sequential_midi: str | None = None
        self._sequential_target_bpm: float = 120.0
        self._sequential_volume: float = 0.8
        self._sequential_audio_dur: float = 0.0
        self._combined_total: float = 0.0
        self._fill_after_audio: bool = False
        self._fill_started: bool = False
        self._end_poll: QTimer | None = None
        self._playing_kind: str = "midi"
        self._playback_total: float = 0.0
        self._seek_offset: float = 0.0
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(6)

        header = QLabel("PLAYBACK")
        header.setObjectName("section_header")
        layout.addWidget(header)

        compare = QLabel("Compare")
        compare.setObjectName("section_header")
        layout.addWidget(compare)

        row_cmp = QHBoxLayout()
        self._mode_group = QButtonGroup(self)
        self.btn_original = QPushButton("Original")
        self.btn_with_fill = QPushButton("With Fill")
        self.btn_fill_only = QPushButton("Fill only")
        self._mode_ids = ["input_only", "combined", "continuation_only"]
        for i, (btn, mode) in enumerate([
            (self.btn_original, "input_only"),
            (self.btn_with_fill, "combined"),
            (self.btn_fill_only, "continuation_only"),
        ]):
            btn.setCheckable(True)
            btn.setObjectName("secondary")
            self._mode_group.addButton(btn, i)
            row_cmp.addWidget(btn)
        self._mode_group.idClicked.connect(self._on_mode_group)
        self.btn_with_fill.setChecked(True)
        layout.addLayout(row_cmp)

        row1 = QHBoxLayout()
        self.play_btn = QPushButton("▶  Play")
        self.play_btn.setObjectName("fl_btn")
        self.play_btn.clicked.connect(self._toggle_play)
        self.play_btn.setEnabled(False)
        row1.addWidget(self.play_btn, stretch=1)
        self.loop_btn = QPushButton("↺")
        self.loop_btn.setCheckable(True)
        self.loop_btn.setObjectName("secondary")
        self.loop_btn.setFixedWidth(36)
        row1.addWidget(self.loop_btn)
        layout.addLayout(row1)

        self.seek_slider = SeekSlider()
        self.seek_slider.seek_requested.connect(self._on_seek)
        layout.addWidget(self.seek_slider)

        self.time_label = QLabel("0:00 / 0:00")
        self.time_label.setObjectName("section_header")
        layout.addWidget(self.time_label)

        sliders_row = QHBoxLayout()
        sliders_row.setSpacing(12)

        vol_row = QHBoxLayout()
        vol_row.setSpacing(4)
        _vol_lbl = QLabel("Vol")
        _vol_lbl.setStyleSheet("color:rgba(244,237,225,0.34); font-size:10px;")
        _vol_lbl.setFixedWidth(22)
        vol_row.addWidget(_vol_lbl)
        self.vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(80)
        self.vol_slider.setFixedHeight(14)
        self.vol_slider.valueChanged.connect(self._on_vol_changed)
        vol_row.addWidget(self.vol_slider)
        self.vol_label = QLabel("80%")
        self.vol_label.setStyleSheet("color:rgba(244,237,225,0.34); font-size:10px;")
        self.vol_label.setFixedWidth(28)
        vol_row.addWidget(self.vol_label)
        sliders_row.addLayout(vol_row, stretch=1)

        bpm_row = QHBoxLayout()
        bpm_row.setSpacing(4)
        _bpm_lbl = QLabel("BPM")
        _bpm_lbl.setStyleSheet("color:rgba(244,237,225,0.34); font-size:10px;")
        _bpm_lbl.setFixedWidth(28)
        bpm_row.addWidget(_bpm_lbl)
        self.bpm_slider = QSlider(Qt.Orientation.Horizontal)
        self.bpm_slider.setRange(40, 200)
        self.bpm_slider.setValue(120)
        self.bpm_slider.setFixedHeight(14)
        self.bpm_slider.valueChanged.connect(self._on_bpm_changed)
        bpm_row.addWidget(self.bpm_slider)
        self.bpm_label = QLabel("120")
        self.bpm_label.setStyleSheet("color:rgba(244,237,225,0.34); font-size:10px;")
        self.bpm_label.setFixedWidth(28)
        bpm_row.addWidget(self.bpm_label)
        sliders_row.addLayout(bpm_row, stretch=1)

        layout.addLayout(sliders_row)

        self.mode_combo = QComboBox()
        self.mode_combo.hide()

    def current_mode(self) -> str:
        return self._playback_mode

    def _on_mode_group(self, btn_id: int):
        self._playback_mode = self._mode_ids[btn_id]
        self._update_duration_hint()

    def _update_duration_hint(self):
        total = self._estimate_total_duration()
        self._playback_total = total
        self.time_label.setText(f"0:00 / {_fmt(total)}")

    def _estimate_total_duration(self) -> float:
        mode = self._playback_mode
        target = float(self.bpm_slider.value())
        if mode == "input_only" and self._input_path:
            if self._input_type == "audio":
                try:
                    import librosa
                    rate = target / max(self._input_bpm, 1.0)
                    return float(librosa.get_duration(path=self._input_path)) / rate
                except Exception:
                    return 0.0
            return _midi_duration_at_bpm(self._input_path, target)
        if mode == "continuation_only" and self._continuation_path:
            return _midi_duration_at_bpm(self._continuation_path, target)
        if mode == "combined" and self._input_path and self._continuation_path:
            if self._input_type == "audio":
                try:
                    import librosa
                    rate = target / max(self._input_bpm, 1.0)
                    a = float(librosa.get_duration(path=self._input_path)) / rate
                except Exception:
                    a = 0.0
                return a + _midi_duration_at_bpm(self._continuation_path, target)
            merged = str(Path(self.output_dir) / "preview_merge.mid")
            if Path(merged).exists() and self._continuation_path:
                merge_input_and_continuation(
                    self._input_path, self._continuation_path, merged
                )
                return _midi_duration_at_bpm(merged, target)
        return 0.0

    def _set_bpm_slider(self, bpm: float):
        self.bpm_slider.blockSignals(True)
        self.bpm_slider.setValue(int(max(40, min(200, round(bpm)))))
        self.bpm_slider.blockSignals(False)
        self.bpm_label.setText(str(int(round(bpm))))

    def set_input(self, path: str | None, source_type: str = "midi", bpm: float = 120.0):
        self._input_path = path
        self._input_type = source_type
        self._input_bpm = bpm
        if path:
            if source_type == "midi":
                self._input_bpm = bpm_from_midi(path)
            self._set_bpm_slider(self._input_bpm)
            self.play_btn.setEnabled(True)
        self._update_mode_buttons()
        self._update_duration_hint()

    def set_continuation(self, path: str | None, bpm: float = 120.0):
        self._continuation_path = path
        if path:
            self._continuation_bpm = (
                bpm_from_midi(path) if path.lower().endswith((".mid", ".midi")) else bpm
            )
            self.play_btn.setEnabled(True)
        self._update_mode_buttons()
        self._update_duration_hint()

    def _update_mode_buttons(self):
        has_in = bool(self._input_path)
        has_cont = bool(self._continuation_path)
        self.btn_with_fill.setEnabled(has_in and has_cont)
        self.btn_original.setEnabled(has_in)
        self.btn_fill_only.setEnabled(has_cont)
        if has_in and has_cont:
            self._playback_mode = "combined"
            self.btn_with_fill.setChecked(True)
        elif has_in:
            self._playback_mode = "input_only"
            self.btn_original.setChecked(True)
        elif has_cont:
            self._playback_mode = "continuation_only"
            self.btn_fill_only.setChecked(True)

    def _resolve_playback_path(self, mode: str) -> tuple[str, str]:
        if mode == "input_only":
            if not self._input_path:
                raise ValueError("No input loaded")
            return self._input_path, self._input_type
        if mode == "continuation_only":
            if not self._continuation_path:
                raise ValueError("No continuation selected")
            return self._continuation_path, "midi"
        if not self._continuation_path:
            if self._input_path:
                return self._input_path, self._input_type
            raise ValueError("Nothing to play")
        if not self._input_path:
            return self._continuation_path, "midi"
        if self._input_type == "audio":
            return self._continuation_path, "sequential"
        merged = merge_input_and_continuation(
            self._input_path,
            self._continuation_path,
            str(Path(self.output_dir) / "preview_merge.mid"),
        )
        return merged, "midi"

    def _toggle_play(self):
        if self._worker and self._worker.isRunning():
            self._stop_worker()
        elif self._audio_player and self._audio_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._stop_audio()
        else:
            self._start_playback(self._seek_offset)

    def _on_seek(self, frac: float):
        total = self._playback_total or self._estimate_total_duration()
        if total <= 0:
            return
        self._seek_offset = frac * total
        was_playing = (
            (self._worker and self._worker.isRunning())
            or (
                self._audio_player
                and self._audio_player.playbackState()
                == QMediaPlayer.PlaybackState.PlayingState
            )
        )
        self._stop_worker(keep_sequential=True, reset_seek=False)
        if was_playing:
            self._start_playback(self._seek_offset)
        else:
            self.seek_slider.set_position_fraction(frac)
            self.time_label.setText(f"{_fmt(self._seek_offset)} / {_fmt(total)}")

    def _start_playback(self, start_sec: float = 0.0):
        mode = self._playback_mode
        try:
            path, kind = self._resolve_playback_path(mode)
        except ValueError as e:
            self.time_label.setText(str(e)[:50])
            return

        if kind == "midi" and count_midi_notes(path) == 0:
            self.time_label.setText("No notes in file to play")
            return

        self._playing_kind = kind
        self._file_bpm = bpm_from_midi(path) if kind != "audio" else self._input_bpm
        target_bpm = float(self.bpm_slider.value())
        volume = self.vol_slider.value() / 100.0
        self._playback_total = self._estimate_total_duration()

        if kind == "audio":
            self._play_audio(path, volume, target_bpm, self._file_bpm, start_sec=start_sec)
            return

        if kind == "sequential":
            if not self._continuation_path:
                self.time_label.setText("Select a continuation first")
                return
            sf = _find_soundfont()
            if not sf:
                self.time_label.setText("No soundfont — pip install pretty_midi")
                return
            try:
                import librosa
                raw_audio = float(librosa.get_duration(path=self._input_path))
            except Exception:
                raw_audio = 0.0
            rate = target_bpm / max(self._input_bpm, 1.0)
            self._sequential_audio_dur = raw_audio / max(rate, 0.01)
            midi_part = _midi_duration_at_bpm(path, target_bpm)
            self._combined_total = self._sequential_audio_dur + midi_part
            self._playback_total = self._combined_total

            if start_sec >= self._sequential_audio_dur - 0.1:
                fill_start = start_sec - self._sequential_audio_dur
                self._play_midi(path, sf, target_bpm, volume, fill_start, self._combined_total, self._sequential_audio_dur)
                return

            self._sequential_midi = path
            self._sequential_target_bpm = target_bpm
            self._sequential_volume = volume
            self._soundfont = sf
            self._fill_after_audio = True
            self._fill_started = False
            self._play_audio(
                self._input_path, volume, target_bpm, self._input_bpm,
                combined_total=self._combined_total,
                start_sec=start_sec,
            )
            return

        sf = _find_soundfont()
        if not sf:
            self.time_label.setText("No soundfont — pip install pretty_midi")
            return
        self._play_midi(path, sf, target_bpm, volume, start_sec, self._playback_total, 0.0)

    def _play_midi(self, path, sf, target_bpm, volume, start_sec, total, offset):
        self._worker = _MidiPlayerWorker(
            path, sf, self.loop_btn.isChecked(), target_bpm, volume, start_sec=start_sec,
        )

        def on_pos(elapsed, _t):
            self._on_position(elapsed + offset, total)

        self._worker.position.connect(on_pos)
        self._worker.done.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()
        self.play_btn.setText("⏹  Stop")

    def _play_audio(
        self, path: str, volume: float, target_bpm: float, file_bpm: float,
        combined_total: float | None = None, start_sec: float = 0.0,
    ):
        if not _HAS_QTMULTIMEDIA:
            self.time_label.setText("Audio playback unavailable: reinstall PyQt6")
            return
        self._stop_worker(keep_sequential=True)
        self._fill_after_audio = combined_total is not None
        self._fill_started = False
        self._pending_audio_seek_ms = int(start_sec * 1000)
        self._audio_player = QMediaPlayer()
        self._audio_out = QAudioOutput()
        self._audio_player.setAudioOutput(self._audio_out)
        self._audio_out.setVolume(volume)
        rate = target_bpm / max(file_bpm, 1.0)
        self._audio_player.setPlaybackRate(max(0.25, min(4.0, rate)))
        self._audio_player.setSource(QUrl.fromLocalFile(path))
        self._audio_player.positionChanged.connect(self._on_audio_position)
        self._audio_player.mediaStatusChanged.connect(self._on_audio_status)
        self._audio_player.playbackStateChanged.connect(self._on_audio_state)
        try:
            import librosa
            dur = float(librosa.get_duration(path=path)) / max(rate, 0.01)
        except Exception:
            dur = 0.0
        self._audio_duration = combined_total if combined_total else dur
        self._audio_only_duration = dur
        self._playback_total = self._audio_duration
        if self._fill_after_audio:
            self._end_poll = QTimer(self)
            self._end_poll.setInterval(200)
            self._end_poll.timeout.connect(self._poll_audio_end)
            self._end_poll.start()
        self._audio_player.play()
        self.play_btn.setText("⏹  Stop")

    def _on_vol_changed(self, v: int):
        self.vol_label.setText(f"{v}%")
        vol = v / 100.0
        if self._audio_out:
            self._audio_out.setVolume(vol)
        if self._worker and isinstance(self._worker, _MidiPlayerWorker) and self._worker.isRunning():
            self._worker.set_volume(vol)

    def _on_bpm_changed(self, v: int):
        self.bpm_label.setText(str(v))
        self._update_duration_hint()
        if self._audio_player and self._audio_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            file_bpm = self._input_bpm if self._playing_kind == "sequential" else self._file_bpm
            rate = v / max(file_bpm, 1.0)
            self._audio_player.setPlaybackRate(max(0.25, min(4.0, rate)))

    def _poll_audio_end(self):
        if not self._audio_player or not self._fill_after_audio or self._fill_started:
            return
        pos = self._audio_player.position() / 1000.0
        if pos >= self._audio_only_duration - 0.35:
            self._begin_fill_playback()

    def _on_audio_position(self, pos_ms: int):
        pos_sec = pos_ms / 1000.0
        total = self._playback_total or 1
        self.seek_slider.set_position_fraction(pos_sec / total)
        tag = " · input" if self._fill_after_audio else ""
        self.time_label.setText(f"{_fmt(pos_sec)} / {_fmt(total)}{tag}")
        if self._fill_after_audio and not self._fill_started and self._audio_player:
            dur_ms = self._audio_player.duration()
            if dur_ms > 0:
                at_end = pos_ms >= dur_ms - 400
            else:
                at_end = pos_sec >= self._audio_only_duration - 0.35
            if at_end:
                self._begin_fill_playback()

    def _begin_fill_playback(self):
        if self._fill_started or not self._sequential_midi or not self._soundfont:
            return
        self._fill_started = True
        if self._end_poll:
            self._end_poll.stop()
        if self._audio_player:
            self._audio_player.stop()
            self._audio_player.deleteLater()
            self._audio_player = None
        if self._audio_out:
            self._audio_out.deleteLater()
            self._audio_out = None
        midi_path = self._sequential_midi
        self._sequential_midi = None
        self._fill_after_audio = False
        audio_dur = self._sequential_audio_dur
        self._play_midi(
            midi_path, self._soundfont, self._sequential_target_bpm,
            self._sequential_volume, 0.0, self._combined_total, audio_dur,
        )

    def _on_audio_status(self, status):
        if status in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        ):
            pending = getattr(self, "_pending_audio_seek_ms", 0)
            if pending and self._audio_player:
                self._audio_player.setPosition(pending)
                self._pending_audio_seek_ms = 0
        if status == QMediaPlayer.MediaStatus.EndOfMedia and self._fill_after_audio:
            self._begin_fill_playback()

    def _on_audio_state(self, state):
        if (
            state == QMediaPlayer.PlaybackState.StoppedState
            and not self._fill_after_audio
            and not (self._worker and self._worker.isRunning())
        ):
            self.play_btn.setText("▶  Play")

    def _stop_audio(self, clear_sequential: bool = True):
        if self._end_poll:
            self._end_poll.stop()
            self._end_poll = None
        if self._audio_player:
            self._audio_player.stop()
            self._audio_player.deleteLater()
            self._audio_player = None
        if self._audio_out:
            self._audio_out.deleteLater()
            self._audio_out = None
        if clear_sequential:
            self._fill_after_audio = False
            self._sequential_midi = None
            self._fill_started = False

    def _stop_worker(self, keep_sequential: bool = False, reset_seek: bool = True):
        if self._worker and self._worker.isRunning():
            if hasattr(self._worker, "stop"):
                self._worker.stop()
            self._worker.wait(3000)
        self._worker = None
        if not keep_sequential:
            self._sequential_midi = None
            self._fill_after_audio = False
            self._fill_started = False
        self._stop_audio(clear_sequential=not keep_sequential)
        if not keep_sequential:
            self.play_btn.setText("▶  Play")
            if reset_seek:
                self._seek_offset = 0.0

    @pyqtSlot(float, float)
    def _on_position(self, elapsed: float, total: float):
        if total > 0:
            self.seek_slider.set_position_fraction(elapsed / total)
        self.time_label.setText(f"{_fmt(elapsed)} / {_fmt(total)}")

    def _on_done(self):
        self.play_btn.setText("▶  Play")
        self.seek_slider.setValue(0)
        self._seek_offset = 0.0

    def _on_error(self, err: str):
        self.play_btn.setText("▶  Play")
        self.time_label.setText(f"Error: {err[:45]}")

    def closeEvent(self, event):
        self._stop_worker()
        super().closeEvent(event)
