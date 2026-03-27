"""User configuration management with JSON persistence."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".bavel"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_HOTKEYS: dict[str, str] = {
    "toggle_translation": "ctrl+shift+t",
    "pause_resume": "ctrl+shift+p",
    "reset_speakers": "ctrl+shift+r",
    "toggle_overlay": "ctrl+shift+o",
    "increase_font": "ctrl+shift+=",
    "decrease_font": "ctrl+shift+-",
    "clear_subtitles": "ctrl+shift+l",
}

SPEAKER_COLORS: list[str] = [
    "#4FC3F7",  # sky blue
    "#81C784",  # green
    "#FFB74D",  # orange
    "#CE93D8",  # purple
    "#F06292",  # pink
    "#4DB6AC",  # teal
    "#FFD54F",  # amber
    "#90A4AE",  # blue grey
]


@dataclass
class OverlaySettings:
    font_size: int = 18
    opacity: int = 80
    max_lines: int = 5
    position: str = "bottom"


@dataclass
class AppConfig:
    source_language: str = "auto"
    target_language: str = "ko"
    stt_model: str = "large-v3-turbo"
    lm_studio_url: str = "http://localhost:1234/v1/chat/completions"
    lm_studio_model: str = "gemma-3-4b"
    hotkeys: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_HOTKEYS))
    overlay: OverlaySettings = field(default_factory=OverlaySettings)
    speaker_colors: list[str] = field(default_factory=lambda: list(SPEAKER_COLORS))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppConfig:
        overlay_data = data.pop("overlay", {})
        overlay = OverlaySettings(**overlay_data) if overlay_data else OverlaySettings()

        hotkeys = data.pop("hotkeys", None)
        if hotkeys is None:
            hotkeys = dict(DEFAULT_HOTKEYS)
        else:
            merged = dict(DEFAULT_HOTKEYS)
            merged.update(hotkeys)
            hotkeys = merged

        speaker_colors = data.pop("speaker_colors", None)
        if speaker_colors is None:
            speaker_colors = list(SPEAKER_COLORS)

        return cls(overlay=overlay, hotkeys=hotkeys, speaker_colors=speaker_colors, **data)


class ConfigManager:
    """Loads, saves, and hot-reloads application configuration."""

    def __init__(self) -> None:
        self._config = AppConfig()
        self._listeners: list[Callable[[AppConfig], None]] = []
        self.load()

    @property
    def config(self) -> AppConfig:
        return self._config

    def add_listener(self, callback: Callable[[AppConfig], None]) -> None:
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[AppConfig], None]) -> None:
        self._listeners.discard(callback) if hasattr(self._listeners, "discard") else None
        if callback in self._listeners:
            self._listeners.remove(callback)

    def load(self) -> None:
        if CONFIG_FILE.exists():
            try:
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                self._config = AppConfig.from_dict(data)
                logger.info("Configuration loaded from %s", CONFIG_FILE)
            except (json.JSONDecodeError, TypeError, KeyError) as exc:
                logger.warning("Failed to load config, using defaults: %s", exc)
                self._config = AppConfig()
        else:
            logger.info("No config file found, using defaults")
            self._config = AppConfig()

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(
            json.dumps(self._config.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Configuration saved to %s", CONFIG_FILE)

    def update(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            if hasattr(self._config, key):
                setattr(self._config, key, value)
        self.save()
        self._notify()

    def update_overlay(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            if hasattr(self._config.overlay, key):
                setattr(self._config.overlay, key, value)
        self.save()
        self._notify()

    def update_hotkey(self, action: str, key_combo: str) -> None:
        self._config.hotkeys[action] = key_combo
        self.save()
        self._notify()

    def reset_hotkeys(self) -> None:
        self._config.hotkeys = dict(DEFAULT_HOTKEYS)
        self.save()
        self._notify()

    def _notify(self) -> None:
        for listener in self._listeners:
            try:
                listener(self._config)
            except Exception as exc:
                logger.error("Config listener error: %s", exc)
