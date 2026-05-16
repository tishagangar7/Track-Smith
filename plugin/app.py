"""
Aux plugin companion app — main window.

Layout:
  Left panel:  MIDI drop zone + output file list
  Right panel: Chat panel (slash commands)
"""

from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QSplitter, QListWidget, QListWidgetItem,
    QPushButton, QApplication, QMessageBox, QComboBox,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, pyqtSlot

from plugin.ui.midi_drop_zone import MidiDropZone
from plugin.ui.chat_panel import ChatPanel
from plugin.ui.player_panel import PlayerPanel
from plugin import iac


class _IACWorker(QThread):
    done = pyqtSignal(str)   # emits the method used: "command" or "stream"
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


class AuxApp(QMainWindow):
    def __init__(self, output_dir: str):
        super().__init__()
        self.output_dir = output_dir
        self.setWindowTitle("Aux — AI Music Producer")
        self.resize(1000, 680)
        self.setMinimumSize(760, 500)

        Path(output_dir).mkdir(exist_ok=True)

        self._build_ui()
        self._apply_style()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter)

        # ── left panel ────────────────────────────────────────────────────────
        left = QWidget()
        left.setMinimumWidth(240)
        left.setMaximumWidth(340)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 10, 0)
        left_layout.setSpacing(12)

        title = QLabel("AUX")
        title.setObjectName("title")
        left_layout.addWidget(title)

        sub = QLabel("AI MUSIC PRODUCER")
        sub.setObjectName("section_header")
        left_layout.addWidget(sub)

        self.drop_zone = MidiDropZone()
        self.drop_zone.file_loaded.connect(self._on_midi_loaded)
        left_layout.addWidget(self.drop_zone)

        output_header = QLabel("OUTPUT FILES")
        output_header.setObjectName("section_header")
        left_layout.addWidget(output_header)

        self.file_list = QListWidget()
        self.file_list.setWordWrap(True)
        self.file_list.currentItemChanged.connect(self._on_file_selected)
        left_layout.addWidget(self.file_list, stretch=1)

        self.player = PlayerPanel()
        left_layout.addWidget(self.player)

        self.port_selector = QComboBox()
        ports = iac.list_ports()
        if ports:
            self.port_selector.addItems(ports)
            if iac.DEFAULT_PORT in ports:
                self.port_selector.setCurrentText(iac.DEFAULT_PORT)
        else:
            self.port_selector.addItem("No IAC ports found")
            self.port_selector.setEnabled(False)
        left_layout.addWidget(self.port_selector)

        self.fl_script_toggle = QComboBox()
        self.fl_script_toggle.addItem("Ghost produce (FL script)", True)
        self.fl_script_toggle.addItem("Raw stream (IAC fallback)", False)
        left_layout.addWidget(self.fl_script_toggle)

        self.fl_btn = QPushButton("→ Ghost Produce in FL Studio")
        self.fl_btn.setObjectName("fl_btn")
        self.fl_btn.setToolTip("Send 4-bar pattern to FL Studio via MIDI Controller Script")
        self.fl_btn.clicked.connect(self._send_selected_to_fl)
        left_layout.addWidget(self.fl_btn)

        self._iac_worker: _IACWorker | None = None

        splitter.addWidget(left)

        # ── right panel (chat) ─────────────────────────────────────────────────
        self.chat = ChatPanel(output_dir=self.output_dir)
        self.chat.files_ready.connect(self._on_files_ready)
        splitter.addWidget(self.chat)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

    def _apply_style(self):
        qss_path = Path(__file__).parent / "ui" / "styles.qss"
        if qss_path.exists():
            self.setStyleSheet(qss_path.read_text())

    # ── slots ─────────────────────────────────────────────────────────────────

    @pyqtSlot(str)
    def _on_midi_loaded(self, path: str):
        self.chat.set_midi_path(path)
        self._warn_if_empty(path)

    def _warn_if_empty(self, path: str):
        try:
            import mido
            mid = mido.MidiFile(path)
            notes = [
                m for track in mid.tracks
                for m in track
                if m.type in ("note_on", "note_off")
            ]
            if not notes:
                self.chat._append_system(
                    "Warning: this MIDI file has no notes — /fill and /analyze will use defaults.\n"
                    "Export a MIDI with actual notes from FL Studio, or use /vibe to generate from scratch."
                )
        except Exception:
            pass

    @pyqtSlot()
    def _on_file_selected(self):
        item = self.file_list.currentItem()
        if not item:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        if path and Path(path).exists():
            bpm = item.data(Qt.ItemDataRole.UserRole + 1) or 120.0
            self.player.load(path, original_bpm=float(bpm))

    @pyqtSlot(list, str)
    def _on_files_ready(self, files: list, output_dir: str):
        self.file_list.clear()
        for f in files:
            filepath = f.get("filepath", "")
            label = f.get("vibe") or f.get("description") or Path(filepath).name
            bpm   = f.get("tempo", 120)
            item  = QListWidgetItem(f"{label}\n{Path(filepath).name}")
            item.setData(Qt.ItemDataRole.UserRole, filepath)
            item.setData(Qt.ItemDataRole.UserRole + 1, bpm)
            self.file_list.addItem(item)

        if files:
            self.file_list.setCurrentRow(0)

    def _send_selected_to_fl(self):
        item = self.file_list.currentItem()
        if not item:
            QMessageBox.information(self, "No file selected", "Select a file from the list first.")
            return
        src = item.data(Qt.ItemDataRole.UserRole)
        if not src or not Path(src).exists():
            QMessageBox.warning(self, "File not found", f"Cannot find:\n{src}")
            return
        if self._iac_worker and self._iac_worker.isRunning():
            QMessageBox.information(self, "Busy", "Already streaming — wait for it to finish.")
            return

        port_name = self.port_selector.currentText()
        use_fl_script = self.fl_script_toggle.currentData()
        self._iac_worker = _IACWorker(src, port_name, use_fl_script=use_fl_script)
        self._iac_worker.done.connect(self._on_iac_done)
        self._iac_worker.error.connect(self._on_iac_error)
        self._iac_worker.finished.connect(lambda: self._set_fl_btn_busy(False))
        self._iac_worker.start()
        self._set_fl_btn_busy(True)

    def _set_fl_btn_busy(self, busy: bool):
        self.fl_btn.setEnabled(not busy)
        self.fl_btn.setText("Writing command..." if busy else "→ Ghost Produce in FL Studio")

    def _on_iac_done(self, method: str):
        self.chat._append_system(f"Sent to FL Studio ({method}).")

    def _on_iac_error(self, err: str):
        QMessageBox.warning(self, "FL Studio Error", f"Failed to send:\n{err}")


