"""Main control window for BAVEL application."""

from __future__ import annotations

import logging
from functools import partial

from PySide6.QtCore import Qt, Signal, Slot, QSize
from PySide6.QtGui import QIcon, QFont
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QPushButton, QSlider, QGroupBox,
    QGridLayout, QListWidget, QListWidgetItem, QMessageBox,
    QTabWidget, QScrollArea, QFrame,
)

from src.core.config import ConfigManager, AppConfig, DEFAULT_HOTKEYS
from src.core.hotkey_manager import HotkeyManager
from src.ui.styles import DARK_THEME
from src.ui.window_selector import WindowEnumerator, WindowInfo
from src.ui.overlay import OverlayWidget

logger = logging.getLogger(__name__)

LANGUAGES = [
    ("auto", "Auto Detect"),
    ("en", "English"),
    ("ko", "Korean (한국어)"),
    ("ja", "Japanese (日本語)"),
    ("zh", "Chinese (中文)"),
    ("es", "Spanish (Español)"),
    ("fr", "French (Français)"),
    ("de", "German (Deutsch)"),
    ("pt", "Portuguese (Português)"),
    ("ru", "Russian (Русский)"),
    ("ar", "Arabic (العربية)"),
    ("hi", "Hindi (हिन्दी)"),
    ("vi", "Vietnamese (Tiếng Việt)"),
    ("th", "Thai (ไทย)"),
    ("id", "Indonesian (Bahasa Indonesia)"),
]

STT_MODELS = [
    "large-v3-turbo",
    "large-v3",
    "medium",
    "small",
    "base",
    "tiny",
]

HOTKEY_LABELS = {
    "toggle_translation": "Start/Stop Translation",
    "pause_resume": "Pause/Resume",
    "reset_speakers": "Reset Speakers",
    "toggle_overlay": "Toggle Overlay",
    "increase_font": "Increase Font",
    "decrease_font": "Decrease Font",
    "clear_subtitles": "Clear Subtitles",
}


class MainWindow(QMainWindow):
    """Main control panel for BAVEL."""

    translation_start_requested = Signal()
    translation_stop_requested = Signal()
    window_selected = Signal(int, int)  # hwnd, pid
    language_changed = Signal(str, str)  # source, target
    model_changed = Signal(str)
    speaker_reset_requested = Signal()

    def __init__(
        self,
        config_manager: ConfigManager,
        hotkey_manager: HotkeyManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config_manager
        self._hotkey = hotkey_manager
        self._is_translating = False
        self._windows: list[WindowInfo] = []

        self._setup_window()
        self._build_ui()
        self._apply_config()
        self._connect_signals()

    def _setup_window(self) -> None:
        self.setWindowTitle("BAVEL")
        self.setMinimumSize(420, 580)
        self.resize(440, 640)
        self.setStyleSheet(DARK_THEME)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(16, 12, 16, 12)
        root_layout.setSpacing(12)

        # Title
        title = QLabel("BAVEL")
        title.setObjectName("title-label")
        title.setAlignment(Qt.AlignmentFlag.AlignLeft)
        root_layout.addWidget(title)

        # Tabs
        tabs = QTabWidget()
        tabs.addTab(self._build_main_tab(), "Main")
        tabs.addTab(self._build_hotkey_tab(), "Hotkeys")
        root_layout.addWidget(tabs)

        # Status bar
        self._status_label = QLabel("Status: Ready")
        self._status_label.setObjectName("status-label")
        root_layout.addWidget(self._status_label)

    def _build_main_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)

        # --- Window Selection ---
        win_group = QGroupBox("Target Window")
        win_layout = QHBoxLayout(win_group)
        self._window_combo = QComboBox()
        self._window_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        win_layout.addWidget(self._window_combo, 1)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_windows)
        win_layout.addWidget(refresh_btn)
        layout.addWidget(win_group)

        # --- Language Selection ---
        lang_group = QGroupBox("Language")
        lang_grid = QGridLayout(lang_group)

        lang_grid.addWidget(QLabel("Source Language"), 0, 0)
        self._source_lang_combo = QComboBox()
        for code, name in LANGUAGES:
            self._source_lang_combo.addItem(name, code)
        lang_grid.addWidget(self._source_lang_combo, 0, 1)

        lang_grid.addWidget(QLabel("Target Language"), 1, 0)
        self._target_lang_combo = QComboBox()
        for code, name in LANGUAGES:
            if code == "auto":
                continue
            self._target_lang_combo.addItem(name, code)
        lang_grid.addWidget(self._target_lang_combo, 1, 1)
        layout.addWidget(lang_group)

        # --- STT & LM Studio ---
        engine_group = QGroupBox("Engine")
        engine_grid = QGridLayout(engine_group)

        engine_grid.addWidget(QLabel("STT Model"), 0, 0)
        self._model_combo = QComboBox()
        for m in STT_MODELS:
            self._model_combo.addItem(m)
        engine_grid.addWidget(self._model_combo, 0, 1)

        engine_grid.addWidget(QLabel("LM Studio"), 1, 0)
        self._lm_status_label = QLabel("Checking...")
        engine_grid.addWidget(self._lm_status_label, 1, 1)
        layout.addWidget(engine_group)

        # --- Start/Stop Button ---
        self._start_stop_btn = QPushButton("Start Translation")
        self._start_stop_btn.setObjectName("start-btn")
        self._start_stop_btn.clicked.connect(self._toggle_translation)
        layout.addWidget(self._start_stop_btn)

        # --- Speaker Reset ---
        self._reset_speakers_btn = QPushButton("Reset Speakers")
        self._reset_speakers_btn.clicked.connect(self.speaker_reset_requested.emit)
        layout.addWidget(self._reset_speakers_btn)

        # --- Overlay Settings ---
        overlay_group = QGroupBox("Overlay Settings")
        overlay_grid = QGridLayout(overlay_group)

        overlay_grid.addWidget(QLabel("Font Size"), 0, 0)
        self._font_slider = QSlider(Qt.Orientation.Horizontal)
        self._font_slider.setRange(8, 48)
        self._font_label = QLabel()
        overlay_grid.addWidget(self._font_slider, 0, 1)
        overlay_grid.addWidget(self._font_label, 0, 2)

        overlay_grid.addWidget(QLabel("Opacity"), 1, 0)
        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(10, 100)
        self._opacity_label = QLabel()
        overlay_grid.addWidget(self._opacity_slider, 1, 1)
        overlay_grid.addWidget(self._opacity_label, 1, 2)

        overlay_grid.addWidget(QLabel("Max Lines"), 2, 0)
        self._lines_slider = QSlider(Qt.Orientation.Horizontal)
        self._lines_slider.setRange(1, 20)
        self._lines_label = QLabel()
        overlay_grid.addWidget(self._lines_slider, 2, 1)
        overlay_grid.addWidget(self._lines_label, 2, 2)

        layout.addWidget(overlay_group)
        layout.addStretch()
        return tab

    def _build_hotkey_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(8)

        desc = QLabel("Click a hotkey to reassign (press new key combo)")
        desc.setObjectName("status-label")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        self._hotkey_buttons: dict[str, QPushButton] = {}
        grid = QGridLayout()
        row = 0
        for action, label_text in HOTKEY_LABELS.items():
            grid.addWidget(QLabel(label_text), row, 0)
            btn = QPushButton()
            btn.setObjectName("hotkey-btn")
            btn.clicked.connect(partial(self._start_hotkey_capture, action))
            self._hotkey_buttons[action] = btn
            grid.addWidget(btn, row, 1)
            row += 1
        layout.addLayout(grid)

        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.clicked.connect(self._reset_hotkeys)
        layout.addWidget(reset_btn)
        layout.addStretch()
        return tab

    def _apply_config(self) -> None:
        cfg = self._config.config

        # Language
        idx = self._source_lang_combo.findData(cfg.source_language)
        if idx >= 0:
            self._source_lang_combo.setCurrentIndex(idx)
        idx = self._target_lang_combo.findData(cfg.target_language)
        if idx >= 0:
            self._target_lang_combo.setCurrentIndex(idx)

        # Model
        idx = self._model_combo.findText(cfg.stt_model)
        if idx >= 0:
            self._model_combo.setCurrentIndex(idx)

        # Overlay sliders
        self._font_slider.setValue(cfg.overlay.font_size)
        self._font_label.setText(f"{cfg.overlay.font_size}pt")
        self._opacity_slider.setValue(cfg.overlay.opacity)
        self._opacity_label.setText(f"{cfg.overlay.opacity}%")
        self._lines_slider.setValue(cfg.overlay.max_lines)
        self._lines_label.setText(str(cfg.overlay.max_lines))

        # Hotkey buttons
        for action, btn in self._hotkey_buttons.items():
            combo = cfg.hotkeys.get(action, DEFAULT_HOTKEYS.get(action, ""))
            btn.setText(combo)

    def _connect_signals(self) -> None:
        self._window_combo.currentIndexChanged.connect(self._on_window_selected)
        self._source_lang_combo.currentIndexChanged.connect(self._on_language_changed)
        self._target_lang_combo.currentIndexChanged.connect(self._on_language_changed)
        self._model_combo.currentTextChanged.connect(self._on_model_changed)

        self._font_slider.valueChanged.connect(self._on_font_changed)
        self._opacity_slider.valueChanged.connect(self._on_opacity_changed)
        self._lines_slider.valueChanged.connect(self._on_lines_changed)

    # --- Slots ---

    def _refresh_windows(self) -> None:
        self._window_combo.clear()
        self._windows = WindowEnumerator.list_windows()
        for w in self._windows:
            self._window_combo.addItem(f"{w.title}", w.hwnd)
        self._status_label.setText(f"Status: Found {len(self._windows)} windows")

    def _on_window_selected(self, index: int) -> None:
        if 0 <= index < len(self._windows):
            w = self._windows[index]
            self.window_selected.emit(w.hwnd, w.pid)

    def _on_language_changed(self) -> None:
        source = self._source_lang_combo.currentData()
        target = self._target_lang_combo.currentData()
        self._config.update(source_language=source, target_language=target)
        self.language_changed.emit(source, target)

    def _on_model_changed(self, model: str) -> None:
        self._config.update(stt_model=model)
        self.model_changed.emit(model)

    def _on_font_changed(self, value: int) -> None:
        self._font_label.setText(f"{value}pt")
        self._config.update_overlay(font_size=value)

    def _on_opacity_changed(self, value: int) -> None:
        self._opacity_label.setText(f"{value}%")
        self._config.update_overlay(opacity=value)

    def _on_lines_changed(self, value: int) -> None:
        self._lines_label.setText(str(value))
        self._config.update_overlay(max_lines=value)

    def _toggle_translation(self) -> None:
        if self._is_translating:
            self._is_translating = False
            self._start_stop_btn.setText("Start Translation")
            self._start_stop_btn.setObjectName("start-btn")
            self._start_stop_btn.setStyleSheet("")
            self.style().unpolish(self._start_stop_btn)
            self.style().polish(self._start_stop_btn)
            self.translation_stop_requested.emit()
            self._status_label.setText("Status: Stopped")
        else:
            if self._window_combo.currentIndex() < 0:
                QMessageBox.warning(self, "BAVEL", "Please select a target window first.")
                return
            self._is_translating = True
            self._start_stop_btn.setText("Stop Translation")
            self._start_stop_btn.setObjectName("stop-btn")
            self._start_stop_btn.setStyleSheet("")
            self.style().unpolish(self._start_stop_btn)
            self.style().polish(self._start_stop_btn)
            self.translation_start_requested.emit()
            self._status_label.setText("Status: Translating...")

    def _start_hotkey_capture(self, action: str) -> None:
        btn = self._hotkey_buttons[action]
        btn.setText("Press a key combo...")
        btn.setStyleSheet("border-color: #f9e2af; color: #f9e2af;")

        def on_captured(combo: str) -> None:
            conflict = self._hotkey.check_conflict(combo, exclude_action=action)
            if conflict:
                QMessageBox.warning(
                    self, "Hotkey Conflict",
                    f"'{combo}' is already used by '{HOTKEY_LABELS.get(conflict, conflict)}'."
                )
                btn.setText(self._config.config.hotkeys.get(action, ""))
                btn.setStyleSheet("")
                return
            self._config.update_hotkey(action, combo)
            btn.setText(combo)
            btn.setStyleSheet("")

        self._hotkey.start_capture(on_captured)

    def _reset_hotkeys(self) -> None:
        self._config.reset_hotkeys()
        for action, btn in self._hotkey_buttons.items():
            btn.setText(DEFAULT_HOTKEYS.get(action, ""))

    # --- Public API ---

    def set_lm_status(self, connected: bool, model_name: str = "") -> None:
        if connected:
            self._lm_status_label.setText(f"Connected ({model_name})")
            self._lm_status_label.setObjectName("connected-label")
        else:
            self._lm_status_label.setText("Disconnected")
            self._lm_status_label.setObjectName("disconnected-label")
        self.style().unpolish(self._lm_status_label)
        self.style().polish(self._lm_status_label)

    def set_status(self, text: str) -> None:
        self._status_label.setText(f"Status: {text}")
