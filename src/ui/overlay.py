"""Floating subtitle overlay — always-on-top, draggable, semi-transparent."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from PySide6.QtCore import Qt, QPoint, QTimer, QPropertyAnimation, QEasingCurve, Signal, Slot
from PySide6.QtGui import QColor, QFont, QPainter, QBrush, QPen, QMouseEvent, QScreen
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGraphicsOpacityEffect, QApplication

from src.core.config import SPEAKER_COLORS

logger = logging.getLogger(__name__)


@dataclass
class SubtitleLine:
    speaker_id: int
    speaker_label: str
    translated: str
    original: str
    color: str


class SubtitleLabel(QLabel):
    """A single subtitle entry: translated text + original in parentheses."""

    def __init__(self, line: SubtitleLine, font_size: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._line = line

        self.setTextFormat(Qt.TextFormat.RichText)

        original_same = line.translated.strip() == line.original.strip()
        if original_same:
            # No translation available — show original only
            self.setText(
                f'<span style="color:{line.color}; font-weight:bold;">'
                f'{line.speaker_label}</span>: {line.original}'
            )
        else:
            sub_font_size = max(8, font_size - 4)
            self.setText(
                f'<span style="color:{line.color}; font-weight:bold;">'
                f'{line.speaker_label}</span>: {line.translated}<br>'
                f'<span style="color:#a6adc8; font-size:{sub_font_size}pt;">'
                f'({line.original})</span>'
            )

        font = QFont("Segoe UI", font_size)
        self.setFont(font)
        self.setStyleSheet("color: #cdd6f4; background: transparent;")
        self.setWordWrap(True)

        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_effect)

        self._fade_in = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._fade_in.setDuration(250)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade_in.start()

    def fade_out(self, on_finished: callable = None) -> None:
        anim = QPropertyAnimation(self._opacity_effect, b"opacity")
        anim.setDuration(400)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.InCubic)
        if on_finished:
            anim.finished.connect(on_finished)
        anim.start()
        self._fade_out_anim = anim


class SpeakerNotification(QLabel):
    """Temporary notification badge for new speaker detection."""

    def __init__(self, speaker_label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText(f"  + New speaker detected ({speaker_label})  ")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont("Segoe UI", 9, QFont.Weight.Bold)
        self.setFont(font)
        self.setStyleSheet(
            "background-color: rgba(137, 180, 250, 200);"
            "color: #1e1e2e; font-weight: bold;"
            "border-radius: 6px; padding: 4px 10px; margin: 2px;"
        )
        self.adjustSize()
        QTimer.singleShot(3000, self._start_fade_out)

    def _start_fade_out(self) -> None:
        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity")
        anim.setDuration(400)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.finished.connect(self.deleteLater)
        anim.start()
        self._anim = anim


class OverlayWidget(QWidget):
    """Floating subtitle bar — always on top, draggable, semi-transparent.

    Displays recent subtitle lines in a compact strip.  The user can
    click-and-drag anywhere on it to reposition.
    """

    def __init__(
        self,
        max_lines: int = 5,
        font_size: int = 18,
        opacity_percent: int = 80,
    ) -> None:
        super().__init__()

        self._max_lines = max_lines
        self._font_size = font_size
        self._opacity_percent = opacity_percent
        self._subtitle_labels: list[SubtitleLabel] = []
        self._speaker_colors: list[str] = list(SPEAKER_COLORS)

        self._drag_pos: QPoint | None = None

        self._setup_window()
        self._setup_layout()
        self._position_default()

        # Re-assert topmost every 2 s so fullscreen apps can't bury us
        self._topmost_timer = QTimer(self)
        self._topmost_timer.setInterval(2000)
        self._topmost_timer.timeout.connect(self._ensure_topmost)
        self._topmost_timer.start()

    def _setup_window(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setMinimumWidth(400)

    def _setup_layout(self) -> None:
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(0)

        self._notification_area = QVBoxLayout()
        self._notification_area.setContentsMargins(8, 4, 8, 0)
        self._notification_area.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter
        )
        self._root.addLayout(self._notification_area)

        self._subtitle_area = QVBoxLayout()
        self._subtitle_area.setContentsMargins(12, 8, 12, 8)
        self._subtitle_area.setSpacing(2)
        self._root.addLayout(self._subtitle_area)

    def _position_default(self) -> None:
        """Place the bar at the bottom-center of the primary screen."""
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        w = min(800, geo.width() - 100)
        h = 200
        x = geo.x() + (geo.width() - w) // 2
        y = geo.y() + geo.height() - h - 40
        self.setGeometry(x, y, w, h)

    # ---- painting ----

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        alpha = int(255 * self._opacity_percent / 100)
        bg = QColor(17, 17, 27, alpha)
        painter.setBrush(QBrush(bg))
        painter.setPen(QPen(QColor(69, 71, 90, alpha), 1))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 12, 12)

        painter.end()

    # ---- drag ----

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_pos = None
        event.accept()

    # ---- subtitles ----

    @Slot(str, str, str, int)
    def add_subtitle(self, translated: str, original: str, speaker_label: str, speaker_id: int) -> None:
        color_idx = (speaker_id - 1) % len(self._speaker_colors)
        color = self._speaker_colors[color_idx]

        line = SubtitleLine(
            speaker_id=speaker_id,
            speaker_label=speaker_label,
            translated=translated,
            original=original,
            color=color,
        )
        label = SubtitleLabel(line, self._font_size, self)
        self._subtitle_area.addWidget(label)
        self._subtitle_labels.append(label)

        while len(self._subtitle_labels) > self._max_lines:
            old = self._subtitle_labels.pop(0)
            old.fade_out(on_finished=lambda w=old: self._remove_label(w))

        self.update()

    def _remove_label(self, label: SubtitleLabel) -> None:
        self._subtitle_area.removeWidget(label)
        label.deleteLater()
        self.update()

    def show_new_speaker(self, speaker_label: str) -> None:
        notif = SpeakerNotification(speaker_label, self)
        self._notification_area.addWidget(notif)

    def clear_subtitles(self) -> None:
        for label in self._subtitle_labels:
            self._subtitle_area.removeWidget(label)
            label.deleteLater()
        self._subtitle_labels.clear()
        self.update()

    # ---- settings ----

    def set_font_size(self, size: int) -> None:
        self._font_size = max(8, min(48, size))
        font = QFont("Segoe UI", self._font_size)
        for label in self._subtitle_labels:
            label.setFont(font)

    def increase_font(self) -> None:
        self.set_font_size(self._font_size + 1)

    def decrease_font(self) -> None:
        self.set_font_size(self._font_size - 1)

    def set_opacity(self, percent: int) -> None:
        self._opacity_percent = max(10, min(100, percent))
        self.update()

    def set_max_lines(self, n: int) -> None:
        self._max_lines = max(1, min(20, n))

    def set_speaker_colors(self, colors: list[str]) -> None:
        self._speaker_colors = colors

    def _ensure_topmost(self) -> None:
        """Re-assert the always-on-top flag via Win32 API.

        Some fullscreen apps or Windows itself can demote TOPMOST
        windows; this timer-driven call puts us back on top.
        """
        if not self.isVisible():
            return
        try:
            import ctypes
            HWND_TOPMOST = -1
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOACTIVATE = 0x0010
            hwnd = int(self.winId())
            ctypes.windll.user32.SetWindowPos(
                hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
            )
        except Exception:
            pass
