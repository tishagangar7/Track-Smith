from pathlib import Path
from PyQt6.QtWidgets import QLabel
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent


class MidiDropZone(QLabel):
    file_loaded = pyqtSignal(str)  # emits absolute path

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("drop_zone")
        self.setAcceptDrops(True)
        self.setText("Drop MIDI here\nor click to browse")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(90)
        self._path: str | None = None

    @property
    def midi_path(self) -> str | None:
        return self._path

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if any(u.toLocalFile().lower().endswith((".mid", ".midi")) for u in urls):
                event.acceptProposedAction()
                return
        event.ignore()

    def dropEvent(self, event: QDropEvent):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith((".mid", ".midi")):
                self._set_file(path)
                break

    def mousePressEvent(self, event):
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Open MIDI file", "", "MIDI files (*.mid *.midi)"
        )
        if path:
            self._set_file(path)

    def _set_file(self, path: str):
        self._path = path
        name = Path(path).name
        self.setText(f"{name}")
        self.setProperty("loaded", "true")
        self.style().unpolish(self)
        self.style().polish(self)
        self.file_loaded.emit(path)
