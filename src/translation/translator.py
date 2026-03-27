"""Translation engine supporting multiple OpenAI-compatible API providers.

Supported providers:
  - local:     LM Studio or any local OpenAI-compatible server
  - groq:      Groq Cloud (free tier: 30 RPM, very fast LPU inference)
  - gemini:    Google Gemini API (free tier: 15 RPM for Flash-Lite)
  - openrouter: OpenRouter (27+ free models, 20 RPM)
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable

import httpx

from src.core.config import TranslationSettings

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

PROVIDER_PRESETS: dict[str, dict] = {
    "local": {
        "url": "http://localhost:1234/v1/chat/completions",
        "default_model": "gemma-3-4b",
        "needs_key": False,
    },
    "groq": {
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "default_model": "meta-llama/llama-4-scout-17b-16e-instruct",
        "needs_key": True,
    },
    "gemini": {
        "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "default_model": "gemini-2.5-flash-lite-preview-06-17",
        "needs_key": True,
    },
    "openrouter": {
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "default_model": "deepseek/deepseek-chat-v3-0324:free",
        "needs_key": True,
    },
}


@dataclass
class TranslationResult:
    original: str
    translated: str
    source_lang: str
    target_lang: str
    speaker_label: str = ""
    speaker_id: int = 1


TranslationCallback = Callable[[TranslationResult], None]


class Translator:
    """Async translation client for OpenAI-compatible APIs.

    Works with LM Studio (local), Groq, Google Gemini, and OpenRouter.
    """

    def __init__(
        self,
        api_url: str = "http://localhost:1234/v1/chat/completions",
        model: str = "gemma-3-4b",
        source_lang: str = "auto",
        target_lang: str = "ko",
        provider: str = "local",
        api_key: str = "",
        settings: TranslationSettings | None = None,
    ) -> None:
        s = settings or TranslationSettings()
        self._provider = provider
        self._api_key = api_key
        self._api_url = api_url
        self._model = model
        self._source_lang = source_lang
        self._target_lang = target_lang
        self._max_cache_size = s.max_cache_size
        self._temperature = s.temperature
        self._max_tokens = s.max_tokens
        self._request_timeout = s.request_timeout
        self._callback: TranslationCallback | None = None
        self._cache: OrderedDict[str, str] = OrderedDict()
        self._connected = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._running = False

        if provider in PROVIDER_PRESETS:
            preset = PROVIDER_PRESETS[provider]
            if api_url == "http://localhost:1234/v1/chat/completions" and provider != "local":
                self._api_url = preset["url"]
            if model == "gemma-3-4b" and provider != "local":
                self._model = preset["default_model"]

    @property
    def is_connected(self) -> bool:
        return self._connected

    def set_callback(self, callback: TranslationCallback) -> None:
        self._callback = callback

    def set_languages(self, source: str, target: str) -> None:
        self._source_lang = source
        self._target_lang = target

    def set_provider(self, provider: str, api_key: str = "", model: str = "") -> None:
        """Switch to a different translation provider at runtime."""
        self._provider = provider
        self._api_key = api_key
        if provider in PROVIDER_PRESETS:
            preset = PROVIDER_PRESETS[provider]
            self._api_url = preset["url"]
            self._model = model or preset["default_model"]
        self._connected = False
        self._cache.clear()

    def _headers(self) -> dict[str, str]:
        if self._api_key:
            return {"Authorization": f"Bearer {self._api_key}"}
        return {}

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
                resp = await client.get(models_url, headers=self._headers())
                if resp.status_code == 200:
                    self._connected = True
                    data = resp.json()
                    models = [m.get("id", "unknown") for m in data.get("data", [])]
                    logger.info(
                        "Translation API connected (%s). Models: %s",
                        self._provider, models[:5],
                    )
                else:
                    self._connected = False
                    logger.warning(
                        "Translation API (%s) returned status %d",
                        self._provider, resp.status_code,
                    )
        except Exception as exc:
            self._connected = False
            logger.warning("Translation API (%s) not reachable: %s", self._provider, exc)

    def translate(
        self,
        text: str,
        speaker_label: str = "",
        speaker_id: int = 1,
    ) -> None:
        """Submit text for async translation.  Falls back to passthrough
        when the translation API is not connected."""
        full_text = f"{speaker_label}: {text}" if speaker_label else text

        if not self._running or self._loop is None or not self._connected:
            self._emit_result(full_text, full_text, speaker_label, speaker_id)
            return

        cache_key = self._cache_key(full_text)
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            self._cache.move_to_end(cache_key)
            self._emit_result(full_text, cached, speaker_label, speaker_id)
            return

        asyncio.run_coroutine_threadsafe(
            self._translate_async(full_text, cache_key, speaker_label, speaker_id),
            self._loop,
        )

    async def _translate_async(
        self, text: str, cache_key: str,
        speaker_label: str = "", speaker_id: int = 1,
    ) -> None:
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
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
            "stream": False,
        }

        try:
            async with httpx.AsyncClient(timeout=self._request_timeout) as client:
                resp = await client.post(self._api_url, json=payload, headers=self._headers())
                resp.raise_for_status()
                data = resp.json()
                translated = data["choices"][0]["message"]["content"].strip()

                self._cache[cache_key] = translated
                if len(self._cache) > self._max_cache_size:
                    self._cache.popitem(last=False)

                self._emit_result(text, translated, speaker_label, speaker_id)
                self._connected = True
        except httpx.ConnectError:
            self._connected = False
            logger.error("Translation API connection lost — showing original text")
            self._emit_result(text, text, speaker_label, speaker_id)
        except Exception as exc:
            logger.error("Translation error: %s — showing original text", exc)
            self._emit_result(text, text, speaker_label, speaker_id)

    def _emit_result(
        self, original: str, translated: str,
        speaker_label: str = "", speaker_id: int = 1,
    ) -> None:
        if self._callback:
            result = TranslationResult(
                original=original,
                translated=translated,
                source_lang=self._source_lang,
                target_lang=self._target_lang,
                speaker_label=speaker_label,
                speaker_id=speaker_id,
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
