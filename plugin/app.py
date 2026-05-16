"""
TrackSmith — desktop companion app.

Layout:
  Left  (440px): Chat panel — wordmark, session pill, messages, composer
  Right (flex):  Node canvas — transport, dot-grid blocks, drop zone,
                               player panel, FL export
"""
from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QSplitter, QPushButton, QMessageBox,
    QComboBox, QFileDialog, QFrame,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, pyqtSlot

from plugin.ui.media_drop_zone import MediaDropZone
from plugin.ui.chat_panel import ChatPanel
from plugin.ui.player_panel import PlayerPanel
from plugin.ui.node_canvas import NodeCanvas
from plugin.media_info import count_midi_notes
from plugin import iac


class _IACWorker(QThread):
    done = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, midi_path: str, port_name: str, use_fl_script: bool = True):
        super().__init__()
        self.midi_path = midi_path
        self.port_name = port_name
        self.use_fl_script = use_fl_script

    def run(self):
        try:
            if self.use_fl_script:
                path = iac.send_command(self.midi_path)
                self.done.emit(f"command written → {path}")
            else:
                iac.send_to_iac(self.midi_path, self.port_name)
                self.done.emit("streamed via IAC")
        except Exception as exc:
            self.error.emit(str(exc))


class _AnalyzeWorker(QThread):
    done = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, path: str):
        super().__init__()
        self.path = path

    def run(self):
        try:
            from agent.skills.input_analyzer import analyze_input
            self.done.emit(analyze_input(self.path))
        except Exception as e:
            self.error.emit(str(e))


class TrackSmithApp(QMainWindow):
    def __init__(self, output_dir: str):
        super().__init__()
        self.output_dir = output_dir
        self._input_path: str | None = None
        self._input_type: str = "midi"
        self._input_bpm: float = 120.0
        self._analyze_worker: _AnalyzeWorker | None = None
        self._iac_worker: _IACWorker | None = None

        self.setWindowTitle("tracksmith")
        self.resize(1080, 700)
        self.setMinimumSize(800, 520)

        Path(output_dir).mkdir(exist_ok=True)
        self._build_ui()
        self._apply_style()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)
        root.addWidget(splitter)

        # ── Left: Chat ────────────────────────────────────────────────────────
        self.chat = ChatPanel(output_dir=self.output_dir)
        self.chat.setMinimumWidth(380)
        self.chat.setMaximumWidth(480)
        self.chat.files_ready.connect(self._on_files_ready)
        splitter.addWidget(self.chat)

        # ── Right: canvas + player + FL export ───────────────────────────────
        right = QWidget()
        right.setMinimumWidth(420)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        # Drop zone row (just above canvas)
        drop_row = QWidget()
        drop_row.setFixedHeight(76)
        drop_row.setObjectName("transport_bar")
        dl = QHBoxLayout(drop_row)
        dl.setContentsMargins(20, 10, 20, 10)
        self.drop_zone = MediaDropZone()
        self.drop_zone.file_loaded.connect(self._on_media_loaded)
        dl.addWidget(self.drop_zone, stretch=1)
        right_layout.addWidget(drop_row)

        # Node canvas (transport bar + dot-grid blocks)
        self.canvas = NodeCanvas()
        self.canvas.file_selected.connect(self._on_canvas_file_selected)
        self.canvas.command_triggered.connect(self._on_canvas_command)
        self.chat.command_started.connect(self.canvas.set_active_command)
        right_layout.addWidget(self.canvas, stretch=1)

        # Audio preview panel (built in ChatPanel, displayed here)
        right_layout.addWidget(self.chat._audio_bar)

        # Player panel
        sep = QFrame()
        sep.setObjectName("separator")
        sep.setFixedHeight(1)
        right_layout.addWidget(sep)

        self.player = PlayerPanel(output_dir=self.output_dir)
        right_layout.addWidget(self.player)

        # FL export row
        fl_row = QWidget()
        fl_row.setObjectName("fl_bar")
        fl_row.setFixedHeight(56)
        fll = QHBoxLayout(fl_row)
        fll.setContentsMargins(16, 10, 16, 10)
        fll.setSpacing(8)

        self.port_selector = QComboBox()
        ports = iac.list_ports()
        if ports:
            self.port_selector.addItems(ports)
            if iac.DEFAULT_PORT in ports:
                self.port_selector.setCurrentText(iac.DEFAULT_PORT)
        else:
            self.port_selector.addItem("No IAC ports")
            self.port_selector.setEnabled(False)
        self.port_selector.setMaximumWidth(140)
        fll.addWidget(self.port_selector)

        self.fl_script_toggle = QComboBox()
        self.fl_script_toggle.addItem("Ghost produce (FL script)", True)
        self.fl_script_toggle.addItem("Raw stream (IAC fallback)", False)
        self.fl_script_toggle.setMaximumWidth(160)
        fll.addWidget(self.fl_script_toggle)

        self.fl_btn = QPushButton("→ Send to FL Studio")
        self.fl_btn.setObjectName("fl_btn_primary")
        self.fl_btn.clicked.connect(self._send_selected_to_fl)
        fll.addWidget(self.fl_btn, stretch=1)

        self.dl_fill_btn = QPushButton("↓ Fill")
        self.dl_fill_btn.setObjectName("fl_btn")
        self.dl_fill_btn.clicked.connect(self._download_fill)
        self.dl_fill_btn.setEnabled(False)
        fll.addWidget(self.dl_fill_btn)

        self.dl_merged_btn = QPushButton("↓ Merged")
        self.dl_merged_btn.setObjectName("fl_btn")
        self.dl_merged_btn.clicked.connect(self._download_merged)
        self.dl_merged_btn.setEnabled(False)
        fll.addWidget(self.dl_merged_btn)

        right_layout.addWidget(fl_row)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

    def _apply_style(self):
        qss_path = Path(__file__).parent / "ui" / "styles.qss"
        if qss_path.exists():
            self.setStyleSheet(qss_path.read_text())

    # ── slots ─────────────────────────────────────────────────────────────────

    @pyqtSlot(str, str)
    def _on_media_loaded(self, path: str, source_type: str):
        self._input_path = path
        self._input_type = source_type
        self.chat.set_midi_path(path)
        self.canvas.set_file_loaded(Path(path).stem[:28])
        self.canvas.clear()

        self.player.set_input(path, source_type=source_type, bpm=self._input_bpm)
        self.player.set_continuation(None)
        self._update_download_buttons()

        if source_type == "midi" and count_midi_notes(path) == 0:
            self.chat._append_system(
                "Warning: MIDI has no notes — /fill will be blocked.\n"
                "Export from FL piano roll with notes, or drop an MP3 instead."
            )
        elif source_type == "audio":
            self.chat._append_system("Audio loaded — /fill will analyze tempo and key from the file.")

        self._analyze_worker = _AnalyzeWorker(path)
        self._analyze_worker.done.connect(self._on_analyze_done)
        self._analyze_worker.error.connect(lambda e: self.chat._append_system(f"Analyze: {e}"))
        self._analyze_worker.start()

    def _on_analyze_done(self, analysis: dict):
        self._input_bpm = float(analysis.get("tempo", 120))
        key = analysis.get("key", "")
        bpm = int(self._input_bpm)
        self.chat.set_session(
            name=Path(self._input_path).stem[:24] if self._input_path else "",
            key=key,
            bpm=bpm,
        )
        if self._input_path:
            self.player.set_input(self._input_path, source_type=self._input_type, bpm=self._input_bpm)

        # Update transport with duration
        dur = float(analysis.get("duration", 0))
        if dur > 0:
            mins, secs = divmod(int(dur), 60)
            dur_str = f"{mins}:{secs:02d}" if mins else f"{dur:.1f}s"
            stem = Path(self._input_path).stem[:28] if self._input_path else ""
            self.canvas.set_file_loaded(stem, duration=dur_str)
            self.canvas.set_time("0:00", f"{mins}:{secs:02d}" if mins else f"0:{int(dur):02d}")

    @pyqtSlot(str)
    def _on_canvas_command(self, cmd: str):
        self.chat.input.setText(cmd)
        self.chat.send()

    @pyqtSlot(str, float)
    def _on_canvas_file_selected(self, path: str, bpm: float):
        if path and Path(path).exists():
            self.player.set_continuation(path, bpm=bpm)
        self._update_download_buttons()

    @pyqtSlot(list, str)
    def _on_files_ready(self, files: list, output_dir: str):
        self.canvas.set_files(files)
        if files:
            first = files[0]
            path = first.get("filepath", "")
            bpm = float(first.get("tempo") or 120)
            if path and Path(path).exists():
                self.player.set_continuation(path, bpm=bpm)
            self._update_download_buttons()
            self.chat._append_system(
                "Click a block on the canvas to preview it, then → Send to FL Studio."
            )

    def _update_download_buttons(self):
        has_cont = bool(self.player._continuation_path)
        self.dl_fill_btn.setEnabled(has_cont)
        can_merge = bool(has_cont and self._input_path and self._input_type == "midi")
        self.dl_merged_btn.setEnabled(can_merge)

    def _download_fill(self):
        path = self.player._continuation_path
        if not path:
            return
        dest, _ = QFileDialog.getSaveFileName(self, "Download fill", Path(path).name, "MIDI files (*.mid)")
        if dest:
            from plugin.export import export_continuation
            export_continuation(path, dest)
            self.chat._append_system(f"Saved → {dest}")

    def _download_merged(self):
        if not self._input_path or not self.player._continuation_path:
            return
        dest, _ = QFileDialog.getSaveFileName(self, "Download merged", "tracksmith_merged.mid", "MIDI files (*.mid)")
        if dest:
            from plugin.export import export_merged_preview
            export_merged_preview(self._input_path, self.player._continuation_path, dest, self._input_type)
            self.chat._append_system(f"Saved merged → {dest}")

    def _send_selected_to_fl(self):
        f = self.canvas.selected_file()
        if not f:
            QMessageBox.information(self, "Nothing selected", "Click a block on the canvas first.")
            return
        src = f.get("filepath", "")
        if not src or not Path(src).exists():
            QMessageBox.warning(self, "File not found", f"Cannot find:\n{src}")
            return
        if self._iac_worker and self._iac_worker.isRunning():
            QMessageBox.information(self, "Busy", "Already streaming — wait for it to finish.")
            return

        port_name = self.port_selector.currentText()
        use_fl_script = self.fl_script_toggle.currentData()
        self._iac_worker = _IACWorker(src, port_name, use_fl_script=use_fl_script)
        self._iac_worker.done.connect(lambda m: self.chat._append_system(f"Sent to FL Studio ({m})."))
        self._iac_worker.error.connect(lambda e: QMessageBox.warning(self, "FL Studio Error", f"Failed:\n{e}"))
        self._iac_worker.finished.connect(lambda: self._set_fl_btn_busy(False))
        self._iac_worker.start()
        self._set_fl_btn_busy(True)

    def _set_fl_btn_busy(self, busy: bool):
        self.fl_btn.setEnabled(not busy)
        self.fl_btn.setText("Writing…" if busy else "→ Send to FL Studio")


# backward-compat alias
AuxApp = TrackSmithApp
