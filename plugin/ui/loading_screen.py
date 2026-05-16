"""
Loading / splash screen — matches tracksmith design template (LoadingScreen.jsx).
"""
import math

from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QPen, QBrush, QColor, QFont,
    QFontMetrics, QRadialGradient,
)

_BG    = QColor("#0f0d0b")
_FG    = QColor("#f4ede1")
_DIM   = QColor(244, 237, 225, 148)
_DIM2  = QColor(244, 237, 225, 87)
_AMBER = QColor("#e8a268")
_LINE  = QColor(255, 240, 210, 23)


class _Spinner(QWidget):
    def __init__(self, size: int = 170, parent=None):
        super().__init__(parent)
        self._size = size
        self._angle = 0
        self.setFixedSize(size, size)
        t = QTimer(self)
        t.timeout.connect(self._tick)
        t.start(16)

    def _tick(self):
        self._angle = (self._angle + 2) % 360
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s, r = self._size, self._size / 2.0
        p.translate(r, r)
        p.rotate(self._angle)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(_FG))
        p.drawEllipse(int(-r + 1), int(-r + 1), int(s - 2), int(s - 2))

        p.setPen(QPen(QColor(21, 17, 14, 46), 0.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for frac in (0.88, 0.80, 0.72, 0.64, 0.56, 0.48, 0.40):
            rr = r * frac
            p.drawEllipse(int(-rr), int(-rr), int(rr * 2), int(rr * 2))

        p.setPen(QPen(QColor(21, 17, 14, 20), s * 0.06))
        p.drawArc(int(-r * 0.72), int(-r * 0.72), int(r * 1.44), int(r * 1.44), 0, 90 * 16)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(_AMBER))
        cr = int(r * 0.30)
        p.drawEllipse(-cr, -cr, cr * 2, cr * 2)

        p.setBrush(QBrush(QColor("#0f0d0b")))
        p.drawEllipse(-3, -3, 6, 6)

        p.setBrush(QBrush(QColor(21, 17, 14, 115)))
        p.drawRect(-1, int(-r * 0.55), 2, int(r * 0.12))
        p.end()


class _Wordmark(QWidget):
    """tracksmith wordmark + waveform bars, matching Wordmark.jsx."""

    def __init__(self, size: int = 62, parent=None):
        super().__init__(parent)
        self._size = size
        self._wave_h = int(size * 0.42)
        self._gap = int(size * 0.14)
        self.setFixedHeight(size + self._gap + self._wave_h + 4)
        self.setMinimumWidth(480)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        font = QFont("Inter Tight")
        font.setPixelSize(self._size)
        font.setBold(True)
        p.setFont(font)
        p.setPen(_FG)

        fm = QFontMetrics(font)
        text = "tracksmith"
        text_w = fm.horizontalAdvance(text)
        x_off = max(0, (self.width() - text_w) // 2)
        p.drawText(x_off, self._size, text)

        bar_top = self._size + self._gap
        bar_count = 64
        unit = text_w / bar_count
        for i in range(bar_count):
            v = abs(math.sin(i * 0.42) + math.sin(i * 0.13) * 0.6) / 1.5
            h = max(3, int(4 + v * self._wave_h * 0.85))
            accent = 22 <= i <= 30
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(_AMBER if accent else _FG))
            x = x_off + int(i * unit)
            bw = max(2, int(unit * 0.55))
            y = bar_top + (self._wave_h - h) // 2
            p.drawRoundedRect(x, y, bw, h, 1, 1)

        p.end()


class _Steps(QWidget):
    """Animated pipeline steps — matches the steps row in LoadingScreen.jsx."""

    STEPS = [
        "parsing reference",
        "picking key + tempo",
        "drafting blocks",
        "wiring the graph",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._idx = 0
        self._blink = True
        self.setFixedHeight(24)
        self.setMinimumWidth(640)

        t = QTimer(self)
        t.timeout.connect(self._blink_tick)
        t.start(500)

        self._adv = QTimer(self)
        self._adv.timeout.connect(self._advance)
        self._adv.start(1350)

    def _blink_tick(self):
        self._blink = not self._blink
        self.update()

    def _advance(self):
        if self._idx < len(self.STEPS) - 1:
            self._idx += 1
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        font = QFont("Inter Tight")
        font.setPixelSize(12)
        p.setFont(font)
        fm = QFontMetrics(font)

        DOT, GAP, SEP = 8, 8, 18
        widths = [fm.horizontalAdvance(s) for s in self.STEPS]
        total_w = sum(DOT + GAP + w for w in widths) + (SEP + 12) * (len(self.STEPS) - 1)
        x = max(0, (self.width() - total_w) // 2)
        cy = self.height() // 2

        for i, step in enumerate(self.STEPS):
            state = ("done" if i < self._idx else
                     "active" if i == self._idx else "pending")

            if state == "active":
                col = _AMBER if self._blink else QColor(_AMBER.red(), _AMBER.green(), _AMBER.blue(), 153)
            elif state == "done":
                col = _AMBER
            else:
                col = QColor(255, 240, 210, 23)

            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(col))
            p.drawEllipse(x, cy - 4, DOT, DOT)
            x += DOT + GAP

            p.setPen(_FG if state == "active" else (_DIM if state == "done" else _DIM2))
            p.drawText(x, cy + 4, step)
            x += widths[i] + 6

            if i < len(self.STEPS) - 1:
                p.setPen(QPen(_LINE, 1))
                p.drawLine(x, cy, x + SEP, cy)
                x += SEP + 6

        p.end()


class LoadingScreen(QWidget):
    """
    Splash screen — matches LoadingScreen.jsx.
    Emits `ready` after the pipeline animation completes (~5.5 s).
    """

    ready = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        QTimer.singleShot(5500, self.ready.emit)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addStretch(2)

        # Vinyl spinner
        layout.addWidget(_Spinner(170), alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(36)

        # Wordmark
        wm = _Wordmark(62)
        layout.addWidget(wm, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(8)

        # Subtitle
        sub = QLabel("MAKE MUSIC WITH AN AGENT")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet(
            "color: rgba(244,237,225,0.58);"
            "font-size: 13px;"
            "font-family: 'Inter Tight', 'Inter', system-ui, sans-serif;"
            "letter-spacing: 2px;"
        )
        layout.addWidget(sub)
        layout.addSpacing(32)

        # Steps
        steps = _Steps()
        layout.addWidget(steps, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addStretch(3)

        # Meta — bottom
        self._meta = QLabel("v0.4 · tracksmith · A min · 120 bpm")
        self._meta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._meta.setStyleSheet(
            "color: rgba(244,237,225,0.34);"
            "font-size: 11px;"
            "letter-spacing: 2px;"
            "font-family: 'Inter Tight', 'Inter', system-ui, sans-serif;"
        )
        layout.addWidget(self._meta)
        layout.addSpacing(28)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), _BG)

        # Soft amber glow from top-center
        cx = self.width() // 2
        grad = QRadialGradient(cx, -80, 520)
        glow = QColor(_AMBER)
        glow.setAlphaF(0.15)
        grad.setColorAt(0, glow)
        grad.setColorAt(1, QColor(0, 0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grad))
        p.drawRect(0, 0, self.width(), min(self.height(), 600))

        p.end()
