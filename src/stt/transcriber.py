"""Real-time speech-to-text using Faster Whisper."""

from __future__ import annotations

import logging
import threading
import queue
from dataclasses import dataclass
from typing import Callable

import numpy as np

from src.core.config import STTSettings

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16_000


@dataclass
class TranscriptionSegment:
    text: str
    start: float
    end: float
    language: str
    language_probability: float = 1.0
    is_partial: bool = False


TranscriptionCallback = Callable[[TranscriptionSegment], None]


class RealtimeTranscriber:
    """Streaming STT engine backed by Faster Whisper.

    Receives complete utterances from the VAD and transcribes them
    immediately — no internal accumulation needed.
    """

    def __init__(
        self,
        model_size: str = "large-v3-turbo",
        language: str | None = None,
        device: str = "auto",
        compute_type: str = "auto",
        settings: STTSettings | None = None,
    ) -> None:
        s = settings or STTSettings()
        self._model_size = model_size
        self._language = language
        self._device = device
        self._compute_type = compute_type
        self._min_lang_prob = s.min_language_probability
        self._beam_size = s.beam_size
        self._model = None
        self._callback: TranscriptionCallback | None = None
        self._audio_validated_callback: Callable[[np.ndarray, int], None] | None = None
        self._audio_queue: queue.Queue[np.ndarray | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._running = False
        self._time_offset: float = 0.0

    def load_model(self) -> None:
        self._add_cuda_dll_paths()
        from faster_whisper import WhisperModel

        device = self._device
        if device == "auto":
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"

        compute = self._compute_type
        if compute == "auto":
            compute = "float16" if device == "cuda" else "int8"

        try:
            self._model = WhisperModel(
                self._model_size,
                device=device,
                compute_type=compute,
            )
            # Dry-run to catch missing DLL errors early
            _test = np.zeros(16000, dtype=np.float32)
            list(self._model.transcribe(_test, language="en")[0])
        except Exception as exc:
            if device == "cuda":
                logger.warning("CUDA failed (%s), falling back to CPU", exc)
                device = "cpu"
                compute = "int8"
                self._model = WhisperModel(
                    self._model_size,
                    device=device,
                    compute_type=compute,
                )
            else:
                raise

        logger.info(
            "Faster Whisper model loaded: %s (device=%s, compute=%s)",
            self._model_size, device, compute,
        )

    @staticmethod
    def _add_cuda_dll_paths() -> None:
        """Add nvidia pip package DLL dirs to the DLL search path."""
        import os, site
        for sp in site.getsitepackages():
            nvidia_dir = os.path.join(sp, "nvidia")
            if not os.path.isdir(nvidia_dir):
                continue
            for sub in os.listdir(nvidia_dir):
                bin_dir = os.path.join(nvidia_dir, sub, "bin")
                lib_dir = os.path.join(nvidia_dir, sub, "lib")
                for d in (bin_dir, lib_dir):
                    if os.path.isdir(d) and d not in os.environ.get("PATH", ""):
                        os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
                        try:
                            os.add_dll_directory(d)
                        except (OSError, AttributeError):
                            pass

    def set_callback(self, callback: TranscriptionCallback) -> None:
        self._callback = callback

    def set_audio_validated_callback(
        self, callback: Callable[[np.ndarray, int], None],
    ) -> None:
        """Register a callback that fires once per audio chunk that passes
        the language-probability gate.  Used to feed only validated speech
        to the diarizer (instead of raw VAD output that may contain noise)."""
        self._audio_validated_callback = callback

    def start(self) -> None:
        if self._running:
            return
        if self._model is None:
            self.load_model()
        self._running = True
        self._time_offset = 0.0
        self._thread = threading.Thread(target=self._process_loop, daemon=True)
        self._thread.start()
        logger.info("Transcriber started")

    def stop(self) -> None:
        self._running = False
        self._audio_queue.put(None)
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        logger.info("Transcriber stopped")

    def feed_audio(self, audio: np.ndarray, sample_rate: int) -> None:
        if self._running:
            self._audio_queue.put(audio.astype(np.float32))

    def _process_loop(self) -> None:
        while self._running:
            try:
                audio = self._audio_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if audio is None:
                break
            self._transcribe(audio)

    def _transcribe(self, audio: np.ndarray) -> None:
        if self._model is None:
            return
        try:
            segments, info = self._model.transcribe(
                audio,
                language=self._language,
                beam_size=self._beam_size,
                vad_filter=False,
            )

            lang_prob = info.language_probability
            if lang_prob < self._min_lang_prob:
                logger.info(
                    "STT: language '%s' prob %.2f < %.2f, skipping",
                    info.language, lang_prob, self._min_lang_prob,
                )
                self._time_offset += len(audio) / SAMPLE_RATE
                return

            # Audio confirmed as valid speech → forward to diarizer
            if self._audio_validated_callback:
                try:
                    self._audio_validated_callback(audio, SAMPLE_RATE)
                except Exception as exc:
                    logger.error("Audio validated callback error: %s", exc)

            for seg in segments:
                text = seg.text.strip()
                if not text:
                    continue
                result = TranscriptionSegment(
                    text=text,
                    start=seg.start + self._time_offset,
                    end=seg.end + self._time_offset,
                    language=info.language,
                    language_probability=lang_prob,
                )
                logger.info("STT: [%s %.0f%%] %s", info.language, lang_prob * 100, text)
                if self._callback:
                    self._callback(result)

            self._time_offset += len(audio) / SAMPLE_RATE
        except Exception as exc:
            logger.error("Transcription error: %s", exc)

    def change_model(self, model_size: str) -> None:
        was_running = self._running
        if was_running:
            self.stop()
        self._model_size = model_size
        self._model = None
        if was_running:
            self.start()

    def set_language(self, language: str | None) -> None:
        self._language = language if language != "auto" else None
