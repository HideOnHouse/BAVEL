"""User configuration management with JSON persistence.

All pipeline hyperparameters are centralised here so they can be tuned from
one place and persisted to ``~/.bavel/config.json``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_FILE = PROJECT_ROOT / "config.py"

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


# ---------------------------------------------------------------------------
# Pipeline hyperparameter groups
# ---------------------------------------------------------------------------

@dataclass
class AudioSettings:
    # 오디오 스트림이 VAD에 전달하는 chunk 크기 (초).
    # 작을수록 실시간 반응이 빠름. 너무 작으면(<0.1) 리샘플링 오버헤드 증가.
    # 권장: 0.3~1.0
    chunk_duration: float = 0.5

    # 모든 처리 모듈의 공통 샘플레이트 (Hz).
    # Silero VAD · Faster Whisper · diart 모두 16 kHz 기준.
    sample_rate: int = 16_000


@dataclass
class VADSettings:
    # Silero VAD 음성 판별 임계치 (0.0 ~ 1.0).
    # 낮으면 민감 (잡음도 음성으로 인식), 높으면 보수적.
    speech_threshold: float = 0.5

    # 음성 시작(onset) 확인에 필요한 연속 speech frame 수.
    # 1 frame = 512 samples = 32 ms @ 16 kHz.
    onset_frames: int = 2  # ≈ 64 ms

    # 발화 종료(offset) 확인에 필요한 연속 silence frame 수.
    # 클수록 문장 사이 짧은 쉼을 허용해 문장을 하나로 합침.
    # 작을수록 발화 종료를 빨리 감지 → 실시간성 향상.
    offset_frames: int = 10  # ≈ 320 ms  (기존 15 ≈ 480 ms)

    # 발화 시작 전 포함할 pre-roll frame 수.
    # Whisper에 전달할 때 발화 첫 음절이 잘리지 않도록 여유분 확보.
    pre_roll_frames: int = 3  # ≈ 96 ms

    # 무시할 최소 발화 길이 (초). 짧은 잡음·클릭·한숨 제거.
    min_utterance_sec: float = 0.3

    # 강제 분할할 최대 발화 길이 (초). 지연 시간 상한선.
    # 연속 발화가 이 길이를 넘으면 강제로 끊어서 STT에 전달.
    max_utterance_sec: float = 10.0


@dataclass
class STTSettings:
    # 언어 감지 신뢰도 임계치 (0.0 ~ 1.0).
    # 이 값 미만이면 해당 발화를 무시 (음악·효과음·잡음 필터링).
    min_language_probability: float = 0.7

    # Whisper beam search 너비. 클수록 정확하지만 느림.
    # 실시간용으로는 3~5 권장.
    beam_size: int = 5


@dataclass
class DiarizationSettings:
    # 최대 동시 인식 화자 수.
    max_speakers: int = 8

    # 화자 활성도 임계치 (tau_active).
    # 이 값 이상이어야 "말하고 있다"로 판정.
    # 높으면 확실한 발화만 인식, 낮으면 작은 소리도 포함.
    tau_active: float = 0.55

    # 화자 임베딩 업데이트 강도 (rho_update, 0.0 ~ 1.0).
    # 낮으면 기존 화자 모델을 보수적으로 유지 → 과잉 분류 방지.
    # 높으면 새 발화마다 임베딩을 크게 갱신 → 화자 모델이 빨리 변함.
    rho_update: float = 0.3

    # 새 화자 생성 임계치 (delta_new).
    # 기존 화자 임베딩과의 거리가 이 값 이상이면 새 화자로 등록.
    # 높을수록 새 화자 생성이 어려움 → 같은 사람이 언어를 바꿔도 동일 화자 유지.
    # 낮으면 사소한 음색 변화에도 새 화자를 만듦.
    delta_new: float = 2.2

    # diarizer가 무시할 최소 세그먼트 길이 (초).
    # 짧은 노이즈성 세그먼트를 걸러냄.
    min_segment_duration: float = 0.3


@dataclass
class TranslationSettings:
    # 번역 캐시 최대 항목 수. 동일 문장 반복 시 API 호출 절약.
    max_cache_size: int = 256

    # LLM 생성 온도 (0.0 ~ 1.0).
    # 낮을수록 결정적 (번역에 적합), 높을수록 창의적.
    temperature: float = 0.3

    # 번역 결과 최대 토큰 수.
    max_tokens: int = 512

    # API 요청 타임아웃 (초). 로컬 LM Studio는 15초면 충분,
    # 클라우드 API는 네트워크 상태에 따라 늘릴 수 있음.
    request_timeout: float = 15.0


# ---------------------------------------------------------------------------
# UI / overlay settings
# ---------------------------------------------------------------------------

@dataclass
class OverlaySettings:
    font_size: int = 18
    opacity: int = 80
    max_lines: int = 5
    position: str = "bottom"


# ---------------------------------------------------------------------------
# Top-level config
# ---------------------------------------------------------------------------

@dataclass
class AppConfig:
    source_language: str = "auto"
    target_language: str = "ko"
    stt_model: str = "large-v3-turbo"

    # Translation provider: local | groq | gemini | openrouter
    translation_provider: str = "local"
    translation_api_url: str = "http://localhost:1234/v1/chat/completions"
    translation_model: str = "gemma-3-4b"
    translation_api_key: str = ""

    # Legacy fields for backward compat
    lm_studio_url: str = "http://localhost:1234/v1/chat/completions"
    lm_studio_model: str = "gemma-3-4b"

    hotkeys: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_HOTKEYS))
    overlay: OverlaySettings = field(default_factory=OverlaySettings)
    speaker_colors: list[str] = field(default_factory=lambda: list(SPEAKER_COLORS))

    # Pipeline hyperparameters
    audio: AudioSettings = field(default_factory=AudioSettings)
    vad: VADSettings = field(default_factory=VADSettings)
    stt: STTSettings = field(default_factory=STTSettings)
    diarization: DiarizationSettings = field(default_factory=DiarizationSettings)
    translation: TranslationSettings = field(default_factory=TranslationSettings)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppConfig:
        # Pop nested dataclass dicts so they don't clash with **data
        overlay_data = data.pop("overlay", {})
        overlay = OverlaySettings(**overlay_data) if overlay_data else OverlaySettings()

        audio_data = data.pop("audio", {})
        audio = AudioSettings(**audio_data) if audio_data else AudioSettings()

        vad_data = data.pop("vad", {})
        vad = VADSettings(**vad_data) if vad_data else VADSettings()

        stt_data = data.pop("stt", {})
        stt = STTSettings(**stt_data) if stt_data else STTSettings()

        diarization_data = data.pop("diarization", {})
        diarization = (
            DiarizationSettings(**diarization_data)
            if diarization_data
            else DiarizationSettings()
        )

        translation_data = data.pop("translation", {})
        translation_settings = (
            TranslationSettings(**translation_data)
            if translation_data
            else TranslationSettings()
        )

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

        return cls(
            overlay=overlay,
            hotkeys=hotkeys,
            speaker_colors=speaker_colors,
            audio=audio,
            vad=vad,
            stt=stt,
            diarization=diarization,
            translation=translation_settings,
            **data,
        )


# ---------------------------------------------------------------------------
# Config manager
# ---------------------------------------------------------------------------

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
        if callback in self._listeners:
            self._listeners.remove(callback)

    def load(self) -> None:
        if CONFIG_FILE.exists():
            try:
                self._config = self._load_from_py(CONFIG_FILE)
                logger.info("Configuration loaded from %s", CONFIG_FILE)
            except Exception as exc:
                logger.warning("Failed to load config, using defaults: %s", exc)
                self._config = AppConfig()
        else:
            logger.info("No config file found, using defaults")
            self._config = AppConfig()
            self.save()

    @staticmethod
    def _load_from_py(path: Path) -> AppConfig:
        """Execute config.py and extract variables into AppConfig."""
        ns: dict[str, Any] = {}
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), ns)

        def _get(key: str, default: Any = None) -> Any:
            return ns.get(key, default)

        return AppConfig(
            source_language=_get("source_language", "auto"),
            target_language=_get("target_language", "ko"),
            stt_model=_get("stt_model", "large-v3-turbo"),
            translation_provider=_get("translation_provider", "local"),
            translation_api_url=_get("translation_api_url", "http://localhost:1234/v1/chat/completions"),
            translation_model=_get("translation_model", "gemma-3-4b"),
            translation_api_key=_get("translation_api_key", ""),
            hotkeys=_get("hotkeys", dict(DEFAULT_HOTKEYS)),
            overlay=OverlaySettings(
                font_size=_get("overlay_font_size", 18),
                opacity=_get("overlay_opacity", 80),
                max_lines=_get("overlay_max_lines", 5),
                position=_get("overlay_position", "bottom"),
            ),
            speaker_colors=_get("speaker_colors", list(SPEAKER_COLORS)),
            audio=AudioSettings(
                chunk_duration=_get("audio_chunk_duration", 0.5),
                sample_rate=_get("audio_sample_rate", 16_000),
            ),
            vad=VADSettings(
                speech_threshold=_get("vad_speech_threshold", 0.5),
                onset_frames=_get("vad_onset_frames", 2),
                offset_frames=_get("vad_offset_frames", 10),
                pre_roll_frames=_get("vad_pre_roll_frames", 3),
                min_utterance_sec=_get("vad_min_utterance_sec", 0.3),
                max_utterance_sec=_get("vad_max_utterance_sec", 10.0),
            ),
            stt=STTSettings(
                min_language_probability=_get("stt_min_language_probability", 0.7),
                beam_size=_get("stt_beam_size", 5),
            ),
            diarization=DiarizationSettings(
                max_speakers=_get("diarization_max_speakers", 8),
                tau_active=_get("diarization_tau_active", 0.55),
                rho_update=_get("diarization_rho_update", 0.3),
                delta_new=_get("diarization_delta_new", 2.2),
                min_segment_duration=_get("diarization_min_segment_duration", 0.3),
            ),
            translation=TranslationSettings(
                max_cache_size=_get("translation_max_cache_size", 256),
                temperature=_get("translation_temperature", 0.3),
                max_tokens=_get("translation_max_tokens", 512),
                request_timeout=_get("translation_request_timeout", 15.0),
            ),
        )

    def save(self) -> None:
        self._save_to_py(CONFIG_FILE, self._config)
        logger.info("Configuration saved to %s", CONFIG_FILE)

    @staticmethod
    def _save_to_py(path: Path, cfg: AppConfig) -> None:
        """Regenerate config.py with current values, preserving comments."""
        c = cfg
        hotkeys_str = "\n".join(
            f'    "{k}": {json.dumps(v, ensure_ascii=False)},'
            for k, v in c.hotkeys.items()
        )
        colors_str = "\n".join(f'    "{col}",' for col in c.speaker_colors)

        content = f'''\
"""
BAVEL 설정 파일
==============
이 파일을 직접 수정하여 파이프라인 동작을 조정할 수 있습니다.
앱 UI의 Pipeline 탭에서도 같은 설정을 변경할 수 있으며, 변경 시 이 파일이 자동 갱신됩니다.
"""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  언어 설정
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 소스 언어. "auto"면 Whisper가 자동 감지.
# 특정 언어로 고정하면 인식 정확도가 올라갈 수 있음.
# 지원: "auto", "en", "ko", "ja", "zh", "es", "fr", "de", "pt", "ru", "ar", "hi", "vi", "th", "id"
source_language = {json.dumps(c.source_language)}

# 번역 목표 언어.
target_language = {json.dumps(c.target_language)}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  STT 모델
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Faster Whisper 모델 크기.
# 큰 모델일수록 정확하지만 느리고 VRAM을 많이 사용.
#   "large-v3-turbo" — 속도/정확도 균형 (권장)
#   "large-v3"       — 최고 정확도, 느림
#   "medium"         — 중간
#   "small" / "base" / "tiny" — 가볍지만 정확도↓
stt_model = {json.dumps(c.stt_model)}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  번역 API 설정
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 번역 프로바이더. 모두 OpenAI 호환 API 사용.
#   "local"      — LM Studio 등 로컬 서버 (API 키 불필요)
#   "groq"       — Groq Cloud. 무료 30 RPM, 매우 빠름 (LPU)
#   "gemini"     — Google Gemini. 무료 15 RPM, 번역에 최적화
#   "openrouter" — OpenRouter. 27+ 무료 모델
translation_provider = {json.dumps(c.translation_provider)}

# 번역 API 엔드포인트 URL.
translation_api_url = {json.dumps(c.translation_api_url)}

# 사용할 LLM 모델 이름.
# 프로바이더별 권장 모델:
#   local:      "gemma-3-4b" 또는 LM Studio에 로드된 모델명
#   groq:       "meta-llama/llama-4-scout-17b-16e-instruct"
#   gemini:     "gemini-2.5-flash-lite-preview-06-17"
#   openrouter: "deepseek/deepseek-chat-v3-0324:free"
translation_model = {json.dumps(c.translation_model)}

# 번역 API 키. local 프로바이더는 비워두면 됨.
translation_api_key = {json.dumps(c.translation_api_key)}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  오디오 파이프라인
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 오디오 스트림이 VAD에 전달하는 chunk 크기 (초).
# 이 값이 곧 "최소 반응 시간"을 결정함.
#   작을수록 → 실시간 반응이 빠름, 문장이 바로바로 처리됨
#   클수록   → 문장이 모여서 한꺼번에 처리되는 느낌
# 권장: 0.3 ~ 1.0
audio_chunk_duration = {c.audio.chunk_duration}

# 내부 처리 샘플레이트 (Hz). 변경 비권장.
audio_sample_rate = {c.audio.sample_rate}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  VAD (Voice Activity Detection) — 음성 구간 감지
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Silero VAD 음성 판별 임계치 (0.0 ~ 1.0).
#   낮으면 (0.3) → 작은 소리, 먼 목소리도 음성으로 인식. 잡음에 민감.
#   높으면 (0.7) → 확실한 목소리만 인식. 작은 소리를 놓칠 수 있음.
# 권장: 0.4 ~ 0.6
vad_speech_threshold = {c.vad.speech_threshold}

# 음성 시작(onset) 확인에 필요한 연속 speech frame 수.  (1 frame ≈ 32ms)
# 권장: 1 ~ 3
vad_onset_frames = {c.vad.onset_frames}

# 발화 종료(offset) 확인에 필요한 연속 silence frame 수.  (1 frame ≈ 32ms)
# ★ "문장이 빨리 나오는가, 모여서 나오는가"에 큰 영향.
#   8  → 256ms 무음이면 끊김 (빠른 반응)
#   10 → 320ms (기본값)
#   15 → 480ms (천천히 말하는 화자에 적합)
# 권장: 8 ~ 15
vad_offset_frames = {c.vad.offset_frames}

# 발화 시작 전 포함할 pre-roll frame 수. 첫 음절 잘림 방지.
# 권장: 2 ~ 5
vad_pre_roll_frames = {c.vad.pre_roll_frames}

# 무시할 최소 발화 길이 (초). 기침·클릭·한숨 제거.
# 권장: 0.2 ~ 0.5
vad_min_utterance_sec = {c.vad.min_utterance_sec}

# 강제 분할할 최대 발화 길이 (초). 연속 발화 시 지연 상한선.
# 권장: 8 ~ 15
vad_max_utterance_sec = {c.vad.max_utterance_sec}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  STT 하이퍼파라미터
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 언어 감지 최소 신뢰도 (0.0 ~ 1.0). 이 미만이면 발화 무시.
# ★ 이 필터를 통과한 오디오만 화자 분류(diarizer)에도 전달됨.
# 권장: 0.6 ~ 0.8
stt_min_language_probability = {c.stt.min_language_probability}

# Whisper beam search 너비. 클수록 정확하지만 느림.
# 권장: 3 ~ 5
stt_beam_size = {c.stt.beam_size}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Diarization — 화자 분류
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 최대 동시 인식 화자 수.
diarization_max_speakers = {c.diarization.max_speakers}

# 화자 활성도 임계치 (tau_active). 높으면 확실한 발화만 인식.
# 권장: 0.45 ~ 0.65
diarization_tau_active = {c.diarization.tau_active}

# 화자 임베딩 업데이트 강도 (rho_update). 낮으면 보수적 유지.
# ★ 같은 사람이 다른 언어로 말할 때 과잉 분류되면 이 값을 낮추세요.
# 권장: 0.2 ~ 0.4
diarization_rho_update = {c.diarization.rho_update}

# 새 화자 생성 임계치 (delta_new).
# ★ "화자가 너무 많이 생긴다" → 올리세요.  "다른 사람인데 같은 화자" → 내리세요.
# 권장: 1.5 ~ 2.8
diarization_delta_new = {c.diarization.delta_new}

# diarizer가 무시할 최소 세그먼트 길이 (초).
# 권장: 0.2 ~ 0.5
diarization_min_segment_duration = {c.diarization.min_segment_duration}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Translation — 번역 엔진
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# LLM 생성 온도 (0.0 ~ 1.0). 낮을수록 결정적 (번역에 적합).
# 권장: 0.1 ~ 0.4
translation_temperature = {c.translation.temperature}

# 번역 결과 최대 토큰 수. 권장: 256 ~ 1024
translation_max_tokens = {c.translation.max_tokens}

# 번역 캐시 최대 항목 수. 0이면 비활성화. 권장: 100 ~ 500
translation_max_cache_size = {c.translation.max_cache_size}

# API 요청 타임아웃 (초). 권장: 10 ~ 30
translation_request_timeout = {c.translation.request_timeout}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  오버레이 UI
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

overlay_font_size = {c.overlay.font_size}       # 자막 글꼴 크기 (pt)
overlay_opacity = {c.overlay.opacity}         # 배경 불투명도 (10~100%)
overlay_max_lines = {c.overlay.max_lines}        # 동시 표시할 최대 자막 줄 수
overlay_position = {json.dumps(c.overlay.position)}  # 기본 위치

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  단축키
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

hotkeys = {{
{hotkeys_str}
}}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  화자 색상 팔레트  (Speaker 1부터 순서대로)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

speaker_colors = [
{colors_str}
]
'''
        path.write_text(content, encoding="utf-8")

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
