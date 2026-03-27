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
    QTabWidget, QScrollArea, QFrame, QDoubleSpinBox, QSpinBox,
    QLineEdit,
)

from src.core.config import (
    ConfigManager, AppConfig, DEFAULT_HOTKEYS,
    AudioSettings, VADSettings, STTSettings, DiarizationSettings, TranslationSettings,
)
from src.core.hotkey_manager import HotkeyManager
from src.translation.translator import PROVIDER_PRESETS
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
    provider_changed = Signal(str, str, str)  # provider, api_key, model

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
        self.setMinimumSize(460, 620)
        self.resize(480, 720)
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
        tabs.addTab(self._build_pipeline_tab(), "Pipeline")
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

        # --- STT Model ---
        stt_group = QGroupBox("STT")
        stt_grid = QGridLayout(stt_group)
        stt_grid.addWidget(QLabel("STT Model"), 0, 0)
        self._model_combo = QComboBox()
        for m in STT_MODELS:
            self._model_combo.addItem(m)
        stt_grid.addWidget(self._model_combo, 0, 1)
        layout.addWidget(stt_group)

        # --- Translation Provider ---
        trans_group = QGroupBox("Translation")
        trans_grid = QGridLayout(trans_group)

        trans_grid.addWidget(QLabel("Provider"), 0, 0)
        self._provider_combo = QComboBox()
        self._provider_combo.addItem("Local (LM Studio)", "local")
        self._provider_combo.addItem("Groq (Free, Fast)", "groq")
        self._provider_combo.addItem("Google Gemini (Free)", "gemini")
        self._provider_combo.addItem("OpenRouter (Free)", "openrouter")
        trans_grid.addWidget(self._provider_combo, 0, 1)

        trans_grid.addWidget(QLabel("API Key"), 1, 0)
        self._api_key_edit = QLineEdit()
        self._api_key_edit.setPlaceholderText("Not needed for Local")
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        trans_grid.addWidget(self._api_key_edit, 1, 1)

        trans_grid.addWidget(QLabel("Model"), 2, 0)
        self._trans_model_edit = QLineEdit()
        trans_grid.addWidget(self._trans_model_edit, 2, 1)

        self._apply_provider_btn = QPushButton("Apply")
        self._apply_provider_btn.clicked.connect(self._on_provider_apply)
        trans_grid.addWidget(self._apply_provider_btn, 3, 1)

        trans_grid.addWidget(QLabel("Status"), 4, 0)
        self._lm_status_label = QLabel("Checking...")
        trans_grid.addWidget(self._lm_status_label, 4, 1)
        layout.addWidget(trans_group)

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

    # ---- Pipeline settings tab ----

    def _build_pipeline_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(10)

        note = QLabel("⚠  변경 사항은 저장 즉시 반영되지만, 일부 설정은 다음 Start 시 적용됩니다.")
        note.setObjectName("status-label")
        note.setWordWrap(True)
        layout.addWidget(note)

        self._pipeline_spins: dict[str, QDoubleSpinBox | QSpinBox] = {}

        # --- Audio ---
        layout.addWidget(self._pipeline_group("Audio  오디오", [
            ("audio.chunk_duration", "Chunk Duration (s)", "오디오를 VAD에 전달하는 주기. 작을수록 실시간 반응↑",
             "float", 0.1, 5.0, 0.1, 2),
        ]))

        # --- VAD ---
        layout.addWidget(self._pipeline_group("VAD  음성 감지", [
            ("vad.speech_threshold", "Speech Threshold", "음성 판별 임계치. 낮으면 민감, 높으면 보수적",
             "float", 0.1, 0.95, 0.05, 2),
            ("vad.onset_frames", "Onset Frames", "음성 시작 확인에 필요한 연속 프레임 (1 frame ≈ 32ms)",
             "int", 1, 10, 1, 0),
            ("vad.offset_frames", "Offset Frames", "발화 종료 확인에 필요한 연속 무음 프레임. 작을수록 빠르게 끊김",
             "int", 3, 30, 1, 0),
            ("vad.pre_roll_frames", "Pre-roll Frames", "발화 시작 전 포함할 여유 프레임 (첫 음절 보존)",
             "int", 0, 10, 1, 0),
            ("vad.min_utterance_sec", "Min Utterance (s)", "무시할 최소 발화 길이. 짧은 잡음 제거",
             "float", 0.1, 2.0, 0.1, 1),
            ("vad.max_utterance_sec", "Max Utterance (s)", "강제 분할할 최대 발화 길이",
             "float", 3.0, 30.0, 1.0, 1),
        ]))

        # --- STT ---
        layout.addWidget(self._pipeline_group("STT  음성 인식", [
            ("stt.min_language_probability", "Min Language Prob", "언어 감지 최소 신뢰도. 이 미만이면 무시 (잡음 필터)",
             "float", 0.3, 1.0, 0.05, 2),
            ("stt.beam_size", "Beam Size", "Whisper beam search 너비. 클수록 정확하지만 느림",
             "int", 1, 10, 1, 0),
        ]))

        # --- Diarization ---
        layout.addWidget(self._pipeline_group("Diarization  화자 분류", [
            ("diarization.max_speakers", "Max Speakers", "최대 동시 인식 화자 수",
             "int", 2, 16, 1, 0),
            ("diarization.tau_active", "Tau Active", "화자 활성도 임계치. 높으면 확실한 발화만 인식",
             "float", 0.1, 0.95, 0.05, 2),
            ("diarization.rho_update", "Rho Update", "화자 임베딩 업데이트 강도. 낮으면 보수적 (과잉분류 방지)",
             "float", 0.05, 0.9, 0.05, 2),
            ("diarization.delta_new", "Delta New", "새 화자 생성 임계치. 높을수록 새 화자 생성이 어려움",
             "float", 0.5, 3.5, 0.1, 1),
            ("diarization.min_segment_duration", "Min Segment (s)", "무시할 최소 세그먼트 길이",
             "float", 0.1, 2.0, 0.1, 1),
        ]))

        # --- Translation ---
        layout.addWidget(self._pipeline_group("Translation  번역", [
            ("translation.temperature", "Temperature", "LLM 온도. 낮을수록 결정적 (번역에 적합)",
             "float", 0.0, 1.0, 0.1, 1),
            ("translation.max_tokens", "Max Tokens", "번역 결과 최대 토큰 수",
             "int", 64, 2048, 64, 0),
            ("translation.max_cache_size", "Cache Size", "번역 캐시 최대 항목 수",
             "int", 0, 2000, 50, 0),
            ("translation.request_timeout", "Timeout (s)", "API 요청 타임아웃",
             "float", 5.0, 120.0, 5.0, 0),
        ]))

        # --- Buttons ---
        btn_row = QHBoxLayout()
        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.clicked.connect(self._reset_pipeline_defaults)
        btn_row.addWidget(reset_btn)

        open_btn = QPushButton("Open config.json")
        open_btn.clicked.connect(self._open_config_file)
        btn_row.addWidget(open_btn)
        layout.addLayout(btn_row)

        layout.addStretch()
        scroll.setWidget(container)
        return scroll

    def _pipeline_group(self, title: str, params: list) -> QGroupBox:
        """Build a group box with rows of: Label  [SpinBox]  Description."""
        group = QGroupBox(title)
        grid = QGridLayout(group)
        grid.setColumnStretch(2, 1)

        for row_idx, (key, label, desc, dtype, lo, hi, step, decimals) in enumerate(params):
            name_label = QLabel(label)
            name_label.setMinimumWidth(130)
            grid.addWidget(name_label, row_idx * 2, 0)

            if dtype == "float":
                spin = QDoubleSpinBox()
                spin.setRange(lo, hi)
                spin.setSingleStep(step)
                spin.setDecimals(decimals)
            else:
                spin = QSpinBox()
                spin.setRange(int(lo), int(hi))
                spin.setSingleStep(int(step))

            spin.setMinimumWidth(90)
            spin.setMaximumWidth(110)
            grid.addWidget(spin, row_idx * 2, 1)
            self._pipeline_spins[key] = spin

            spin.valueChanged.connect(self._on_pipeline_value_changed)

            desc_label = QLabel(desc)
            desc_label.setStyleSheet("color: #a6adc8; font-size: 9pt;")
            desc_label.setWordWrap(True)
            grid.addWidget(desc_label, row_idx * 2 + 1, 0, 1, 3)

        return group

    def _apply_pipeline_config(self) -> None:
        cfg = self._config.config
        mapping = {
            "audio.chunk_duration": cfg.audio.chunk_duration,
            "audio.sample_rate": cfg.audio.sample_rate,
            "vad.speech_threshold": cfg.vad.speech_threshold,
            "vad.onset_frames": cfg.vad.onset_frames,
            "vad.offset_frames": cfg.vad.offset_frames,
            "vad.pre_roll_frames": cfg.vad.pre_roll_frames,
            "vad.min_utterance_sec": cfg.vad.min_utterance_sec,
            "vad.max_utterance_sec": cfg.vad.max_utterance_sec,
            "stt.min_language_probability": cfg.stt.min_language_probability,
            "stt.beam_size": cfg.stt.beam_size,
            "diarization.max_speakers": cfg.diarization.max_speakers,
            "diarization.tau_active": cfg.diarization.tau_active,
            "diarization.rho_update": cfg.diarization.rho_update,
            "diarization.delta_new": cfg.diarization.delta_new,
            "diarization.min_segment_duration": cfg.diarization.min_segment_duration,
            "translation.temperature": cfg.translation.temperature,
            "translation.max_tokens": cfg.translation.max_tokens,
            "translation.max_cache_size": cfg.translation.max_cache_size,
            "translation.request_timeout": cfg.translation.request_timeout,
        }
        for key, spin in self._pipeline_spins.items():
            if key in mapping:
                spin.blockSignals(True)
                spin.setValue(mapping[key])
                spin.blockSignals(False)

    def _on_pipeline_value_changed(self) -> None:
        cfg = self._config.config

        cfg.audio.chunk_duration = self._pipeline_spins["audio.chunk_duration"].value()
        cfg.vad.speech_threshold = self._pipeline_spins["vad.speech_threshold"].value()
        cfg.vad.onset_frames = self._pipeline_spins["vad.onset_frames"].value()
        cfg.vad.offset_frames = self._pipeline_spins["vad.offset_frames"].value()
        cfg.vad.pre_roll_frames = self._pipeline_spins["vad.pre_roll_frames"].value()
        cfg.vad.min_utterance_sec = self._pipeline_spins["vad.min_utterance_sec"].value()
        cfg.vad.max_utterance_sec = self._pipeline_spins["vad.max_utterance_sec"].value()
        cfg.stt.min_language_probability = self._pipeline_spins["stt.min_language_probability"].value()
        cfg.stt.beam_size = self._pipeline_spins["stt.beam_size"].value()
        cfg.diarization.max_speakers = self._pipeline_spins["diarization.max_speakers"].value()
        cfg.diarization.tau_active = self._pipeline_spins["diarization.tau_active"].value()
        cfg.diarization.rho_update = self._pipeline_spins["diarization.rho_update"].value()
        cfg.diarization.delta_new = self._pipeline_spins["diarization.delta_new"].value()
        cfg.diarization.min_segment_duration = self._pipeline_spins["diarization.min_segment_duration"].value()
        cfg.translation.temperature = self._pipeline_spins["translation.temperature"].value()
        cfg.translation.max_tokens = self._pipeline_spins["translation.max_tokens"].value()
        cfg.translation.max_cache_size = self._pipeline_spins["translation.max_cache_size"].value()
        cfg.translation.request_timeout = self._pipeline_spins["translation.request_timeout"].value()

        self._config.save()

    def _reset_pipeline_defaults(self) -> None:
        cfg = self._config.config
        cfg.audio = AudioSettings()
        cfg.vad = VADSettings()
        cfg.stt = STTSettings()
        cfg.diarization = DiarizationSettings()
        cfg.translation = TranslationSettings()
        self._config.save()
        self._apply_pipeline_config()

    def _open_config_file(self) -> None:
        import os
        from src.core.config import CONFIG_FILE
        self._config.save()
        os.startfile(str(CONFIG_FILE))

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

        # Translation provider
        prov_idx = self._provider_combo.findData(cfg.translation_provider)
        if prov_idx >= 0:
            self._provider_combo.setCurrentIndex(prov_idx)
        self._api_key_edit.setText(cfg.translation_api_key)
        self._trans_model_edit.setText(cfg.translation_model)
        self._update_provider_ui_hints(cfg.translation_provider)

        # Overlay sliders
        self._font_slider.setValue(cfg.overlay.font_size)
        self._font_label.setText(f"{cfg.overlay.font_size}pt")
        self._opacity_slider.setValue(cfg.overlay.opacity)
        self._opacity_label.setText(f"{cfg.overlay.opacity}%")
        self._lines_slider.setValue(cfg.overlay.max_lines)
        self._lines_label.setText(str(cfg.overlay.max_lines))

        # Pipeline tab
        self._apply_pipeline_config()

        # Hotkey buttons
        for action, btn in self._hotkey_buttons.items():
            combo = cfg.hotkeys.get(action, DEFAULT_HOTKEYS.get(action, ""))
            btn.setText(combo)

    def _connect_signals(self) -> None:
        self._window_combo.currentIndexChanged.connect(self._on_window_selected)
        self._source_lang_combo.currentIndexChanged.connect(self._on_language_changed)
        self._target_lang_combo.currentIndexChanged.connect(self._on_language_changed)
        self._model_combo.currentTextChanged.connect(self._on_model_changed)
        self._provider_combo.currentIndexChanged.connect(self._on_provider_combo_changed)

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

    def _on_provider_combo_changed(self, index: int) -> None:
        provider = self._provider_combo.currentData()
        self._update_provider_ui_hints(provider)

    def _update_provider_ui_hints(self, provider: str) -> None:
        preset = PROVIDER_PRESETS.get(provider, {})
        needs_key = preset.get("needs_key", False)
        self._api_key_edit.setEnabled(needs_key)
        if not needs_key:
            self._api_key_edit.setPlaceholderText("Not needed for Local")
        else:
            self._api_key_edit.setPlaceholderText("Enter API key")
        if not self._trans_model_edit.text() or self._trans_model_edit.text() in [
            p.get("default_model", "") for p in PROVIDER_PRESETS.values()
        ]:
            self._trans_model_edit.setText(preset.get("default_model", ""))

    def _on_provider_apply(self) -> None:
        provider = self._provider_combo.currentData()
        api_key = self._api_key_edit.text().strip()
        model = self._trans_model_edit.text().strip()

        preset = PROVIDER_PRESETS.get(provider, {})
        if preset.get("needs_key") and not api_key:
            QMessageBox.warning(self, "BAVEL", f"API key is required for {provider}.")
            return

        self._config.update(
            translation_provider=provider,
            translation_api_key=api_key,
            translation_model=model or preset.get("default_model", ""),
        )
        self.provider_changed.emit(provider, api_key, model)
        self._lm_status_label.setText("Reconnecting...")

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
