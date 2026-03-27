"""Audio stream management: ring buffer, resampling, and chunk dispatch."""

from __future__ import annotations

import logging
import threading
from collections import deque
from typing import Callable

import numpy as np
from scipy import signal as scipy_signal

logger = logging.getLogger(__name__)

TARGET_SAMPLE_RATE = 16_000
CHUNK_DURATION_SEC = 3.0
HOP_DURATION_SEC = 1.5


class AudioStream:
    """Ring-buffer backed audio stream that resamples to 16 kHz mono
    and dispatches fixed-duration chunks for downstream consumers."""

    def __init__(
        self,
        source_sample_rate: int = 48_000,
        chunk_duration: float = CHUNK_DURATION_SEC,
        hop_duration: float = HOP_DURATION_SEC,
    ) -> None:
        self._source_sr = source_sample_rate
        self._target_sr = TARGET_SAMPLE_RATE
        self._chunk_samples = int(self._target_sr * chunk_duration)
        self._hop_samples = int(self._target_sr * hop_duration)

        self._buffer: deque[np.ndarray] = deque()
        self._buffer_samples = 0
        self._lock = threading.Lock()

        self._consumers: list[Callable[[np.ndarray, int], None]] = []

    @property
    def sample_rate(self) -> int:
        return self._target_sr

    def set_source_sample_rate(self, sr: int) -> None:
        self._source_sr = sr

    def add_consumer(self, callback: Callable[[np.ndarray, int], None]) -> None:
        self._consumers.append(callback)

    def remove_consumer(self, callback: Callable[[np.ndarray, int], None]) -> None:
        if callback in self._consumers:
            self._consumers.remove(callback)

    def feed(self, audio: np.ndarray) -> None:
        """Accept raw audio, resample, buffer, and dispatch chunks."""
        audio = audio.astype(np.float32)
        if self._source_sr != self._target_sr:
            num_samples = int(len(audio) * self._target_sr / self._source_sr)
            audio = scipy_signal.resample(audio, num_samples).astype(np.float32)

        with self._lock:
            self._buffer.append(audio)
            self._buffer_samples += len(audio)

        self._try_dispatch()

    def _try_dispatch(self) -> None:
        while self._buffer_samples >= self._chunk_samples:
            chunk = self._collect_chunk()
            if chunk is not None:
                for consumer in self._consumers:
                    try:
                        consumer(chunk, self._target_sr)
                    except Exception as exc:
                        logger.error("Stream consumer error: %s", exc)

    def _collect_chunk(self) -> np.ndarray | None:
        with self._lock:
            if self._buffer_samples < self._chunk_samples:
                return None

            parts: list[np.ndarray] = []
            collected = 0
            while collected < self._chunk_samples and self._buffer:
                segment = self._buffer[0]
                needed = self._chunk_samples - collected
                if len(segment) <= needed:
                    parts.append(self._buffer.popleft())
                    collected += len(segment)
                    self._buffer_samples -= len(segment)
                else:
                    parts.append(segment[:needed])
                    self._buffer[0] = segment[needed:]
                    self._buffer_samples -= needed
                    collected += needed

            # Advance by hop, not full chunk (sliding window)
            discard = self._hop_samples
            remaining = self._chunk_samples - self._hop_samples
            if remaining > 0:
                chunk_data = np.concatenate(parts)
                overlap = chunk_data[discard:]
                self._buffer.appendleft(overlap)
                self._buffer_samples += len(overlap)

            return np.concatenate(parts) if parts else None

    def clear(self) -> None:
        with self._lock:
            self._buffer.clear()
            self._buffer_samples = 0
