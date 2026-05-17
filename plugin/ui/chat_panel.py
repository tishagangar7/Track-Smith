"""
Chat panel — slash command input + scrolling message log.
Message bubbles match the tracksmith design template (App.jsx).
Inference runs in a QThread so the UI stays responsive.
"""

import html as _html
import math
import subprocess
import sys
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame,
    QLineEdit, QPushButton, QLabel, QSizePolicy, QSlider,
)
from PyQt6.QtCore import Qt, QThread, QUrl, QTimer, QSize, pyqtSignal
from PyQt6.QtGui import (
    QKeyEvent, QPainter, QPainterPath, QPen, QBrush, QColor, QFont, QFontMetrics,
)

try:
    from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
    _HAS_MEDIA = True
except ImportError:
    _HAS_MEDIA = False

# Accent colors cycling for pill tags
_PILL_COLORS = ["#e8a268", "#7fb3a3", "#c69ad8", "#a7bf7a"]


def _h(text: str) -> str:
    """Escape plain text for QLabel RichText, preserving newlines as <br>."""
    return _html.escape(str(text)).replace("\n", "<br>")


# ── style chip bar ────────────────────────────────────────────────────────────

# ── vinyl icon widget ─────────────────────────────────────────────────────────

class _VinylIcon(QWidget):
    """Tiny vinyl record icon for composer input."""

    def __init__(self, size: int = 16, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = self.width()
        r = s / 2.0
        p.translate(r, r)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor("#f4ede1")))
        p.drawEllipse(int(-r), int(-r), s, s)

        groove = QColor(21, 17, 14, 80)
        p.setPen(QPen(groove, 0.8))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for frac in (0.84, 0.68, 0.54):
            rr = r * frac
            p.drawEllipse(int(-rr), int(-rr), int(rr * 2), int(rr * 2))

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor("#e8a268")))
        cr = int(r * 0.30)
        p.drawEllipse(-cr, -cr, cr * 2, cr * 2)

        p.setBrush(QBrush(QColor("#0f0d0b")))
        p.drawEllipse(-2, -2, 4, 4)
        p.end()


# ── brand header widget ───────────────────────────────────────────────────────

class _WordmarkWidget(QWidget):
    """tracksmith wordmark + compact waveform — matches Wordmark.jsx (compact=True)."""

    def __init__(self, size: int = 22, parent=None):
        super().__init__(parent)
        self._size = size
        self._wave_h = int(size * 0.32)
        self._gap = int(size * 0.14)
        self.setFixedHeight(size + self._gap + self._wave_h + 2)

    def sizeHint(self):
        return QSize(220, self._size + self._gap + self._wave_h + 2)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        font = QFont("Inter Tight")
        font.setPixelSize(self._size)
        font.setBold(True)
        p.setFont(font)
        p.setPen(QColor("#f4ede1"))
        p.drawText(0, self._size, "tracksmith")

        fm = QFontMetrics(font)
        text_w = fm.horizontalAdvance("tracksmith")
        bar_top = self._size + self._gap
        unit = text_w / 64
        for i in range(64):
            v = abs(math.sin(i * 0.42) + math.sin(i * 0.13) * 0.6) / 1.5
            h = max(2, int(3 + v * self._wave_h * 0.9))
            accent = 22 <= i <= 30
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor("#e8a268") if accent else QColor("#f4ede1")))
            x = int(i * unit)
            bw = max(1, int(unit * 0.55))
            y = bar_top + (self._wave_h - h) // 2
            p.drawRoundedRect(x, y, bw, h, 1, 1)
        p.end()


# ── message widget helpers ────────────────────────────────────────────────────

class _Pill(QWidget):
    """Colored dot + label pill tag — matches template node ref pills."""

    def __init__(self, text: str, color: str, parent=None):
        super().__init__(parent)
        l = QHBoxLayout(self)
        l.setContentsMargins(9, 4, 9, 4)
        l.setSpacing(6)

        dot = QLabel()
        dot.setFixedSize(6, 6)
        dot.setStyleSheet(f"background:{color}; border-radius:3px;")
        l.addWidget(dot)

        lbl = QLabel(text)
        lbl.setTextFormat(Qt.TextFormat.PlainText)
        lbl.setStyleSheet(
            "color:rgba(244,237,225,0.58); font-size:11px;"
            "background:transparent; border:none;"
        )
        l.addWidget(lbl)

        self.setStyleSheet(
            "border:1px solid rgba(255,240,210,0.09);"
            "border-radius:999px; background:transparent;"
        )


class _UserMsg(QWidget):
    """Right-aligned user bubble — YOU label + bordered transparent bubble."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(80, 4, 0, 4)
        outer.setSpacing(5)

        who = QLabel("YOU")
        who.setAlignment(Qt.AlignmentFlag.AlignRight)
        who.setStyleSheet(
            "color:rgba(244,237,225,0.34); font-size:10px;"
            "background:transparent; border:none;"
        )
        outer.addWidget(who)

        bubble = QLabel()
        bubble.setTextFormat(Qt.TextFormat.RichText)
        bubble.setText(_h(text))
        bubble.setWordWrap(True)
        bubble.setMaximumWidth(340)
        bubble.setStyleSheet(
            "background:transparent;"
            "border:1px solid rgba(255,240,210,0.12);"
            "border-radius:12px; padding:10px 13px;"
            "color:#f4ede1; font-size:13px;"
        )

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch()
        row.addWidget(bubble)
        outer.addLayout(row)


class _AgentMsg(QWidget):
    """Left-aligned agent bubble + optional pill tags + optional action buttons."""

    def __init__(self, text: str, pills=None,
                 on_accept=None, on_tweak=None, on_skip=None,
                 parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 4, 80, 4)
        outer.setSpacing(6)

        who = QLabel("AGENT")
        who.setStyleSheet(
            "color:rgba(244,237,225,0.34); font-size:10px;"
            "background:transparent; border:none;"
        )
        outer.addWidget(who)

        bubble = QLabel()
        bubble.setTextFormat(Qt.TextFormat.RichText)
        bubble.setText(_h(text))
        bubble.setWordWrap(True)
        bubble.setMaximumWidth(340)
        bubble.setStyleSheet(
            "background:#181513; border-radius:12px;"
            "padding:11px 14px;"
            "color:rgba(244,237,225,0.85); font-size:13px;"
        )
        outer.addWidget(bubble)

        # Pill tags (node references)
        if pills:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 2, 0, 0)
            rl.setSpacing(6)
            for txt, clr in pills:
                rl.addWidget(_Pill(txt, clr))
            rl.addStretch()
            outer.addWidget(row)

        # Accept / tweak / skip action buttons
        if on_accept or on_tweak or on_skip:
            btn_row = QWidget()
            bl = QHBoxLayout(btn_row)
            bl.setContentsMargins(0, 4, 0, 0)
            bl.setSpacing(6)

            if on_accept:
                b = QPushButton("accept")
                b.setStyleSheet(
                    "background:#e8a268; color:#1a0e06; border:none;"
                    "border-radius:8px; padding:6px 13px; font-size:12px;"
                    "font-weight:500;"
                )
                b.clicked.connect(on_accept)
                bl.addWidget(b)
            for label, fn in [("tweak", on_tweak), ("skip", on_skip)]:
                if fn:
                    b = QPushButton(label)
                    b.setStyleSheet(
                        "background:transparent; color:rgba(244,237,225,0.58);"
                        "border:1px solid rgba(255,240,210,0.09);"
                        "border-radius:8px; padding:6px 13px; font-size:12px;"
                    )
                    b.clicked.connect(fn)
                    bl.addWidget(b)
            bl.addStretch()
            outer.addWidget(btn_row)


class _SystemMsg(QWidget):
    """Dim centered system / status text."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        l = QVBoxLayout(self)
        l.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel()
        lbl.setTextFormat(Qt.TextFormat.RichText)
        lbl.setText(_h(text))
        lbl.setWordWrap(True)
        lbl.setStyleSheet(
            "color:rgba(244,237,225,0.34); font-size:11px;"
            "background:transparent; border:none;"
        )
        l.addWidget(lbl)


class _ErrorMsg(QWidget):
    """Red-tinted error bubble."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        l = QVBoxLayout(self)
        l.setContentsMargins(0, 0, 0, 0)
        bubble = QLabel()
        bubble.setTextFormat(Qt.TextFormat.RichText)
        bubble.setText(_h(text))
        bubble.setWordWrap(True)
        bubble.setStyleSheet(
            "background:rgba(220,80,80,0.1);"
            "border:1px solid rgba(220,80,80,0.3);"
            "border-radius:8px; padding:8px 12px;"
            "color:#f08080; font-size:13px;"
        )
        l.addWidget(bubble)


class _WaveWidget(QWidget):
    """Animated 3-layer sine wave — replaces static 'thinking...' during inference."""

    _LAYERS = [
        (12,  0.020, 0.0, 0.30),
        (8,   0.030, 1.0, 0.50),
        (15,  0.015, 2.0, 0.80),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(60)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(50)

    def _tick(self):
        self._phase += 0.12
        self.update()

    def stop(self):
        self._timer.stop()

    def paintEvent(self, event):
        try:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            w = self.width()
            cy = self.height() / 2.0
            for amp, freq, phase_off, opacity in self._LAYERS:
                color = QColor("#00d4aa")
                color.setAlphaF(opacity)
                p.setPen(QPen(color, 1.5))
                p.setBrush(Qt.BrushStyle.NoBrush)
                path = QPainterPath()
                path.moveTo(0.0, cy + amp * math.sin(self._phase + phase_off))
                for x in range(1, w):
                    y = cy + amp * math.sin(freq * x + self._phase + phase_off)
                    path.lineTo(float(x), y)
                p.drawPath(path)
            p.end()
        except Exception:
            pass


class _PolicyLogMsg(QWidget):
    """Compact OpenClaw policy activity strip shown after /fill completes."""

    def __init__(self, entries: list, parent=None):
        super().__init__(parent)
        l = QVBoxLayout(self)
        l.setContentsMargins(0, 6, 0, 2)
        l.setSpacing(2)

        hdr = QLabel("Agent Activity")
        hdr.setStyleSheet(
            "color:rgba(244,237,225,0.22); font-size:10px; font-weight:500;"
            "letter-spacing:0.5px; background:transparent; border:none;"
        )
        l.addWidget(hdr)

        for e in entries:
            icon = "✅" if e.get("status") == "allowed" else "🚫"
            detail = f" · {e['detail']}" if e.get("detail") else ""
            row = QLabel(f"{icon}  {e.get('action', '')} → {e.get('resource', '')}{detail}")
            row.setStyleSheet(
                "color:rgba(244,237,225,0.32); font-size:10px;"
                "background:transparent; border:none;"
            )
            row.setWordWrap(True)
            l.addWidget(row)


class _ChatLog(QScrollArea):
    """Scrollable message list — replaces QTextEdit."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet("background:transparent; border:none;")

        container = QWidget()
        container.setStyleSheet("background:transparent;")
        self._layout = QVBoxLayout(container)
        self._layout.setContentsMargins(22, 16, 22, 16)
        self._layout.setSpacing(18)
        self._layout.addStretch()
        self.setWidget(container)

    def add_widget(self, w: QWidget) -> QWidget:
        self._layout.insertWidget(self._layout.count() - 1, w)
        QTimer.singleShot(20, self._scroll_bottom)
        return w

    def remove_widget(self, w: QWidget):
        self._layout.removeWidget(w)
        w.deleteLater()

    def _scroll_bottom(self):
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())


# ── inference worker ──────────────────────────────────────────────────────────

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


# ── main panel ────────────────────────────────────────────────────────────────

class ChatPanel(QWidget):
    files_ready = pyqtSignal(list, str)   # (files list, output_dir)
    command_started = pyqtSignal(str)     # emits the slash command e.g. "/fill"

    def __init__(self, output_dir: str, parent=None):
        super().__init__(parent)
        self.output_dir = output_dir
        self._midi_path: str | None = None
        self._style_context: str | None = None
        self._worker: _InferenceWorker | None = None
        self._history: list[str] = []
        self._hist_idx: int = -1
        self._latest_audio: str | None = None
        self._audio_combined: str | None = None
        self._audio_continuation: str | None = None
        self._showing_combined: bool = True
        self._thinking_widget: QWidget | None = None

        if _HAS_MEDIA:
            self._audio_output = QAudioOutput()
            self._player = QMediaPlayer()
            self._player.setAudioOutput(self._audio_output)
        else:
            self._player = None
            self._audio_output = None

        self._build_ui()
        self._append_system(
            "tracksmith ready.  /fill  /vibe <text>  /suggest  /analyze  /mix  /stems  /style <artist>\n"
            "Drop a MIDI or MP3 on the right, then type a command."
        )

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Header: wordmark + waveform + agent status ────────────────────────
        header = QWidget()
        header.setObjectName("chat_header")
        header.setFixedHeight(64)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(22, 10, 22, 10)

        wordmark = _WordmarkWidget(22)
        hl.addWidget(wordmark)

        hl.addStretch()

        # Agent status — 6px amber dot + label (matches template)
        agent_w = QWidget()
        agent_l = QHBoxLayout(agent_w)
        agent_l.setContentsMargins(0, 0, 0, 4)
        agent_l.setSpacing(6)
        agent_l.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self._agent_dot = QLabel()
        self._agent_dot.setFixedSize(6, 6)
        self._agent_dot.setStyleSheet("background-color:#e8a268; border-radius:3px;")
        agent_l.addWidget(self._agent_dot)

        self._lbl_agent = QLabel("agent on")
        self._lbl_agent.setStyleSheet("color:rgba(244,237,225,0.34); font-size:11px;")
        agent_l.addWidget(self._lbl_agent)

        hl.addWidget(agent_w)
        layout.addWidget(header)

        # ── Session pill (hidden until file analyzed) ──────────────────────────
        self._session_row = QWidget()
        self._session_row.setVisible(False)
        sl = QHBoxLayout(self._session_row)
        sl.setContentsMargins(22, 10, 22, 2)

        self._session_pill = QWidget()
        self._session_pill.setObjectName("session_pill_widget")
        pill_l = QHBoxLayout(self._session_pill)
        pill_l.setContentsMargins(8, 5, 10, 5)
        pill_l.setSpacing(8)

        self._pill_dot = QLabel("■")
        self._pill_dot.setStyleSheet(
            "color:transparent; font-size:12px;"
            "background:qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            "stop:0 #e8a268,stop:1 #7fb3a3);"
            "border-radius:3px; min-width:14px; max-width:14px;"
            "min-height:14px; max-height:14px;"
        )
        pill_l.addWidget(self._pill_dot)

        self._lbl_pill_name = QLabel("")
        self._lbl_pill_name.setObjectName("session_pill_name")
        pill_l.addWidget(self._lbl_pill_name)

        self._lbl_pill_meta = QLabel("")
        self._lbl_pill_meta.setObjectName("session_pill_meta")
        pill_l.addWidget(self._lbl_pill_meta)

        sl.addWidget(self._session_pill)
        sl.addStretch()
        layout.addWidget(self._session_row)

        # ── Message log (widget-based, matches template) ───────────────────────
        self._chat_log = _ChatLog()
        layout.addWidget(self._chat_log, stretch=1)

        # ── Audio preview panel (placed in right panel by app.py, not here) ──────
        # Built here so all logic stays in ChatPanel; parent set by TrackSmithApp.
        self._audio_bar = QWidget()
        self._audio_bar.setObjectName("audio_bar")
        self._audio_bar.setVisible(False)
        av = QVBoxLayout(self._audio_bar)
        av.setContentsMargins(20, 12, 20, 12)
        av.setSpacing(10)

        # Header row — section label + filename
        hdr = QHBoxLayout()
        sec_lbl = QLabel("AUDIO PREVIEW")
        sec_lbl.setObjectName("section_header")
        hdr.addWidget(sec_lbl)
        hdr.addStretch()
        self._lbl_audio = QLabel("")
        self._lbl_audio.setObjectName("audio_label")
        hdr.addWidget(self._lbl_audio)
        av.addLayout(hdr)

        # Seek slider + time label
        seek_row = QHBoxLayout()
        seek_row.setSpacing(8)
        self._audio_seek = QSlider(Qt.Orientation.Horizontal)
        self._audio_seek.setRange(0, 1000)
        self._audio_seek.setValue(0)
        self._audio_seek.setFixedHeight(14)
        self._audio_seek.sliderMoved.connect(self._on_audio_seek)
        seek_row.addWidget(self._audio_seek, stretch=1)
        self._audio_time = QLabel("0:00")
        self._audio_time.setStyleSheet(
            "color:rgba(244,237,225,0.34); font-size:10px; background:transparent; border:none;"
        )
        self._audio_time.setFixedWidth(36)
        seek_row.addWidget(self._audio_time)
        av.addLayout(seek_row)

        # Button row — all controls clearly visible
        btns = QHBoxLayout()
        btns.setSpacing(8)

        self._btn_play = QPushButton("▶  Play")
        self._btn_play.setObjectName("fl_btn_primary")
        self._btn_play.clicked.connect(self._toggle_play)
        btns.addWidget(self._btn_play, stretch=1)

        self._btn_toggle_audio = QPushButton("Solo")
        self._btn_toggle_audio.setObjectName("fl_btn")
        self._btn_toggle_audio.setToolTip("Toggle between combined mix and fill-only audio")
        self._btn_toggle_audio.clicked.connect(self._toggle_audio_mode)
        self._btn_toggle_audio.setVisible(False)
        btns.addWidget(self._btn_toggle_audio)

        self._btn_stems = QPushButton("Separate Stems")
        self._btn_stems.setObjectName("fl_btn")
        self._btn_stems.clicked.connect(self._separate_stems)
        btns.addWidget(self._btn_stems)

        av.addLayout(btns)
        # NOTE: not added to chat layout — app.py inserts it into the right panel

        # ── Composer — matches template ChatComposer ────────────────────────────
        composer_wrap = QWidget()
        composer_wrap.setFixedHeight(68)
        composer_wrap.setStyleSheet("border-top:1px solid rgba(255,240,210,0.09);")
        outer = QVBoxLayout(composer_wrap)
        outer.setContentsMargins(16, 10, 16, 10)
        outer.setSpacing(0)

        composer_box = QWidget()
        composer_box.setObjectName("composer_box")
        inner = QHBoxLayout(composer_box)
        inner.setContentsMargins(14, 10, 10, 10)
        inner.setSpacing(10)

        vinyl_icon = _VinylIcon(size=16)
        inner.addWidget(vinyl_icon)

        self.input = QLineEdit()
        self.input.setObjectName("composer_input")
        self.input.setPlaceholderText("ask, hum, or drop a reference…")
        self.input.returnPressed.connect(self.send)
        inner.addWidget(self.input, stretch=1)

        self._kbd_badge = QLabel("⌘K")
        self._kbd_badge.setObjectName("kbd_badge")
        inner.addWidget(self._kbd_badge)

        outer.addWidget(composer_box)
        layout.addWidget(composer_wrap)

    # ── public API ────────────────────────────────────────────────────────────

    def set_midi_path(self, path: str):
        self._midi_path = path
        self._append_system(f"Loaded: {Path(path).name}")

    def set_session(self, name: str, key: str, bpm: int):
        self._lbl_pill_name.setText(name)
        self._lbl_pill_meta.setText(f"· {bpm} bpm · {key}" if key else f"· {bpm} bpm")
        self._session_row.setVisible(True)

    def set_output_dir(self, output_dir: str):
        self.output_dir = output_dir

    # ── audio controls ────────────────────────────────────────────────────────

    def _set_audio(self, audio_path: str | None, combined: str | None = None, continuation: str | None = None):
        self._audio_combined = combined
        self._audio_continuation = continuation
        self._showing_combined = True

        has_both = bool(combined and continuation)
        self._btn_toggle_audio.setVisible(has_both)
        if has_both:
            self._btn_toggle_audio.setText("Solo")

        self._latest_audio = audio_path
        if not audio_path:
            self._audio_bar.setVisible(False)
            return

        self._audio_bar.setVisible(True)
        self._lbl_audio.setText(Path(audio_path).name)
        self._btn_play.setText("▶ Play")
        self._audio_seek.setValue(0)
        self._audio_time.setText("0:00")

        if self._player:
            self._player.positionChanged.connect(self._on_player_position)
            self._player.durationChanged.connect(self._on_player_duration)
            self._player.setSource(QUrl.fromLocalFile(audio_path))

        if not _HAS_MEDIA:
            self._btn_play.setToolTip("PyQt6.QtMultimedia not installed — use Open Folder to play manually")

    def _toggle_audio_mode(self):
        if not self._audio_combined or not self._audio_continuation:
            return
        self._showing_combined = not self._showing_combined
        path = self._audio_combined if self._showing_combined else self._audio_continuation
        self._btn_toggle_audio.setText("Solo" if self._showing_combined else "Combined")
        self._latest_audio = path
        self._lbl_audio.setText(Path(path).name)
        self._btn_play.setText("▶ Play")
        if self._player:
            self._player.stop()
            self._player.setSource(QUrl.fromLocalFile(path))

    def _toggle_play(self):
        if not self._latest_audio:
            return
        if self._player:
            if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self._player.pause()
                self._btn_play.setText("▶ Play")
            else:
                self._player.play()
                self._btn_play.setText("⏸ Pause")
        else:
            _open_with_system(self._latest_audio)

    def _on_player_position(self, pos_ms: int):
        if not self._player:
            return
        dur = self._player.duration()
        if dur > 0 and not self._audio_seek.isSliderDown():
            self._audio_seek.setValue(int(pos_ms * 1000 / dur))
        s = pos_ms // 1000
        self._audio_time.setText(f"{s // 60}:{s % 60:02d}")

    def _on_player_duration(self, dur_ms: int):
        self._audio_seek.setValue(0)

    def _on_audio_seek(self, value: int):
        if self._player:
            dur = self._player.duration()
            if dur > 0:
                self._player.setPosition(int(value * dur / 1000))

    def _open_audio_folder(self):
        target = self._latest_audio or (self.output_dir if self.output_dir else None)
        if not target:
            return
        _open_with_system(str(Path(target).parent))

    def _separate_stems(self):
        target = self._latest_audio or self._midi_path
        if not target:
            self._append_error("No audio loaded. Run /fill first to generate audio.")
            return
        path = Path(target)
        if path.suffix.lower() not in {".wav", ".mp3", ".aiff", ".flac", ".ogg", ".m4a"}:
            self._append_error(
                f"Stem separation needs audio (WAV/MP3), not {path.suffix}.\n"
                "Run /fill first — audio generates when DGX audio server is online."
            )
            return
        self._dispatch_stems(str(path))

    def _dispatch_stems(self, audio_path: str):
        from plugin.commands.stems import run as stems_run
        self._set_busy(True)
        self._append_system(f"Separating stems from {Path(audio_path).name}...")
        self._worker = _InferenceWorker(stems_run, audio_path, self.output_dir)
        self._worker.done.connect(self._on_result)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(lambda: self._set_busy(False))
        self._worker.start()

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
        # Emit the slash command word so the transport can highlight it
        first = raw.strip().split()[0].lower() if raw.strip() else ""
        if first.startswith("/"):
            self.command_started.emit(first)
        self._set_busy(True)
        try:
            wave = _WaveWidget()
            self._chat_log.add_widget(wave)
            self._thinking_widget = wave
        except Exception:
            self._append_system("processing...")
        self._worker = _InferenceWorker(
            route, raw, self._midi_path, self._style_context, self.output_dir,
        )
        self._worker.done.connect(self._on_result)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(lambda: self._set_busy(False))
        self._worker.start()

    # ── result handling ───────────────────────────────────────────────────────

    def _on_result(self, result: dict):
        self._remove_thinking()
        rtype = result.get("type", "text")
        msg   = result.get("message", "")

        if rtype == "error":
            self._append_error(msg)
        elif rtype == "style":
            self._style_context = result.get("style")
            self._append_agent(msg)
        elif rtype == "files":
            files = result.get("files", [])
            pills = [
                ((f.get("vibe") or Path(f.get("filepath", "")).stem)[:22],
                 _PILL_COLORS[i % len(_PILL_COLORS)])
                for i, f in enumerate(files[:4])
            ]
            self._append_agent(msg, pills=pills or None)
            self._set_audio(
                result.get("audio_path"),
                combined=result.get("audio_combined"),
                continuation=result.get("audio_continuation"),
            )
            if files:
                self.files_ready.emit(files, self.output_dir)
            self._append_policy_log()
        elif rtype == "stems":
            self._append_agent(msg)
            stems_dir = result.get("stems_dir", "")
            if stems_dir:
                self._append_system(f"Stems saved to: {stems_dir}")
        else:
            self._append_agent(msg)

    def _on_error(self, err: str):
        self._remove_thinking()
        self._append_error(f"Error: {err}")

    # ── message helpers ───────────────────────────────────────────────────────

    def _append_user(self, text: str):
        self._chat_log.add_widget(_UserMsg(text))

    def _append_agent(self, text: str, pills=None,
                      on_accept=None, on_tweak=None, on_skip=None):
        self._chat_log.add_widget(
            _AgentMsg(text, pills=pills,
                      on_accept=on_accept, on_tweak=on_tweak, on_skip=on_skip)
        )

    # keep alias for any external callers
    def _append_aux(self, text: str):
        self._append_agent(text)

    def _append_system(self, text: str):
        w = _SystemMsg(text)
        if text.startswith("thinking"):
            self._thinking_widget = w
        self._chat_log.add_widget(w)

    def _append_error(self, text: str):
        self._chat_log.add_widget(_ErrorMsg(text))

    def _append_policy_log(self):
        try:
            from agent.openclaw_client import openclaw
            entries = openclaw.get_recent_log(5)
            if entries:
                self._chat_log.add_widget(_PolicyLogMsg(entries))
        except Exception:
            pass

    def _remove_thinking(self):
        if self._thinking_widget:
            if hasattr(self._thinking_widget, "stop"):
                self._thinking_widget.stop()
            self._chat_log.remove_widget(self._thinking_widget)
            self._thinking_widget = None

    def _set_busy(self, busy: bool):
        self.input.setEnabled(not busy)
        self.input.setPlaceholderText(
            "thinking…" if busy else "ask, hum, or drop a reference…"
        )
        self._kbd_badge.setStyleSheet(
            "color:rgba(232,162,104,0.7); font-size:10px; padding:4px 7px;"
            "border:1px solid rgba(232,162,104,0.3); border-radius:5px; background:transparent;"
            if busy else ""
        )


def _open_with_system(path: str):
    if sys.platform == "darwin":
        subprocess.Popen(["open", path])
    elif sys.platform == "win32":
        subprocess.Popen(["explorer", path])
    else:
        subprocess.Popen(["xdg-open", path])
