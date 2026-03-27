"""Voice Activity Detection using Silero VAD.

Tracks speech onset/offset across audio chunks and dispatches complete
utterances (from speech start to speech end) to downstream consumers.
"""

from __future__ import annotations

import logging
from typing import Callable

import numpy as np
import torch

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
VAD_FRAME_SAMPLES = 512  # Silero requires exactly 512 samples at 16 kHz

SPEECH_THRESHOLD = 0.5
ONSET_FRAMES = 2         # consecutive speech frames to confirm onset
OFFSET_FRAMES = 15       # consecutive silence frames to confirm offset (~480 ms)
PRE_ROLL_FRAMES = 3      # include N frames before onset for context
MIN_UTTERANCE_SEC = 0.5
MAX_UTTERANCE_SEC = 15.0


class VoiceActivityDetector:
    """Detects utterance boundaries in a continuous audio stream.

    Accumulates audio while speech is active and dispatches complete
    utterances (speech-start → speech-end) via the speech callback.
    """

    def __init__(
        self,
        threshold: float = SPEECH_THRESHOLD,
        sample_rate: int = SAMPLE_RATE,
    ) -> None:
        self._threshold = threshold
        self._sample_rate = sample_rate
        self._model = None
        self._speech_callback: Callable[[np.ndarray, int], None] | None = None

        # State machine
        self._is_speaking = False
        self._speech_count = 0      # consecutive speech frames
        self._silence_count = 0     # consecutive silence frames

        # Buffers
        self._utterance_buf: list[np.ndarray] = []
        self._pre_roll: list[np.ndarray] = []
        self._utterance_samples = 0

    def load_model(self) -> None:
        self._model, _utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            force_reload=False,
            trust_repo=True,
        )
        self._model.eval()
        logger.info("Silero VAD model loaded")

    def set_speech_callback(self, callback: Callable[[np.ndarray, int], None]) -> None:
        self._speech_callback = callback

    def process_chunk(self, audio: np.ndarray, sample_rate: int) -> None:
        """Process a chunk of 16 kHz audio through the VAD state machine."""
        if self._model is None:
            self.load_model()

        for start in range(0, len(audio), VAD_FRAME_SAMPLES):
            end = start + VAD_FRAME_SAMPLES
            frame = audio[start:end]
            if len(frame) < VAD_FRAME_SAMPLES:
                frame = np.pad(frame, (0, VAD_FRAME_SAMPLES - len(frame)))

            tensor = torch.from_numpy(frame).float()
            confidence = self._model(tensor, self._sample_rate).item()
            is_speech = confidence >= self._threshold

            raw_frame = audio[start:min(end, len(audio))]
            self._update_state(is_speech, raw_frame)

    def _update_state(self, is_speech: bool, frame: np.ndarray) -> None:
        if not self._is_speaking:
            # --- waiting for speech onset ---
            self._pre_roll.append(frame)
            if len(self._pre_roll) > PRE_ROLL_FRAMES:
                self._pre_roll.pop(0)

            if is_speech:
                self._speech_count += 1
                if self._speech_count >= ONSET_FRAMES:
                    self._begin_utterance()
            else:
                self._speech_count = 0
        else:
            # --- inside an utterance ---
            self._utterance_buf.append(frame)
            self._utterance_samples += len(frame)

            if is_speech:
                self._silence_count = 0
            else:
                self._silence_count += 1
                if self._silence_count >= OFFSET_FRAMES:
                    self._end_utterance()
                    return

            # Force-flush very long utterances to keep latency bounded
            if self._utterance_samples / self._sample_rate >= MAX_UTTERANCE_SEC:
                self._end_utterance()

    def _begin_utterance(self) -> None:
        self._is_speaking = True
        self._silence_count = 0
        # Prepend the pre-roll for context
        self._utterance_buf = list(self._pre_roll)
        self._utterance_samples = sum(len(f) for f in self._utterance_buf)
        self._pre_roll.clear()
        logger.debug("Speech onset detected")

    def _end_utterance(self) -> None:
        self._is_speaking = False
        self._speech_count = 0
        self._silence_count = 0

        if self._utterance_samples / self._sample_rate < MIN_UTTERANCE_SEC:
            self._utterance_buf.clear()
            self._utterance_samples = 0
            return

        utterance = np.concatenate(self._utterance_buf)
        self._utterance_buf.clear()
        self._utterance_samples = 0

        dur = len(utterance) / self._sample_rate
        logger.debug("Utterance dispatched: %.1f s", dur)

        if self._speech_callback is not None:
            try:
                self._speech_callback(utterance, self._sample_rate)
            except Exception as exc:
                logger.error("VAD speech callback error: %s", exc)

    def reset(self) -> None:
        if self._model is not None:
            self._model.reset_states()
        self._is_speaking = False
        self._speech_count = 0
        self._silence_count = 0
        self._utterance_buf.clear()
        self._pre_roll.clear()
        self._utterance_samples = 0
