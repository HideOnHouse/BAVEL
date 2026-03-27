"""Global hotkey manager using pynput for system-wide keyboard shortcuts."""

from __future__ import annotations

import logging
import threading
from typing import Callable

from pynput import keyboard

logger = logging.getLogger(__name__)

MODIFIER_KEYS = {
    "ctrl": {keyboard.Key.ctrl_l, keyboard.Key.ctrl_r},
    "shift": {keyboard.Key.shift_l, keyboard.Key.shift_r},
    "alt": {keyboard.Key.alt_l, keyboard.Key.alt_r, keyboard.Key.alt_gr},
}

KEY_ALIASES: dict[str, str] = {
    "=": "equal",
    "-": "minus",
    "+": "plus",
}


def _parse_combo(combo_str: str) -> tuple[frozenset[str], str]:
    """Parse 'ctrl+shift+t' into (frozenset({'ctrl','shift'}), 't')."""
    parts = [p.strip().lower() for p in combo_str.split("+")]
    modifiers: set[str] = set()
    key_part = ""
    for part in parts:
        if part in MODIFIER_KEYS:
            modifiers.add(part)
        else:
            key_part = KEY_ALIASES.get(part, part)
    return frozenset(modifiers), key_part


def _key_to_str(key: keyboard.Key | keyboard.KeyCode) -> str | None:
    """Convert a pynput key to a comparable string."""
    if isinstance(key, keyboard.KeyCode):
        return key.char.lower() if key.char else None
    name = key.name if hasattr(key, "name") else str(key)
    return name.lower()


class HotkeyManager:
    """Registers global hotkeys that work even when the app is not focused."""

    def __init__(self) -> None:
        self._bindings: dict[str, tuple[frozenset[str], str, Callable[[], None]]] = {}
        self._pressed_modifiers: set[str] = set()
        self._listener: keyboard.Listener | None = None
        self._lock = threading.Lock()
        self._capture_callback: Callable[[str], None] | None = None
        self._capturing = False

    def register(self, action: str, combo_str: str, callback: Callable[[], None]) -> None:
        modifiers, key = _parse_combo(combo_str)
        with self._lock:
            self._bindings[action] = (modifiers, key, callback)
        logger.info("Registered hotkey: %s -> %s", action, combo_str)

    def unregister(self, action: str) -> None:
        with self._lock:
            self._bindings.pop(action, None)
        logger.info("Unregistered hotkey: %s", action)

    def unregister_all(self) -> None:
        with self._lock:
            self._bindings.clear()

    def start_capture(self, callback: Callable[[str], None]) -> None:
        """Enter key-capture mode: the next key combo pressed will be
        reported via *callback* instead of triggering an action."""
        self._capture_callback = callback
        self._capturing = True

    def stop_capture(self) -> None:
        self._capturing = False
        self._capture_callback = None

    def start(self) -> None:
        if self._listener is not None:
            return
        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.daemon = True
        self._listener.start()
        logger.info("Hotkey listener started")

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
            logger.info("Hotkey listener stopped")

    def _modifier_for_key(self, key: keyboard.Key | keyboard.KeyCode) -> str | None:
        for mod_name, key_set in MODIFIER_KEYS.items():
            if key in key_set:
                return mod_name
        return None

    def _on_press(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        mod = self._modifier_for_key(key)
        if mod:
            self._pressed_modifiers.add(mod)
            return

        key_str = _key_to_str(key)
        if key_str is None:
            return

        if self._capturing and self._capture_callback:
            parts = sorted(self._pressed_modifiers) + [key_str]
            combo = "+".join(parts)
            self._capture_callback(combo)
            self._capturing = False
            self._capture_callback = None
            return

        current_mods = frozenset(self._pressed_modifiers)
        with self._lock:
            for _action, (req_mods, req_key, callback) in self._bindings.items():
                if req_mods == current_mods and req_key == key_str:
                    try:
                        callback()
                    except Exception as exc:
                        logger.error("Hotkey callback error (%s): %s", _action, exc)
                    break

    def _on_release(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        mod = self._modifier_for_key(key)
        if mod:
            self._pressed_modifiers.discard(mod)

    def check_conflict(self, combo_str: str, exclude_action: str = "") -> str | None:
        """Return the action name that already uses *combo_str*, or None."""
        mods, key = _parse_combo(combo_str)
        with self._lock:
            for action, (req_mods, req_key, _cb) in self._bindings.items():
                if action == exclude_action:
                    continue
                if req_mods == mods and req_key == key:
                    return action
        return None
