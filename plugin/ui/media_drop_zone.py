from pathlib import Path

from PyQt6.QtWidgets import QLabel, QFileDialog
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent

from plugin.media_info import MEDIA_FILTER, is_supported_media, describe_media


class MediaDropZone(QLabel):
    """Accept MIDI and audio files."""

    file_loaded = pyqtSignal(str, str)  # path, source_type ("midi" | "audio")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("drop_zone")
        self.setAcceptDrops(True)
        self.setText("Drop MIDI / MP3 here\nor click to browse")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(44)
        self._path: str | None = None
        self._source_type: str = "midi"

    @property
    def media_path(self) -> str | None:
        return self._path

    @property
    def source_type(self) -> str:
        return self._source_type

    # backward compat
    @property
    def midi_path(self) -> str | None:
        return self._path

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if any(is_supported_media(u.toLocalFile()) for u in urls):
                event.acceptProposedAction()
                return
        event.ignore()

    def dropEvent(self, event: QDropEvent):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if is_supported_media(path):
                self._set_file(path)
                break

    def mousePressEvent(self, event):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open media file", "", MEDIA_FILTER
        )
        if path:
            self._set_file(path)

    def _set_file(self, path: str):
        self._path = path
        self._source_type, label = describe_media(path)
        self.setText(label)
        self.setProperty("loaded", "true")
        self.style().unpolish(self)
        self.style().polish(self)
        self.file_loaded.emit(path, self._source_type)


# backward-compatible alias
MidiDropZone = MediaDropZone
