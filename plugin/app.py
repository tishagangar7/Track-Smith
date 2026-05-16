"""
Aux plugin companion app — main window.

Layout:
  Left panel:  media drop zone + output file list + playback
  Right panel: Chat panel (slash commands)
"""

from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QSplitter, QListWidget, QListWidgetItem,
    QPushButton, QMessageBox, QComboBox, QFileDialog,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, pyqtSlot

from plugin.ui.media_drop_zone import MediaDropZone
from plugin.ui.chat_panel import ChatPanel
from plugin.ui.player_panel import PlayerPanel
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


class AuxApp(QMainWindow):
    def __init__(self, output_dir: str):
        super().__init__()
        self.output_dir = output_dir
        self._input_path: str | None = None
        self._input_type: str = "midi"
        self._input_bpm: float = 120.0
        self._analyze_worker: _AnalyzeWorker | None = None

        self.setWindowTitle("Aux — AI Music Producer")
        self.resize(1000, 680)
        self.setMinimumSize(760, 500)

        Path(output_dir).mkdir(exist_ok=True)

        self._build_ui()
        self._apply_style()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter)

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

        self.drop_zone = MediaDropZone()
        self.drop_zone.file_loaded.connect(self._on_media_loaded)
        left_layout.addWidget(self.drop_zone)

        output_header = QLabel("OUTPUT FILES")
        output_header.setObjectName("section_header")
        left_layout.addWidget(output_header)

        self.file_list = QListWidget()
        self.file_list.setWordWrap(True)
        self.file_list.currentItemChanged.connect(self._on_file_selected)
        left_layout.addWidget(self.file_list, stretch=1)

        self.player = PlayerPanel(output_dir=self.output_dir)
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
        self.fl_btn.clicked.connect(self._send_selected_to_fl)
        left_layout.addWidget(self.fl_btn)

        dl_header = QLabel("EXPORT")
        dl_header.setObjectName("section_header")
        left_layout.addWidget(dl_header)

        dl_row = QHBoxLayout()
        self.dl_fill_btn = QPushButton("↓ Fill")
        self.dl_fill_btn.setObjectName("secondary")
        self.dl_fill_btn.clicked.connect(self._download_fill)
        self.dl_fill_btn.setEnabled(False)
        dl_row.addWidget(self.dl_fill_btn)

        self.dl_merged_btn = QPushButton("↓ Merged")
        self.dl_merged_btn.setObjectName("secondary")
        self.dl_merged_btn.clicked.connect(self._download_merged)
        self.dl_merged_btn.setEnabled(False)
        dl_row.addWidget(self.dl_merged_btn)
        left_layout.addLayout(dl_row)

        self._iac_worker: _IACWorker | None = None
        splitter.addWidget(left)

        self.chat = ChatPanel(output_dir=self.output_dir)
        self.chat.files_ready.connect(self._on_files_ready)
        splitter.addWidget(self.chat)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

    def _apply_style(self):
        qss_path = Path(__file__).parent / "ui" / "styles.qss"
        if qss_path.exists():
            self.setStyleSheet(qss_path.read_text())

    @pyqtSlot(str, str)
    def _on_media_loaded(self, path: str, source_type: str):
        self._input_path = path
        self._input_type = source_type
        self.chat.set_midi_path(path)

        self.player.set_input(path, source_type=source_type, bpm=self._input_bpm)
        self.player.set_continuation(None)
        self._update_download_buttons()

        if source_type == "midi" and count_midi_notes(path) == 0:
            self.chat._append_system(
                "Warning: this MIDI has no notes — /fill will be blocked.\n"
                "Export from FL piano roll with notes, or drop an MP3 instead."
            )
        elif source_type == "audio":
            self.chat._append_system("Audio loaded — /fill will use estimated tempo/key from the file.")

        self._analyze_worker = _AnalyzeWorker(path)
        self._analyze_worker.done.connect(self._on_analyze_done)
        self._analyze_worker.error.connect(lambda e: self.chat._append_system(f"Analyze: {e}"))
        self._analyze_worker.start()

    def _on_analyze_done(self, analysis: dict):
        self._input_bpm = float(analysis.get("tempo", 120))
        if self._input_path:
            self.player.set_input(
                self._input_path,
                source_type=self._input_type,
                bpm=self._input_bpm,
            )

    @pyqtSlot()
    def _on_file_selected(self):
        item = self.file_list.currentItem()
        if not item:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        if path and Path(path).exists():
            from plugin.media_info import bpm_from_midi
            bpm = bpm_from_midi(path) if path.lower().endswith((".mid", ".midi")) else float(
                item.data(Qt.ItemDataRole.UserRole + 1) or 120.0
            )
            self.player.set_continuation(path, bpm=bpm)
        self._update_download_buttons()

    def _update_download_buttons(self):
        has_cont = bool(self.player._continuation_path)
        self.dl_fill_btn.setEnabled(has_cont)
        can_merge = (
            has_cont
            and self._input_path
            and self._input_type == "midi"
        )
        self.dl_merged_btn.setEnabled(can_merge)
        self.dl_merged_btn.setToolTip(
            "Input + fill as one MIDI (MIDI input only)"
            if can_merge
            else "Merged export needs MIDI input; MP3 → downloads fill only"
        )

    def _download_fill(self):
        path = self.player._continuation_path
        if not path:
            return
        default = Path(path).name
        dest, _ = QFileDialog.getSaveFileName(
            self, "Download fill", default, "MIDI files (*.mid)"
        )
        if dest:
            from plugin.export import export_continuation
            export_continuation(path, dest)
            self.chat._append_system(f"Saved fill → {dest}")

    def _download_merged(self):
        if not self._input_path or not self.player._continuation_path:
            return
        default = "aux_merged_preview.mid"
        dest, _ = QFileDialog.getSaveFileName(
            self, "Download merged preview", default, "MIDI files (*.mid)"
        )
        if dest:
            from plugin.export import export_merged_preview
            export_merged_preview(
                self._input_path,
                self.player._continuation_path,
                dest,
                self._input_type,
            )
            self.chat._append_system(f"Saved merged → {dest}")

    @pyqtSlot(list, str)
    def _on_files_ready(self, files: list, output_dir: str):
        self.file_list.clear()
        for f in files:
            filepath = f.get("filepath", "")
            label = f.get("vibe") or f.get("description") or Path(filepath).name
            bpm = f.get("tempo", 120)
            item = QListWidgetItem(f"{label}\n{Path(filepath).name}")
            item.setData(Qt.ItemDataRole.UserRole, filepath)
            item.setData(Qt.ItemDataRole.UserRole + 1, bpm)
            self.file_list.addItem(item)

        if files:
            self.file_list.setCurrentRow(0)
            self._on_file_selected()
            self._update_download_buttons()
            self.chat._append_system(
                "Compare: Original vs With Fill. Drag the seek bar to scrub. Download fill or merged MIDI below."
            )

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
