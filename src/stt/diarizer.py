"""Real-time speaker diarization using diart (pyannote-based)."""

from __future__ import annotations

import logging
import threading
import queue
from dataclasses import dataclass
from typing import Callable

import numpy as np

from src.core.config import DiarizationSettings

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16_000


@dataclass
class DiarizationResult:
    speaker_id: int
    speaker_label: str
    start: float
    end: float
    is_new_speaker: bool = False


DiarizationCallback = Callable[[DiarizationResult], None]
NewSpeakerCallback = Callable[[int, str], None]


class RealtimeDiarizer:
    """Streaming speaker diarization backed by diart + pyannote.

    Accepts fixed-duration audio chunks (matching ``config.duration`` seconds),
    wraps them as ``SlidingWindowFeature`` objects, and feeds them through
    the diart ``SpeakerDiarization`` pipeline one at a time.
    """

    def __init__(self, settings: DiarizationSettings | None = None) -> None:
        self._settings = settings or DiarizationSettings()
        self._max_speakers = self._settings.max_speakers
        self._min_seg_dur = self._settings.min_segment_duration
        self._pipeline = None
        self._config = None
        self._callback: DiarizationCallback | None = None
        self._new_speaker_callback: NewSpeakerCallback | None = None
        self._audio_queue: queue.Queue[np.ndarray | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._running = False

        self._known_speakers: set[int] = set()
        self._speaker_labels: dict[int, str] = {}
        self._speaker_counter = 0
        self._lock = threading.Lock()

        self._time_offset = 0.0
        self._chunk_duration: float = 5.0
        self._chunk_samples: int = int(SAMPLE_RATE * self._chunk_duration)
        self._accumulator: np.ndarray = np.array([], dtype=np.float32)

    def load_pipeline(self) -> None:
        from diart.blocks.diarization import SpeakerDiarization, SpeakerDiarizationConfig

        s = self._settings
        self._config = SpeakerDiarizationConfig(
            max_speakers=s.max_speakers,
            tau_active=s.tau_active,
            rho_update=s.rho_update,
            delta_new=s.delta_new,
        )
        self._pipeline = SpeakerDiarization(self._config)
        self._chunk_duration = self._config.duration
        self._chunk_samples = int(np.rint(self._chunk_duration * SAMPLE_RATE))
        logger.info(
            "diart pipeline loaded (duration=%.1fs, step=%.1fs, chunk=%d samples)",
            self._chunk_duration, self._config.step, self._chunk_samples,
        )

    def set_callback(self, callback: DiarizationCallback) -> None:
        self._callback = callback

    def set_new_speaker_callback(self, callback: NewSpeakerCallback) -> None:
        self._new_speaker_callback = callback

    def start(self) -> None:
        if self._running:
            return
        if self._pipeline is None:
            self.load_pipeline()
        self._running = True
        self._thread = threading.Thread(target=self._process_loop, daemon=True)
        self._thread.start()
        logger.info("Diarizer started")

    def stop(self) -> None:
        self._running = False
        self._audio_queue.put(None)
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        self._accumulator = np.array([], dtype=np.float32)
        logger.info("Diarizer stopped")

    def feed_audio(self, audio: np.ndarray, sample_rate: int) -> None:
        if self._running:
            self._audio_queue.put(audio)

    def _process_loop(self) -> None:
        while self._running:
            try:
                audio = self._audio_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if audio is None:
                break

            self._accumulator = np.concatenate([self._accumulator, audio.astype(np.float32)])

            while len(self._accumulator) >= self._chunk_samples:
                chunk = self._accumulator[:self._chunk_samples]
                self._accumulator = self._accumulator[self._chunk_samples:]
                self._diarize_chunk(chunk)

    def _diarize_chunk(self, audio: np.ndarray) -> None:
        if self._pipeline is None:
            return
        try:
            from pyannote.core import SlidingWindowFeature, SlidingWindow

            # diart expects (samples, channels) shaped numpy inside SlidingWindowFeature
            waveform_data = audio.reshape(-1, 1)
            sw = SlidingWindow(
                start=self._time_offset,
                duration=1.0 / SAMPLE_RATE,
                step=1.0 / SAMPLE_RATE,
            )
            swf = SlidingWindowFeature(waveform_data, sw)

            outputs = self._pipeline([swf])

            best_segment = None
            best_duration = 0.0

            for annotation, _agg_waveform in outputs:
                for segment, _track, label in annotation.itertracks(yield_label=True):
                    duration = segment.end - segment.start
                    if duration < self._min_seg_dur:
                        continue
                    speaker_num = self._resolve_speaker(label)
                    is_new = speaker_num not in self._known_speakers
                    if is_new:
                        self._register_new_speaker(speaker_num)

                    if duration > best_duration:
                        best_duration = duration
                        best_segment = DiarizationResult(
                            speaker_id=speaker_num,
                            speaker_label=self._speaker_labels.get(
                                speaker_num, f"Speaker {speaker_num}"
                            ),
                            start=segment.start,
                            end=segment.end,
                            is_new_speaker=is_new,
                        )

            if best_segment and self._callback:
                self._callback(best_segment)

            self._time_offset += self._chunk_duration
        except Exception as exc:
            logger.error("Diarization error: %s", exc)

    def _resolve_speaker(self, label: str) -> int:
        try:
            return int(label.split("_")[-1]) + 1
        except (ValueError, IndexError):
            with self._lock:
                self._speaker_counter += 1
                return self._speaker_counter

    def _register_new_speaker(self, speaker_id: int) -> None:
        with self._lock:
            self._known_speakers.add(speaker_id)
            if speaker_id not in self._speaker_labels:
                self._speaker_labels[speaker_id] = f"Speaker {speaker_id}"
        logger.info("New speaker detected: Speaker %d", speaker_id)
        if self._new_speaker_callback:
            try:
                self._new_speaker_callback(speaker_id, self._speaker_labels[speaker_id])
            except Exception as exc:
                logger.error("New speaker callback error: %s", exc)

    def reset_speakers(self) -> None:
        with self._lock:
            self._known_speakers.clear()
            self._speaker_labels.clear()
            self._speaker_counter = 0
        if self._pipeline is not None:
            self._pipeline.reset()
        self._time_offset = 0.0
        self._accumulator = np.array([], dtype=np.float32)
        logger.info("Speaker diarization reset")

    def set_speaker_label(self, speaker_id: int, label: str) -> None:
        with self._lock:
            self._speaker_labels[speaker_id] = label

    def get_speaker_count(self) -> int:
        return len(self._known_speakers)

    def get_speaker_labels(self) -> dict[int, str]:
        with self._lock:
            return dict(self._speaker_labels)
