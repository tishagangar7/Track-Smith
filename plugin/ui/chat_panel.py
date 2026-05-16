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


class ChatPanel(QWidget):
    files_ready = pyqtSignal(list, str)   # (files list, output_dir)

    def __init__(self, output_dir: str, parent=None):
        super().__init__(parent)
        self.output_dir = output_dir
        self._midi_path: str | None = None
        self._style_context: str | None = None
        self._worker: _InferenceWorker | None = None
        self._history: list[str] = []
        self._hist_idx: int = -1
        self._latest_audio: str | None = None

        if _HAS_MEDIA:
            self._audio_output = QAudioOutput()
            self._player = QMediaPlayer()
            self._player.setAudioOutput(self._audio_output)
        else:
            self._player = None
            self._audio_output = None

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

        # ── Audio bar (hidden until audio is available) ────────────────────────
        self._audio_bar = QWidget()
        audio_row = QHBoxLayout(self._audio_bar)
        audio_row.setContentsMargins(0, 0, 0, 0)
        audio_row.setSpacing(6)

        self._lbl_audio = QLabel("No audio")
        self._lbl_audio.setStyleSheet("color:#6ac8ff; font-size:11px;")
        audio_row.addWidget(self._lbl_audio, stretch=1)

        self._btn_play = QPushButton("▶ Play")
        self._btn_play.setFixedWidth(72)
        self._btn_play.clicked.connect(self._toggle_play)
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
        self._append_system(f"Loaded: {Path(path).name}")

    def set_output_dir(self, output_dir: str):
        self.output_dir = output_dir

    # ── audio controls ────────────────────────────────────────────────────────

    def _set_audio(self, audio_path: str | None):
        self._latest_audio = audio_path
        if not audio_path:
            self._audio_bar.setVisible(False)
            return

        self._audio_bar.setVisible(True)
        self._lbl_audio.setText(Path(audio_path).name)
        self._btn_play.setText("▶ Play")

        if self._player:
            self._player.setSource(QUrl.fromLocalFile(audio_path))

        if not _HAS_MEDIA:
            self._btn_play.setToolTip("PyQt6.QtMultimedia not installed — use Open Folder to play manually")

    def _toggle_play(self):
        if not self._latest_audio:
            return

        if self._player:
            if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self._player.pause()
                self._btn_play.setText("▶ Play")
            else:
                self._player.play()
                self._btn_play.setText("⏸ Pause")
        else:
            # Fallback: open with system default player
            _open_with_system(self._latest_audio)

    def _open_audio_folder(self):
        target = self._latest_audio or (self.output_dir if self.output_dir else None)
        if not target:
            return
        folder = str(Path(target).parent)
        _open_with_system(folder)

    def _separate_stems(self):
        target = self._latest_audio or self._midi_path
        if not target:
            self._append_error("No audio loaded. Run /fill first to generate audio.")
            return

        path = Path(target)
        audio_exts = {".wav", ".mp3", ".aiff", ".flac", ".ogg", ".m4a"}
        if path.suffix.lower() not in audio_exts:
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
            # Update audio bar if audio was generated
            audio_path = result.get("audio_path")
            self._set_audio(audio_path)
            files = result.get("files", [])
            if files:
                self.files_ready.emit(files, self.output_dir)
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
