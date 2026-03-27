"""Audio capture via WASAPI loopback using PyAudioWPatch.

Captures all audio from the default output device in real-time and
streams PCM float32 chunks to a callback for downstream processing.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

import numpy as np

logger = logging.getLogger(__name__)

AudioCallback = Callable[[np.ndarray], None]

CHUNK_FRAMES = 4096


class AudioCapture:
    """Captures system audio via WASAPI loopback and streams PCM to a callback."""

    def __init__(self, pid: int, callback: AudioCallback) -> None:
        self._pid = pid
        self._callback = callback
        self._pa = None
        self._stream = None
        self._running = False
        self._paused = False
        self._native_sr: int = 48_000
        self._channels: int = 2
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_paused(self) -> bool:
        return self._paused

    def start(self) -> None:
        if self._running:
            return

        import pyaudiowpatch as pyaudio

        self._pa = pyaudio.PyAudio()

        loopback_device = self._find_loopback_device()
        if loopback_device is None:
            self._pa.terminate()
            raise RuntimeError("No WASAPI loopback device found")

        self._native_sr = int(loopback_device["defaultSampleRate"])
        channels = loopback_device["maxInputChannels"]
        self._channels = channels

        self._running = True
        self._paused = False

        self._stream = self._pa.open(
            format=pyaudio.paFloat32,
            channels=channels,
            rate=self._native_sr,
            input=True,
            input_device_index=loopback_device["index"],
            frames_per_buffer=CHUNK_FRAMES,
            stream_callback=self._stream_callback,
        )
        self._stream.start_stream()
        logger.info(
            "Audio capture started (WASAPI loopback, sr=%d, ch=%d, device='%s')",
            self._native_sr, channels, loopback_device["name"],
        )

    def _find_loopback_device(self):
        """Find the WASAPI loopback device for the default output."""
        import pyaudiowpatch as pyaudio

        try:
            wasapi_info = self._pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        except OSError:
            logger.error("WASAPI host API not available")
            return None

        default_output_idx = wasapi_info["defaultOutputDevice"]
        default_output = self._pa.get_device_info_by_index(default_output_idx)

        for i in range(self._pa.get_device_count()):
            dev = self._pa.get_device_info_by_index(i)
            if dev.get("isLoopbackDevice") and dev["name"].startswith(
                default_output["name"].split(" (")[0]
            ):
                return dev

        for i in range(self._pa.get_device_count()):
            dev = self._pa.get_device_info_by_index(i)
            if dev.get("isLoopbackDevice"):
                return dev

        return None

    def _stream_callback(self, in_data, frame_count, time_info, status):
        import pyaudiowpatch as pyaudio

        if not self._running:
            return (None, pyaudio.paComplete)
        if self._paused:
            return (None, pyaudio.paContinue)

        audio = np.frombuffer(in_data, dtype=np.float32)
        if self._channels > 1:
            audio = audio.reshape(-1, self._channels).mean(axis=1)

        try:
            self._callback(audio)
        except Exception as exc:
            logger.error("Audio callback error: %s", exc)

        return (None, pyaudio.paContinue)

    def pause(self) -> None:
        self._paused = True
        logger.info("Audio capture paused")

    def resume(self) -> None:
        self._paused = False
        logger.info("Audio capture resumed")

    def stop(self) -> None:
        self._running = False
        self._paused = False
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception as exc:
                logger.warning("Error stopping audio stream: %s", exc)
            self._stream = None
        if self._pa is not None:
            self._pa.terminate()
            self._pa = None
        logger.info("Audio capture stopped")

    def change_target(self, pid: int) -> None:
        was_running = self._running
        if was_running:
            self.stop()
        self._pid = pid
        if was_running:
            self.start()
