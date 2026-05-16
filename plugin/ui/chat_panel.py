"""
Chat panel — slash command input + scrolling response log.
Inference runs in a QThread so the UI stays responsive.
"""

import shutil
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLineEdit, QPushButton, QLabel,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QKeyEvent, QTextCursor


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

        self._build_ui()
        self._append_system(
            "Aux loaded. Commands: /fill  /vibe <text>  /suggest  /analyze  /mix  /style <artist>\n"
            "Drop a MIDI file on the left panel, then type a command."
        )

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        layout.addWidget(self.log, stretch=1)

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
            files = result.get("files", [])
            if files:
                self.files_ready.emit(files, self.output_dir)
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
        # strip the "thinking..." system line
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
