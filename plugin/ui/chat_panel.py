"""
Chat panel — slash command input + scrolling response log.
Inference runs in a QThread so the UI stays responsive.
"""

import subprocess
import sys
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLineEdit, QPushButton, QLabel,
)
from PyQt6.QtCore import Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QKeyEvent, QTextCursor

try:
    from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
    _HAS_MEDIA = True
except ImportError:
    _HAS_MEDIA = False

_AUDIO_EXTS = {".wav", ".mp3", ".aiff", ".flac", ".ogg", ".m4a"}


class _InferenceWorker(QThread):
    done = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            self.done.emit(self.fn(*self.args, **self.kwargs))
        except Exception as exc:
            self.error.emit(str(exc))


class _LoopBuildWorker(QThread):
    """Runs ffmpeg concat in background. Emits loop_path (str) or empty string on failure."""
    done = pyqtSignal(str)

    def __init__(self, original: str, fill: str, output: str):
        super().__init__()
        self.original = original
        self.fill = fill
        self.output = output

    def run(self):
        self.done.emit(_concat_audio_ffmpeg(self.original, self.fill, self.output) or "")


class ChatPanel(QWidget):
    files_ready = pyqtSignal(list, str)   # (files list, output_dir)

    def __init__(self, output_dir: str, parent=None):
        super().__init__(parent)
        self.output_dir = output_dir
        self._midi_path: str | None = None
        self._original_audio_path: str | None = None   # audio-only, for loop building
        self._style_context: str | None = None
        self._worker: _InferenceWorker | None = None
        self._loop_worker: _LoopBuildWorker | None = None
        self._history: list[str] = []
        self._hist_idx: int = -1
        self._latest_audio: str | None = None
        self._full_loop_audio: str | None = None

        if _HAS_MEDIA:
            self._audio_output = QAudioOutput()
            self._player = QMediaPlayer()
            self._player.setAudioOutput(self._audio_output)
            self._loop_audio_output = QAudioOutput()
            self._loop_player = QMediaPlayer()
            self._loop_player.setAudioOutput(self._loop_audio_output)
        else:
            self._player = None
            self._audio_output = None
            self._loop_player = None
            self._loop_audio_output = None

        self._build_ui()
        self._append_system(
            "Aux loaded. Commands: /fill  /vibe <text>  /suggest  /analyze  /mix  /stems  /style <artist>\n"
            "Drop MIDI or MP3 on the left, then type a command."
        )

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        layout.addWidget(self.log, stretch=1)

        # ── Fill audio bar (hidden until fill audio available) ─────────────────
        self._audio_bar = QWidget()
        audio_row = QHBoxLayout(self._audio_bar)
        audio_row.setContentsMargins(0, 0, 0, 0)
        audio_row.setSpacing(6)

        self._lbl_audio = QLabel("No audio")
        self._lbl_audio.setStyleSheet("color:#6ac8ff; font-size:11px;")
        audio_row.addWidget(self._lbl_audio, stretch=1)

        self._btn_play = QPushButton("▶ Play Fill")
        self._btn_play.setFixedWidth(84)
        self._btn_play.clicked.connect(self._toggle_play_fill)
        audio_row.addWidget(self._btn_play)

        self._btn_open_folder = QPushButton("Open Folder")
        self._btn_open_folder.setFixedWidth(90)
        self._btn_open_folder.clicked.connect(self._open_audio_folder)
        audio_row.addWidget(self._btn_open_folder)

        self._btn_stems = QPushButton("Separate Stems")
        self._btn_stems.setFixedWidth(110)
        self._btn_stems.clicked.connect(self._separate_stems)
        audio_row.addWidget(self._btn_stems)

        self._audio_bar.setVisible(False)
        layout.addWidget(self._audio_bar)

        # ── Full loop bar (hidden until loop is built) ─────────────────────────
        self._loop_bar = QWidget()
        loop_row = QHBoxLayout(self._loop_bar)
        loop_row.setContentsMargins(0, 0, 0, 0)
        loop_row.setSpacing(6)

        self._lbl_loop = QLabel("Building loop...")
        self._lbl_loop.setStyleSheet("color:#00d4aa; font-size:11px;")
        loop_row.addWidget(self._lbl_loop, stretch=1)

        self._btn_play_loop = QPushButton("▶ Play Full Loop")
        self._btn_play_loop.setFixedWidth(120)
        self._btn_play_loop.clicked.connect(self._toggle_play_loop)
        loop_row.addWidget(self._btn_play_loop)

        self._loop_bar.setVisible(False)
        layout.addWidget(self._loop_bar)

        # ── Command input row ──────────────────────────────────────────────────
        row = QHBoxLayout()
        row.setSpacing(6)

        self.input = QLineEdit()
        self.input.setPlaceholderText("/fill  or  /vibe dark trap 808s  ...")
        self.input.returnPressed.connect(self.send)
        row.addWidget(self.input, stretch=1)

        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self.send)
        row.addWidget(self.send_btn)

        layout.addLayout(row)

    # ── public API ────────────────────────────────────────────────────────────

    def set_midi_path(self, path: str):
        self._midi_path = path
        self._original_audio_path = path if Path(path).suffix.lower() in _AUDIO_EXTS else None
        self._append_system(f"Loaded: {Path(path).name}")

    def set_output_dir(self, output_dir: str):
        self.output_dir = output_dir

    # ── fill audio controls ───────────────────────────────────────────────────

    def _set_audio(self, audio_path: str | None):
        self._latest_audio = audio_path
        if not audio_path:
            self._audio_bar.setVisible(False)
            return

        self._audio_bar.setVisible(True)
        self._lbl_audio.setText(Path(audio_path).name)
        self._btn_play.setText("▶ Play Fill")

        if self._player:
            self._player.setSource(QUrl.fromLocalFile(audio_path))
        if not _HAS_MEDIA:
            self._btn_play.setToolTip("PyQt6.QtMultimedia not installed — use Open Folder to play manually")

    def _toggle_play_fill(self):
        if not self._latest_audio:
            return
        if self._player:
            if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self._player.pause()
                self._btn_play.setText("▶ Play Fill")
            else:
                self._player.play()
                self._btn_play.setText("⏸ Pause Fill")
        else:
            _open_with_system(self._latest_audio)

    # ── full loop controls ────────────────────────────────────────────────────

    def _set_full_loop(self, loop_path: str | None, label: str = "Original → Fill"):
        self._full_loop_audio = loop_path
        if not loop_path:
            self._loop_bar.setVisible(False)
            return

        self._loop_bar.setVisible(True)
        self._lbl_loop.setText(label)
        self._btn_play_loop.setText("▶ Play Full Loop")

        if self._loop_player:
            self._loop_player.setSource(QUrl.fromLocalFile(loop_path))

    def _toggle_play_loop(self):
        if not self._full_loop_audio:
            return
        if self._loop_player:
            if self._loop_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self._loop_player.pause()
                self._btn_play_loop.setText("▶ Play Full Loop")
            else:
                self._loop_player.play()
                self._btn_play_loop.setText("⏸ Pause Loop")
        else:
            _open_with_system(self._full_loop_audio)

    def _start_loop_build(self, original: str, fill: str):
        """Start ffmpeg concat in background. Shows loop bar when done."""
        out_path = str(Path(self.output_dir) / "full_loop.wav")
        self._loop_bar.setVisible(True)
        self._lbl_loop.setText("Building full loop...")
        self._btn_play_loop.setEnabled(False)

        self._loop_worker = _LoopBuildWorker(original, fill, out_path)
        self._loop_worker.done.connect(self._on_loop_built)
        self._loop_worker.start()

    def _on_loop_built(self, loop_path: str):
        self._btn_play_loop.setEnabled(True)
        if not loop_path:
            self._loop_bar.setVisible(False)
            return
        orig_dur = _audio_duration_s(self._original_audio_path or "")
        fill_dur = _audio_duration_s(self._latest_audio or "")
        label = f"Original ({orig_dur}s) → Fill ({fill_dur}s)"
        self._set_full_loop(loop_path, label)

    # ── other audio controls ──────────────────────────────────────────────────

    def _open_audio_folder(self):
        target = self._latest_audio or (self.output_dir if self.output_dir else None)
        if not target:
            return
        _open_with_system(str(Path(target).parent))

    def _separate_stems(self):
        target = self._latest_audio or self._midi_path
        if not target:
            self._append_error("No audio loaded. Run /fill first to generate audio.")
            return
        path = Path(target)
        if path.suffix.lower() not in _AUDIO_EXTS:
            self._append_error(
                f"Stem separation needs audio (WAV/MP3), not {path.suffix}.\n"
                "Run /fill first — audio generates when DGX audio server is online."
            )
            return
        self._dispatch_stems(str(path))

    def _dispatch_stems(self, audio_path: str):
        from plugin.commands.stems import run as stems_run

        self._set_busy(True)
        self._append_system(f"Separating stems from {Path(audio_path).name}...")

        self._worker = _InferenceWorker(stems_run, audio_path, self.output_dir)
        self._worker.done.connect(self._on_result)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(lambda: self._set_busy(False))
        self._worker.start()

    # ── input handling ────────────────────────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Up:
            self._nav_history(-1)
        elif event.key() == Qt.Key.Key_Down:
            self._nav_history(1)
        else:
            super().keyPressEvent(event)

    def _nav_history(self, direction: int):
        if not self._history:
            return
        self._hist_idx = max(0, min(len(self._history) - 1, self._hist_idx + direction))
        self.input.setText(self._history[self._hist_idx])

    def send(self):
        text = self.input.text().strip()
        if not text:
            return
        if self._worker and self._worker.isRunning():
            self._append_system("Still processing — please wait...")
            return

        self._history.insert(0, text)
        self._hist_idx = -1
        self.input.clear()
        self._append_user(text)
        self._dispatch(text)

    def _dispatch(self, raw: str):
        from plugin.commands.router import route

        self._set_busy(True)
        self._append_system("thinking...")

        self._worker = _InferenceWorker(
            route,
            raw,
            self._midi_path,
            self._style_context,
            self.output_dir,
        )
        self._worker.done.connect(self._on_result)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(lambda: self._set_busy(False))
        self._worker.start()

    # ── result handling ───────────────────────────────────────────────────────

    def _on_result(self, result: dict):
        self._remove_thinking()
        rtype = result.get("type", "text")
        msg = result.get("message", "")

        if rtype == "error":
            self._append_error(msg)
        elif rtype == "style":
            self._style_context = result.get("style")
            self._append_aux(msg)
        elif rtype == "files":
            self._append_aux(msg)
            audio_path = result.get("audio_path")
            self._set_audio(audio_path)
            # Build full loop if we have both original audio and fill audio
            if audio_path and self._original_audio_path:
                self._start_loop_build(self._original_audio_path, audio_path)
            files = result.get("files", [])
            if files:
                self.files_ready.emit(files, self.output_dir)
            self._append_policy_log()
        elif rtype == "stems":
            self._append_aux(msg)
            stems_dir = result.get("stems_dir", "")
            if stems_dir:
                self._append_system(f"Stems saved to: {stems_dir}")
        else:
            self._append_aux(msg)

    def _on_error(self, err: str):
        self._remove_thinking()
        self._append_error(f"Error: {err}")

    # ── log helpers ───────────────────────────────────────────────────────────

    def _append_user(self, text: str):
        self._raw(f'<p style="color:#dde1e7; margin:4px 0"><b style="color:#00d4aa">you</b>&nbsp; {_esc(text)}</p>')

    def _append_aux(self, text: str):
        body = _esc(text).replace("\n", "<br>")
        self._raw(f'<p style="color:#aab0bb; margin:4px 0"><b style="color:#6ac8ff">aux</b>&nbsp; {body}</p>')

    def _append_system(self, text: str):
        body = _esc(text).replace("\n", "<br>")
        self._raw(f'<p style="color:#555770; font-size:11px; margin:2px 0">{body}</p>')

    def _append_error(self, text: str):
        body = _esc(text).replace("\n", "<br>")
        self._raw(f'<p style="color:#ff6b6b; margin:4px 0"><b>error</b>&nbsp; {body}</p>')

    def _append_policy_log(self):
        from agent.openclaw_client import openclaw
        entries = openclaw.get_recent_log(5)
        if not entries:
            return
        lines = []
        for e in entries:
            icon = "✅" if e["status"] == "allowed" else "🚫"
            label = e["status"].upper()
            detail = f" ({_esc(e['detail'])})" if e.get("detail") else ""
            lines.append(
                f'{icon} <span style="color:#888">{label}</span>'
                f'&nbsp; {_esc(e["action"])} → {_esc(e["resource"])}{detail}'
            )
        body = "<br>".join(lines)
        self._raw(
            f'<p style="color:#666; font-size:10px; margin:6px 0 2px 0">'
            f'<b style="color:#555">Agent Activity</b><br>{body}</p>'
        )

    def _remove_thinking(self):
        html = self.log.toHtml()
        idx = html.rfind("thinking...")
        if idx != -1:
            p_start = html.rfind("<p", 0, idx)
            p_end = html.find("</p>", idx) + 4
            if p_start != -1 and p_end > 4:
                html = html[:p_start] + html[p_end:]
                self.log.setHtml(html)
                cursor = self.log.textCursor()
                cursor.movePosition(QTextCursor.MoveOperation.End)
                self.log.setTextCursor(cursor)

    def _raw(self, html: str):
        self.log.moveCursor(QTextCursor.MoveOperation.End)
        self.log.insertHtml(html)
        self.log.moveCursor(QTextCursor.MoveOperation.End)

    def _set_busy(self, busy: bool):
        self.input.setEnabled(not busy)
        self.send_btn.setEnabled(not busy)
        self.send_btn.setText("..." if busy else "Send")


# ── module-level helpers ──────────────────────────────────────────────────────

def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
    )


def _open_with_system(path: str):
    if sys.platform == "darwin":
        subprocess.Popen(["open", path])
    elif sys.platform == "win32":
        subprocess.Popen(["explorer", path])
    else:
        subprocess.Popen(["xdg-open", path])


def _concat_audio_ffmpeg(original: str, fill: str, output: str) -> str | None:
    """
    Concatenate two audio files end-to-end using ffmpeg.
    Returns output path on success, None on any failure (including ffmpeg missing).
    """
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", original,
                "-i", fill,
                "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1",
                output,
            ],
            capture_output=True,
            timeout=60,
        )
        if result.returncode == 0 and Path(output).exists():
            return output
        return None
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def _audio_duration_s(path: str) -> str:
    """Best-effort audio duration in seconds as a string."""
    if not path or not Path(path).exists():
        return "?"
    # WAV: use stdlib wave
    if path.lower().endswith(".wav"):
        try:
            import wave
            with wave.open(path) as wf:
                return str(round(wf.getnframes() / wf.getframerate(), 1))
        except Exception:
            pass
    # Other formats: try mutagen (already a dependency)
    try:
        from mutagen import File as MutagenFile
        f = MutagenFile(path)
        if f and hasattr(f, "info"):
            return str(round(f.info.length, 1))
    except Exception:
        pass
    return "?"
