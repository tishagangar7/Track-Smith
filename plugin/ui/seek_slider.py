"""Clickable / draggable seek bar for playback."""

from PyQt6.QtWidgets import QSlider
from PyQt6.QtCore import Qt, pyqtSignal


class SeekSlider(QSlider):
    """Horizontal seek slider; emits seek_requested on release and click."""

    seek_requested = pyqtSignal(float)  # fraction 0.0–1.0

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setRange(0, 1000)
        self.setValue(0)
        self._block_seek = False

    def set_position_fraction(self, frac: float):
        if self._block_seek:
            return
        self.setValue(int(max(0, min(1.0, frac)) * 1000))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._block_seek = True
            frac = event.position().x() / max(self.width(), 1)
            self.setValue(int(frac * 1000))
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            frac = self.value() / 1000.0
            self.seek_requested.emit(frac)
            self._block_seek = False
        super().mouseReleaseEvent(event)
