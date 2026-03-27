"""BAVEL - Real-time Speaker-aware Overlay Translation System.

Entry point that wires all components together:
  Audio Capture -> VAD -> STT + Diarization -> Translation -> Overlay
"""

from __future__ import annotations

# Per-monitor DPI awareness — must be set before any Qt or Win32 window calls
# so that pixel coordinates from Win32 API match Qt's coordinate system.
import ctypes
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# Monkey-patch torchaudio for compatibility with pyannote/diart/speechbrain:
# torchaudio >=2.1 removed legacy backend API; patch in no-op stubs so that
# libraries calling these at import time don't crash.
import torchaudio
if not hasattr(torchaudio, "set_audio_backend"):
    torchaudio.set_audio_backend = lambda backend: None
if not hasattr(torchaudio, "list_audio_backends"):
    torchaudio.list_audio_backends = lambda: ["soundfile"]
if not hasattr(torchaudio, "get_audio_backend"):
    torchaudio.get_audio_backend = lambda: "soundfile"

import logging
import sys
import threading

from PySide6.QtCore import QObject, Signal, Slot, QTimer
from PySide6.QtWidgets import QApplication

from src.core.config import ConfigManager
from src.core.hotkey_manager import HotkeyManager
from src.audio.capture import AudioCapture
from src.audio.stream import AudioStream
from src.audio.vad import VoiceActivityDetector
from src.stt.transcriber import RealtimeTranscriber, TranscriptionSegment
from src.stt.diarizer import RealtimeDiarizer, DiarizationResult
from src.translation.translator import Translator, TranslationResult
from src.ui.main_window import MainWindow
from src.ui.overlay import OverlayWidget

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("bavel")


class Pipeline(QObject):
    """Orchestrates the full audio -> subtitle pipeline and bridges
    worker threads back to the Qt main thread via signals."""

    subtitle_ready = Signal(str, str, str, int)  # translated, original, speaker_label, speaker_id
    new_speaker_detected = Signal(str)  # speaker_label
    lm_status_changed = Signal(bool, str)  # connected, model_name
    status_changed = Signal(str)

    def __init__(self, config: ConfigManager) -> None:
        super().__init__()
        self._config = config
        cfg = config.config

        self._capture: AudioCapture | None = None
        self._stream = AudioStream(settings=cfg.audio)
        self._vad = VoiceActivityDetector(
            settings=cfg.vad,
            sample_rate=cfg.audio.sample_rate,
        )
        self._transcriber = RealtimeTranscriber(
            model_size=cfg.stt_model,
            language=cfg.source_language if cfg.source_language != "auto" else None,
            settings=cfg.stt,
        )
        self._diarizer = RealtimeDiarizer(settings=cfg.diarization)
        self._translator = Translator(
            api_url=cfg.translation_api_url,
            model=cfg.translation_model,
            source_lang=cfg.source_language,
            target_lang=cfg.target_language,
            provider=cfg.translation_provider,
            api_key=cfg.translation_api_key,
            settings=cfg.translation,
        )

        self._latest_speaker: DiarizationResult | None = None
        self._paused = False
        self._running = False

    # ---- wiring ----

    def _wire(self) -> None:
        self._stream.add_consumer(self._vad.process_chunk)
        self._vad.set_speech_callback(self._on_speech)
        self._transcriber.set_callback(self._on_transcription)
        # Diarizer receives audio only AFTER transcriber confirms valid speech
        # (language probability >= threshold). This prevents noise/music from
        # creating spurious speaker labels.
        self._transcriber.set_audio_validated_callback(self._diarizer.feed_audio)
        self._diarizer.set_callback(self._on_diarization)
        self._diarizer.set_new_speaker_callback(self._on_new_speaker)
        self._translator.set_callback(self._on_translation)

    def _on_speech(self, audio, sr) -> None:
        self._transcriber.feed_audio(audio, sr)

    def _on_transcription(self, segment: TranscriptionSegment) -> None:
        if self._paused:
            return
        speaker = self._latest_speaker
        speaker_label = speaker.speaker_label if speaker else "Speaker 1"
        speaker_id = speaker.speaker_id if speaker else 1

        self._translator.translate(segment.text, speaker_label, speaker_id)

    def _on_diarization(self, result: DiarizationResult) -> None:
        self._latest_speaker = result

    def _on_new_speaker(self, speaker_id: int, label: str) -> None:
        self.new_speaker_detected.emit(label)

    def _on_translation(self, result: TranslationResult) -> None:
        if self._paused:
            return

        speaker_label = result.speaker_label or "Speaker 1"
        speaker_id = result.speaker_id

        # Strip "Speaker N: " prefix from the text if present
        original_text = result.original
        parts = original_text.split(": ", 1)
        if len(parts) > 1:
            original_text = parts[1]

        translated_text = result.translated
        t_parts = translated_text.split(": ", 1)
        if len(t_parts) > 1:
            translated_text = t_parts[1]

        self.subtitle_ready.emit(translated_text, original_text, speaker_label, speaker_id)

    # ---- public controls ----

    def start(self, pid: int) -> None:
        if self._running:
            return
        self._running = True
        self._paused = False
        self._wire()

        self._capture = AudioCapture(pid, self._stream.feed)
        self.status_changed.emit("Loading models...")

        def _load_and_start() -> None:
            try:
                self._vad.load_model()
                self.status_changed.emit("Loading STT model...")
                self._transcriber.load_model()
                self.status_changed.emit("Loading diarization model...")
                self._diarizer.load_pipeline()
                self._translator.start()
                self._transcriber.start()
                self._diarizer.start()
                self._capture.start()
                if hasattr(self._capture, '_native_sr'):
                    self._stream.set_source_sample_rate(self._capture._native_sr)
                self.status_changed.emit("Translating...")
            except Exception as exc:
                logger.error("Pipeline start error: %s", exc)
                self.status_changed.emit(f"Error: {exc}")
                self._running = False

        threading.Thread(target=_load_and_start, daemon=True).start()

    def stop(self) -> None:
        self._running = False
        if self._capture:
            self._capture.stop()
        self._transcriber.stop()
        self._diarizer.stop()
        self._translator.stop()
        self._latest_speaker = None
        self.status_changed.emit("Stopped")

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def toggle_pause(self) -> None:
        if self._paused:
            self.resume()
        else:
            self.pause()

    def reset_speakers(self) -> None:
        self._diarizer.reset_speakers()
        self._latest_speaker = None

    def change_provider(self, provider: str, api_key: str, model: str) -> None:
        self._translator.set_provider(provider, api_key, model)
        self.check_lm_connection()

    def set_languages(self, source: str, target: str) -> None:
        lang = source if source != "auto" else None
        self._transcriber.set_language(lang)
        self._translator.set_languages(source, target)

    def change_model(self, model_size: str) -> None:
        self._transcriber.change_model(model_size)

    def check_lm_connection(self) -> None:
        import asyncio

        async def _check():
            connected = await self._translator.check_connection()
            model = self._config.config.translation_model
            self.lm_status_changed.emit(connected, model)

        loop = self._translator._loop
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(_check(), loop)
        else:
            # Start a temporary loop for the check
            def _sync_check():
                result = asyncio.run(self._translator.check_connection())
                model = self._config.config.translation_model
                self.lm_status_changed.emit(result, model)
            threading.Thread(target=_sync_check, daemon=True).start()


class App:
    """Top-level application object that ties the UI and pipeline together."""

    def __init__(self) -> None:
        self._qapp = QApplication(sys.argv)
        self._config = ConfigManager()
        self._hotkey = HotkeyManager()

        self._main_window = MainWindow(self._config, self._hotkey)
        self._overlay = OverlayWidget(
            max_lines=self._config.config.overlay.max_lines,
            font_size=self._config.config.overlay.font_size,
            opacity_percent=self._config.config.overlay.opacity,
        )
        self._pipeline = Pipeline(self._config)

        self._selected_pid: int = 0

        self._connect_signals()
        self._register_hotkeys()

    def _connect_signals(self) -> None:
        mw = self._main_window

        mw.translation_start_requested.connect(self._on_start)
        mw.translation_stop_requested.connect(self._on_stop)
        mw.window_selected.connect(self._on_window_selected)
        mw.language_changed.connect(self._pipeline.set_languages)
        mw.model_changed.connect(self._pipeline.change_model)
        mw.speaker_reset_requested.connect(self._pipeline.reset_speakers)
        mw.provider_changed.connect(self._pipeline.change_provider)

        pipe = self._pipeline
        pipe.subtitle_ready.connect(self._overlay.add_subtitle)
        pipe.new_speaker_detected.connect(self._overlay.show_new_speaker)
        pipe.lm_status_changed.connect(mw.set_lm_status)
        pipe.status_changed.connect(mw.set_status)

        self._config.add_listener(self._on_config_changed)

    def _register_hotkeys(self) -> None:
        cfg = self._config.config
        bindings: dict[str, callable] = {
            "toggle_translation": self._toggle_translation_hotkey,
            "pause_resume": self._pipeline.toggle_pause,
            "reset_speakers": self._pipeline.reset_speakers,
            "toggle_overlay": self._toggle_overlay,
            "increase_font": self._overlay.increase_font,
            "decrease_font": self._overlay.decrease_font,
            "clear_subtitles": self._overlay.clear_subtitles,
        }
        for action, combo in cfg.hotkeys.items():
            cb = bindings.get(action)
            if cb:
                self._hotkey.register(action, combo, cb)
        self._hotkey.start()

    def _toggle_translation_hotkey(self) -> None:
        if self._pipeline._running:
            self._on_stop()
        else:
            self._on_start()

    def _toggle_overlay(self) -> None:
        if self._overlay.isVisible():
            self._overlay.hide()
        else:
            self._overlay.show()

    @Slot(int, int)
    def _on_window_selected(self, hwnd: int, pid: int) -> None:
        self._selected_pid = pid

    @Slot()
    def _on_start(self) -> None:
        if self._selected_pid == 0:
            self._main_window.set_status("No window selected")
            return
        self._overlay.show()
        self._pipeline.start(self._selected_pid)

    @Slot()
    def _on_stop(self) -> None:
        self._pipeline.stop()

    def _on_config_changed(self, cfg: object) -> None:
        self._overlay.set_font_size(cfg.overlay.font_size)
        self._overlay.set_opacity(cfg.overlay.opacity)
        self._overlay.set_max_lines(cfg.overlay.max_lines)
        self._overlay.set_speaker_colors(cfg.speaker_colors)

        self._hotkey.unregister_all()
        self._register_hotkeys()

    def run(self) -> int:
        self._main_window.show()
        self._overlay.show()
        self._main_window._refresh_windows()

        QTimer.singleShot(1000, self._pipeline.check_lm_connection)

        return self._qapp.exec()


def main() -> None:
    app = App()
    sys.exit(app.run())


if __name__ == "__main__":
    main()
