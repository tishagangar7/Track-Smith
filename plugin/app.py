"""
Aux plugin companion app — main window.

Layout:
  Left panel:  MIDI drop zone + output file list
  Right panel: Chat panel (slash commands)
"""

import shutil
from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QSplitter, QListWidget, QListWidgetItem,
    QPushButton, QApplication, QMessageBox, QDialog,
    QTextEdit, QDialogButtonBox,
)
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QClipboard

from plugin.ui.midi_drop_zone import MidiDropZone
from plugin.ui.chat_panel import ChatPanel


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
        left_layout.addWidget(self.file_list, stretch=1)

        fl_btn = QPushButton("→ Piano Roll")
        fl_btn.setObjectName("fl_btn")
        fl_btn.setToolTip("Write selected file as pending.mid for FL Studio Script Pad")
        fl_btn.clicked.connect(self._send_selected_to_fl)
        left_layout.addWidget(fl_btn)

        setup_btn = QPushButton("FL Script Setup")
        setup_btn.setObjectName("secondary")
        setup_btn.clicked.connect(self._show_fl_script)
        left_layout.addWidget(setup_btn)

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

    @pyqtSlot(list, str)
    def _on_files_ready(self, files: list, output_dir: str):
        self.file_list.clear()
        for f in files:
            filepath = f.get("filepath", "")
            label = f.get("vibe") or f.get("description") or Path(filepath).name
            item = QListWidgetItem(f"{label}\n{Path(filepath).name}")
            item.setData(Qt.ItemDataRole.UserRole, filepath)
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

        pending = Path(self.output_dir) / "pending.mid"
        shutil.copy2(src, pending)

        QMessageBox.information(
            self,
            "Ready for FL Studio",
            f"Written to:\n{pending}\n\n"
            "In FL Studio:\n"
            "  1. Open a pattern in the piano roll\n"
            "  2. Open Script Pad (Tools → Script → Score)\n"
            "  3. Paste aux_import.py (click 'FL Script Setup' to copy)\n"
            "  4. Click Run — notes will appear in the piano roll",
        )

    def _show_fl_script(self):
        pending_path = (Path(self.output_dir) / "pending.mid").resolve()
        script_path = Path(__file__).parent / "fl_script" / "aux_import.py"
        template = script_path.read_text() if script_path.exists() else _FL_SCRIPT_FALLBACK

        filled = template.replace(
            'PENDING_MID = r"<UPDATE_THIS_PATH>"',
            f'PENDING_MID = r"{pending_path}"',
        )

        dlg = _ScriptDialog(filled, self)
        dlg.exec()


class _ScriptDialog(QDialog):
    def __init__(self, script: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("FL Studio Script Pad — aux_import.py")
        self.resize(620, 440)
        layout = QVBoxLayout(self)

        note = QLabel(
            "Copy this script into FL Studio's Script Pad\n"
            "(Tools → Script → Score  or  Alt+Shift+S)"
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        self.editor = QTextEdit()
        self.editor.setPlainText(script)
        self.editor.setReadOnly(True)
        layout.addWidget(self.editor)

        btns = QDialogButtonBox()
        copy_btn = QPushButton("Copy to Clipboard")
        copy_btn.clicked.connect(self._copy)
        btns.addButton(copy_btn, QDialogButtonBox.ButtonRole.ActionRole)
        close_btn = btns.addButton(QDialogButtonBox.StandardButton.Close)
        close_btn.clicked.connect(self.accept)
        layout.addWidget(btns)

    def _copy(self):
        QApplication.clipboard().setText(self.editor.toPlainText())


_FL_SCRIPT_FALLBACK = '''\
import flp
import os

# UPDATE THIS PATH to match your machine
PENDING_MID = r"<UPDATE_THIS_PATH>"

if not os.path.exists(PENDING_MID):
    raise FileNotFoundError(f"pending.mid not found at: {PENDING_MID}")

try:
    import mido
except ImportError:
    raise ImportError("mido not installed in FL Studio's Python. Run: pip install mido")

mid = mido.MidiFile(PENDING_MID)
ticks_per_beat = mid.ticks_per_beat
ppq = flp.score.PPQ

flp.score.clear(True)

for track in mid.tracks:
    tick = 0
    active = {}
    for msg in track:
        tick += msg.time
        fl_tick = int(tick * ppq / ticks_per_beat)
        if msg.type == "note_on" and msg.velocity > 0:
            active[msg.note] = (fl_tick, msg.velocity)
        elif msg.type in ("note_off", "note_on") and msg.note in active:
            start, vel = active.pop(msg.note)
            length = max(1, fl_tick - start)
            n = flp.Note()
            n.number = msg.note
            n.time = start
            n.length = length
            n.velocity = round(vel / 127, 3)
            flp.score.addNote(n)

os.remove(PENDING_MID)
'''
