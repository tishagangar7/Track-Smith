"""
Node canvas — right panel dot-grid with MIDI block cards.
Matches the tracksmith design template.
"""
import math
from pathlib import Path

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QSizePolicy
from PyQt6.QtCore import Qt, QTimer, QRect, QPoint, pyqtSignal
from PyQt6.QtGui import QPainter, QPen, QBrush, QColor, QFont, QPainterPath, QFontMetrics

# ── design tokens ──────────────────────────────────────────────────────────────
_BG      = QColor("#0f0d0b")
_NODE_BG = QColor("#1a1714")
_LINE    = QColor(255, 240, 210, 23)
_FG      = QColor("#f4ede1")
_DIM     = QColor(244, 237, 225, 148)
_DIM2    = QColor(244, 237, 225, 87)
_AMBER   = QColor("#e8a268")
_TEAL    = QColor("#7fb3a3")
_PLUM    = QColor("#c69ad8")

_COLORS = [_AMBER, _TEAL, _PLUM]

_CARD_W, _CARD_H = 200, 118
_CARD_POSITIONS  = [(52, 80), (296, 195), (540, 80)]


class VinylSpinner(QWidget):
    def __init__(self, size: int = 18, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def start(self):
        self._timer.start(16)
        self.setVisible(True)

    def stop(self):
        self._timer.stop()
        self.setVisible(False)

    def _tick(self):
        self._angle = (self._angle + 4) % 360
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = self.width()
        r = s / 2.0
        p.translate(r, r)
        p.rotate(self._angle)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(_FG))
        p.drawEllipse(int(-r + 1), int(-r + 1), int(s - 2), int(s - 2))

        groove = QColor(21, 17, 14, 46)
        p.setPen(QPen(groove, 0.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for frac in (0.88, 0.76, 0.64, 0.52, 0.40):
            rr = r * frac
            p.drawEllipse(int(-rr), int(-rr), int(rr * 2), int(rr * 2))

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(_AMBER))
        cr = int(r * 0.30)
        p.drawEllipse(-cr, -cr, cr * 2, cr * 2)

        p.setBrush(QBrush(QColor("#0f0d0b")))
        p.drawEllipse(-2, -2, 4, 4)
        p.end()


class _NodeCard(QWidget):
    clicked = pyqtSignal(int)  # emits option index

    def __init__(self, data: dict, color: QColor, idx: int, parent=None):
        super().__init__(parent)
        self._data = data
        self._color = color
        self._idx = idx
        self._selected = False
        self.setFixedSize(_CARD_W, _CARD_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_selected(self, sel: bool):
        self._selected = sel
        self.update()

    def mousePressEvent(self, event):
        self.clicked.emit(self._idx)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        scale = W / _CARD_W  # relative to base card size

        # Card background + border
        path = QPainterPath()
        path.addRoundedRect(0.5, 0.5, W - 1, H - 1, 12, 12)
        p.fillPath(path, QBrush(_NODE_BG))
        border = _AMBER if self._selected else _LINE
        p.setPen(QPen(border, 1.5 if self._selected else 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        p.scale(scale, scale)

        # Color dot
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(self._color))
        p.drawEllipse(13, 14, 7, 7)

        # Vibe label
        label = (self._data.get("vibe") or self._data.get("description") or "")[:28]
        font = QFont()
        font.setFamily("Inter Tight, Inter, system-ui")
        font.setPixelSize(13)
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        p.setPen(_FG)
        p.drawText(27, 24, label)

        # "8 bars" badge
        bars_font = QFont()
        bars_font.setFamily("Inter Tight, Inter, system-ui")
        bars_font.setPixelSize(10)
        p.setFont(bars_font)
        p.setPen(_DIM2)
        bars_text = "8 bars"
        fm = QFontMetrics(bars_font)
        bw = fm.horizontalAdvance(bars_text)
        p.drawText(_CARD_W - bw - 14, 24, bars_text)

        # Chord sub-line
        chords = self._data.get("chord_progression") or []
        chord_str = (" → ".join(chords[:4]))[:36]
        sub_font = QFont()
        sub_font.setFamily("Inter Tight, Inter, system-ui")
        sub_font.setPixelSize(11)
        p.setFont(sub_font)
        p.setPen(_DIM)
        p.drawText(13, 42, chord_str)

        # Genre · mood
        genre = self._data.get("genre", "")
        mood  = self._data.get("mood", "")
        pill  = (f"{genre} · {mood}" if genre and mood else genre or mood)[:32]
        if pill:
            pill_font = QFont()
            pill_font.setFamily("Inter Tight, Inter, system-ui")
            pill_font.setPixelSize(10)
            p.setFont(pill_font)
            p.setPen(_DIM2)
            p.drawText(13, 57, pill)

        # Mini waveform
        bar_color = QColor(self._color)
        bar_color.setAlphaF(0.85)
        p.setBrush(QBrush(bar_color))
        p.setPen(Qt.PenStyle.NoPen)
        seed = self._data.get("option", self._idx + 1) * 17
        wave_y = _CARD_H - 18
        for i in range(34):
            h = int(3 + abs(math.sin(i * 1.7 + seed * 0.013)) * 10)
            x = 12 + i * 5
            y = wave_y - h // 2
            if x + 3 <= _CARD_W - 14:
                p.drawRoundedRect(x, y, 3, h, 1, 1)

        p.end()


class _DotCanvas(QWidget):
    """Dot-grid canvas that holds node cards."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cards: list[_NodeCard] = []
        self._zoom: float = 0.75  # default fits all 3 cards
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_zoom(self, zoom: float):
        self._zoom = zoom
        self._reposition_cards()
        self.update()

    def _reposition_cards(self):
        z = self._zoom
        for i, card in enumerate(self._cards):
            px, py = (_CARD_POSITIONS[i] if i < len(_CARD_POSITIONS) else (60 + i * 260, 90))
            card.move(int(px * z), int(py * z))
            card.setFixedSize(int(_CARD_W * z), int(_CARD_H * z))

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), _BG)

        # Dot grid
        p.setPen(QPen(_LINE, 1.0))
        spacing = max(12, int(24 * self._zoom))
        for x in range(0, self.width() + spacing, spacing):
            for y in range(0, self.height() + spacing, spacing):
                p.drawPoint(x, y)

        # Bezier edges between cards
        if len(self._cards) >= 2:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            edge_pen = QPen(QColor(255, 240, 210, 46), 1.5)
            p.setPen(edge_pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            cw = int(_CARD_W * self._zoom)
            ch = int(_CARD_H * self._zoom)
            centers = [
                QPoint(c.x() + cw // 2, c.y() + ch // 2)
                for c in self._cards
            ]
            pairs = [(0, 1), (1, 2)] if len(centers) >= 3 else [(0, 1)]
            for a, b in pairs:
                pA, pB = centers[a], centers[b]
                dx = (pB.x() - pA.x()) * 0.4
                path = QPainterPath()
                path.moveTo(pA.x(), pA.y())
                path.cubicTo(
                    pA.x() + dx, pA.y(),
                    pB.x() - dx, pB.y(),
                    pB.x(), pB.y(),
                )
                p.drawPath(path)

        p.end()

    def set_cards(self, cards: list[_NodeCard]):
        self._cards = cards
        self.update()


class NodeCanvas(QWidget):
    """Right panel: transport + dot-grid canvas with MIDI blocks + FL export."""

    file_selected = pyqtSignal(str, float)   # path, bpm
    mode_changed = pyqtSignal(str)           # "input_only" | "combined" | "continuation_only"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._files: list[dict] = []
        self._cards: list[_NodeCard] = []
        self._selected_idx = -1
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Transport bar
        self._transport = self._make_transport()
        layout.addWidget(self._transport)

        # Dot-grid canvas
        self._canvas = _DotCanvas(self)
        layout.addWidget(self._canvas, stretch=1)

    # ── transport ─────────────────────────────────────────────────────────────

    def _make_transport(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("transport_bar")
        bar.setFixedHeight(64)
        row = QHBoxLayout(bar)
        row.setContentsMargins(20, 0, 20, 0)
        row.setSpacing(8)

        self._btn_play = QPushButton("▶")
        self._btn_play.setObjectName("transport_btn_play")
        self._btn_play.setFixedSize(48, 48)
        row.addWidget(self._btn_play)

        self._btn_stop = QPushButton("◼")
        self._btn_stop.setObjectName("transport_btn")
        self._btn_stop.setFixedSize(32, 32)
        row.addWidget(self._btn_stop)

        self._btn_loop = QPushButton("↻")
        self._btn_loop.setObjectName("transport_btn")
        self._btn_loop.setFixedSize(32, 32)
        row.addWidget(self._btn_loop)

        self._spinner = VinylSpinner(size=18)
        self._spinner.setVisible(False)
        row.addWidget(self._spinner)

        self._lbl_status = QLabel("drop a file to start")
        self._lbl_status.setObjectName("transport_status")
        row.addWidget(self._lbl_status)

        self._lbl_time = QLabel("")
        self._lbl_time.setObjectName("transport_dim")
        row.addWidget(self._lbl_time)

        row.addStretch()

        self._lbl_stats = QLabel("")
        self._lbl_stats.setObjectName("transport_dim")
        row.addWidget(self._lbl_stats)

        # Vertical divider
        div = QLabel()
        div.setFixedSize(1, 16)
        div.setStyleSheet("background: rgba(255,240,210,0.09);")
        row.addWidget(div)

        # Playback mode buttons — Original / With Fill / Fill Only
        _MODE_IDS = [
            ("original", "input_only"),
            ("with fill", "combined"),
            ("fill only", "continuation_only"),
        ]
        self._mode_tabs: list[QPushButton] = []
        self._mode_values = [m for _, m in _MODE_IDS]
        for i, (label, _) in enumerate(_MODE_IDS):
            btn = QPushButton(label)
            btn.setObjectName("view_tab_active" if i == 1 else "view_tab")
            btn.setCheckable(True)
            btn.setChecked(i == 1)
            btn.clicked.connect(lambda _, idx=i: self._switch_mode(idx))
            row.addWidget(btn)
            self._mode_tabs.append(btn)

        # Divider before zoom
        div2 = QLabel()
        div2.setFixedSize(1, 16)
        div2.setStyleSheet("background: rgba(255,240,210,0.09);")
        row.addWidget(div2)

        # Zoom controls
        btn_zoom_out = QPushButton("−")
        btn_zoom_out.setObjectName("transport_btn")
        btn_zoom_out.setFixedSize(28, 28)
        btn_zoom_out.clicked.connect(self._zoom_out)
        row.addWidget(btn_zoom_out)

        btn_zoom_in = QPushButton("+")
        btn_zoom_in.setObjectName("transport_btn")
        btn_zoom_in.setFixedSize(28, 28)
        btn_zoom_in.clicked.connect(self._zoom_in)
        row.addWidget(btn_zoom_in)

        return bar

    def _switch_mode(self, idx: int):
        for i, btn in enumerate(self._mode_tabs):
            active = i == idx
            btn.setObjectName("view_tab_active" if active else "view_tab")
            btn.setChecked(active)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self.mode_changed.emit(self._mode_values[idx])

    def _zoom_in(self):
        self._canvas.set_zoom(min(2.0, self._canvas._zoom + 0.2))

    def _zoom_out(self):
        self._canvas.set_zoom(max(0.4, self._canvas._zoom - 0.2))

    # ── public API ─────────────────────────────────────────────────────────────

    def set_busy(self, busy: bool, status: str = ""):
        if busy:
            self._spinner.start()
            self._lbl_status.setText(status or "generating…")
        else:
            self._spinner.stop()
            if self._files:
                self._lbl_status.setText(f"{len(self._files)} loops ready")
            else:
                self._lbl_status.setText("drop a file to start")

    def set_file_loaded(self, name: str, duration: str = ""):
        if duration:
            self._lbl_status.setText(f"{name}  ·  {duration}")
        else:
            self._lbl_status.setText(f"{name} loaded")

    def set_time(self, current: str, total: str):
        self._lbl_time.setText(f"{current} / {total}")

    def set_files(self, files: list):
        self._files = files
        self._selected_idx = 0
        self._build_cards()
        self._lbl_stats.setText(f"{len(files)} blocks")
        if files:
            self._select(0)

    def selected_file(self) -> dict | None:
        if 0 <= self._selected_idx < len(self._files):
            return self._files[self._selected_idx]
        return None

    def clear(self):
        for c in self._cards:
            c.deleteLater()
        self._cards.clear()
        self._files.clear()
        self._canvas.set_cards([])
        self._lbl_stats.setText("")

    # ── internals ──────────────────────────────────────────────────────────────

    def _build_cards(self):
        for c in self._cards:
            c.deleteLater()
        self._cards.clear()

        for i, f in enumerate(self._files[:3]):
            color = _COLORS[i % len(_COLORS)]
            card = _NodeCard(f, color, i, self._canvas)
            card.show()
            card.clicked.connect(self._select)
            self._cards.append(card)

        self._canvas.set_cards(self._cards)
        self._canvas._reposition_cards()

    def _select(self, idx: int):
        self._selected_idx = idx
        for i, card in enumerate(self._cards):
            card.set_selected(i == idx)
        if idx < len(self._files):
            f = self._files[idx]
            path = f.get("filepath", "")
            bpm = float(f.get("tempo") or 120)
            self.file_selected.emit(path, bpm)
