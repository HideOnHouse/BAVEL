"""Window enumeration and selection for targeting a specific process."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
from dataclasses import dataclass

import win32gui
import win32process

from PySide6.QtCore import QTimer, Signal, QObject

logger = logging.getLogger(__name__)

# DwmGetWindowAttribute constants
DWMWA_EXTENDED_FRAME_BOUNDS = 9


def _get_accurate_window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    """Get the visible window rect using DWM, falling back to GetWindowRect.

    On Windows 10/11, GetWindowRect includes invisible shadow borders.
    DwmGetWindowAttribute with DWMWA_EXTENDED_FRAME_BOUNDS gives the
    actual visible frame.
    """
    try:
        rect = ctypes.wintypes.RECT()
        result = ctypes.windll.dwmapi.DwmGetWindowAttribute(
            hwnd,
            DWMWA_EXTENDED_FRAME_BOUNDS,
            ctypes.byref(rect),
            ctypes.sizeof(rect),
        )
        if result == 0:
            return (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
    except Exception:
        pass

    try:
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        return (left, top, right - left, bottom - top)
    except Exception:
        return None


@dataclass
class WindowInfo:
    hwnd: int
    pid: int
    title: str
    x: int
    y: int
    width: int
    height: int
    is_visible: bool


class WindowEnumerator:
    """Enumerates visible top-level windows on Windows."""

    @staticmethod
    def list_windows() -> list[WindowInfo]:
        windows: list[WindowInfo] = []

        def _enum_callback(hwnd: int, _extra: object) -> bool:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            title = win32gui.GetWindowText(hwnd)
            if not title or title == "Program Manager":
                return True

            rect = _get_accurate_window_rect(hwnd)
            if rect is None:
                return True
            x, y, width, height = rect
            if width <= 0 or height <= 0:
                return True

            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                windows.append(WindowInfo(
                    hwnd=hwnd, pid=pid, title=title,
                    x=x, y=y, width=width, height=height,
                    is_visible=True,
                ))
            except Exception:
                pass
            return True

        win32gui.EnumWindows(_enum_callback, None)
        return sorted(windows, key=lambda w: w.title.lower())


class WindowTracker(QObject):
    """Tracks a target window's position and size changes."""

    position_changed = Signal(int, int, int, int)  # x, y, w, h
    window_closed = Signal()
    window_minimized = Signal()
    window_restored = Signal()

    def __init__(self, hwnd: int, poll_interval_ms: int = 100) -> None:
        super().__init__()
        self._hwnd = hwnd
        self._timer = QTimer(self)
        self._timer.setInterval(poll_interval_ms)
        self._timer.timeout.connect(self._poll)
        self._last_rect: tuple[int, int, int, int] | None = None
        self._was_minimized = False

    @property
    def hwnd(self) -> int:
        return self._hwnd

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _poll(self) -> None:
        if not win32gui.IsWindow(self._hwnd):
            self.window_closed.emit()
            self._timer.stop()
            return

        if win32gui.IsIconic(self._hwnd):
            if not self._was_minimized:
                self._was_minimized = True
                self.window_minimized.emit()
            return

        if self._was_minimized:
            self._was_minimized = False
            self.window_restored.emit()

        current = _get_accurate_window_rect(self._hwnd)
        if current and current != self._last_rect:
            self._last_rect = current
            self.position_changed.emit(*current)

    def get_current_rect(self) -> tuple[int, int, int, int] | None:
        if not win32gui.IsWindow(self._hwnd):
            return None
        return _get_accurate_window_rect(self._hwnd)

    def set_target(self, hwnd: int) -> None:
        self._hwnd = hwnd
        self._last_rect = None
        self._was_minimized = False
