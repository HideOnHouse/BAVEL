"""Translation engine using LM Studio's OpenAI-compatible API."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable

import httpx

logger = logging.getLogger(__name__)

TRANSLATION_PROMPT_TEMPLATE = (
    "You are a professional real-time translator. "
    "Translate the following text from {source_lang} to {target_lang}. "
    "Keep the speaker labels (e.g., 'Speaker 1:') intact. "
    "Output ONLY the translation, no explanations or extra text.\n\n"
    "{text}"
)

LANGUAGE_NAMES: dict[str, str] = {
    "auto": "the detected language",
    "en": "English",
    "ko": "Korean",
    "ja": "Japanese",
    "zh": "Chinese",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "pt": "Portuguese",
    "ru": "Russian",
    "ar": "Arabic",
    "hi": "Hindi",
    "vi": "Vietnamese",
    "th": "Thai",
    "id": "Indonesian",
}

MAX_CACHE_SIZE = 256


@dataclass
class TranslationResult:
    original: str
    translated: str
    source_lang: str
    target_lang: str


TranslationCallback = Callable[[TranslationResult], None]


class Translator:
    """Async translation client for LM Studio (OpenAI-compatible API)."""

    def __init__(
        self,
        api_url: str = "http://localhost:1234/v1/chat/completions",
        model: str = "gemma-3-4b",
        source_lang: str = "auto",
        target_lang: str = "ko",
    ) -> None:
        self._api_url = api_url
        self._model = model
        self._source_lang = source_lang
        self._target_lang = target_lang
        self._callback: TranslationCallback | None = None
        self._cache: OrderedDict[str, str] = OrderedDict()
        self._connected = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._running = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def set_callback(self, callback: TranslationCallback) -> None:
        self._callback = callback

    def set_languages(self, source: str, target: str) -> None:
        self._source_lang = source
        self._target_lang = target

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("Translator started")

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._check_connection())
        self._loop.run_forever()

    def stop(self) -> None:
        self._running = False
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        self._loop = None
        logger.info("Translator stopped")

    async def _check_connection(self) -> None:
        base_url = self._api_url.rsplit("/chat/completions", 1)[0]
        models_url = f"{base_url}/models"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(models_url)
                if resp.status_code == 200:
                    self._connected = True
                    data = resp.json()
                    models = [m.get("id", "unknown") for m in data.get("data", [])]
                    logger.info("LM Studio connected. Available models: %s", models)
                else:
                    self._connected = False
                    logger.warning("LM Studio returned status %d", resp.status_code)
        except Exception as exc:
            self._connected = False
            logger.warning("LM Studio not reachable: %s", exc)

    def translate(self, text: str, speaker_label: str = "") -> None:
        """Submit text for async translation.  Falls back to passthrough
        when LM Studio is not connected."""
        full_text = f"{speaker_label}: {text}" if speaker_label else text

        if not self._running or self._loop is None or not self._connected:
            self._emit_result(full_text, full_text)
            return

        cache_key = self._cache_key(full_text)
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            self._cache.move_to_end(cache_key)
            self._emit_result(full_text, cached)
            return

        asyncio.run_coroutine_threadsafe(
            self._translate_async(full_text, cache_key),
            self._loop,
        )

    async def _translate_async(self, text: str, cache_key: str) -> None:
        source_name = LANGUAGE_NAMES.get(self._source_lang, self._source_lang)
        target_name = LANGUAGE_NAMES.get(self._target_lang, self._target_lang)

        prompt = TRANSLATION_PROMPT_TEMPLATE.format(
            source_lang=source_name,
            target_lang=target_name,
            text=text,
        )

        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 512,
            "stream": False,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(self._api_url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                translated = data["choices"][0]["message"]["content"].strip()

                self._cache[cache_key] = translated
                if len(self._cache) > MAX_CACHE_SIZE:
                    self._cache.popitem(last=False)

                self._emit_result(text, translated)
                self._connected = True
        except httpx.ConnectError:
            self._connected = False
            logger.error("LM Studio connection lost")
        except Exception as exc:
            logger.error("Translation error: %s", exc)

    def _emit_result(self, original: str, translated: str) -> None:
        if self._callback:
            result = TranslationResult(
                original=original,
                translated=translated,
                source_lang=self._source_lang,
                target_lang=self._target_lang,
            )
            try:
                self._callback(result)
            except Exception as exc:
                logger.error("Translation callback error: %s", exc)

    def _cache_key(self, text: str) -> str:
        raw = f"{self._source_lang}:{self._target_lang}:{text}"
        return hashlib.md5(raw.encode()).hexdigest()

    async def check_connection(self) -> bool:
        await self._check_connection()
        return self._connected
