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
source_language = "auto"

# 번역 목표 언어.
target_language = "ko"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  STT 모델
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Faster Whisper 모델 크기.
# 큰 모델일수록 정확하지만 느리고 VRAM을 많이 사용.
#   "large-v3-turbo" — 속도/정확도 균형 (권장)
#   "large-v3"       — 최고 정확도, 느림
#   "medium"         — 중간
#   "small" / "base" / "tiny" — 가볍지만 정확도↓
stt_model = "large-v3-turbo"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  번역 API 설정
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 번역 프로바이더. 모두 OpenAI 호환 API 사용.
#   "local"      — LM Studio 등 로컬 서버 (API 키 불필요)
#   "groq"       — Groq Cloud. 무료 30 RPM, 매우 빠름 (LPU)
#   "gemini"     — Google Gemini. 무료 15 RPM, 번역에 최적화
#   "openrouter" — OpenRouter. 27+ 무료 모델
translation_provider = "local"

# 번역 API 엔드포인트 URL.
translation_api_url = "http://localhost:1234/v1/chat/completions"

# 사용할 LLM 모델 이름.
# 프로바이더별 권장 모델:
#   local:      "gemma-3-4b" 또는 LM Studio에 로드된 모델명
#   groq:       "meta-llama/llama-4-scout-17b-16e-instruct"
#   gemini:     "gemini-2.5-flash-lite-preview-06-17"
#   openrouter: "deepseek/deepseek-chat-v3-0324:free"
translation_model = "openai/gpt-oss-20b"

# 번역 API 키. local 프로바이더는 비워두면 됨.
translation_api_key = ""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  오디오 파이프라인
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 오디오 스트림이 VAD에 전달하는 chunk 크기 (초).
# 이 값이 곧 "최소 반응 시간"을 결정함.
#   작을수록 → 실시간 반응이 빠름, 문장이 바로바로 처리됨
#   클수록   → 문장이 모여서 한꺼번에 처리되는 느낌
# 권장: 0.3 ~ 1.0
audio_chunk_duration = 0.7999999999999999

# 내부 처리 샘플레이트 (Hz). 변경 비권장.
audio_sample_rate = 16000

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  VAD (Voice Activity Detection) — 음성 구간 감지
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Silero VAD 음성 판별 임계치 (0.0 ~ 1.0).
#   낮으면 (0.3) → 작은 소리, 먼 목소리도 음성으로 인식. 잡음에 민감.
#   높으면 (0.7) → 확실한 목소리만 인식. 작은 소리를 놓칠 수 있음.
# 권장: 0.4 ~ 0.6
vad_speech_threshold = 0.5

# 음성 시작(onset) 확인에 필요한 연속 speech frame 수.  (1 frame ≈ 32ms)
# 권장: 1 ~ 3
vad_onset_frames = 1

# 발화 종료(offset) 확인에 필요한 연속 silence frame 수.  (1 frame ≈ 32ms)
# ★ "문장이 빨리 나오는가, 모여서 나오는가"에 큰 영향.
#   8  → 256ms 무음이면 끊김 (빠른 반응)
#   10 → 320ms (기본값)
#   15 → 480ms (천천히 말하는 화자에 적합)
# 권장: 8 ~ 15
vad_offset_frames = 4

# 발화 시작 전 포함할 pre-roll frame 수. 첫 음절 잘림 방지.
# 권장: 2 ~ 5
vad_pre_roll_frames = 3

# 무시할 최소 발화 길이 (초). 기침·클릭·한숨 제거.
# 권장: 0.2 ~ 0.5
vad_min_utterance_sec = 0.3

# 강제 분할할 최대 발화 길이 (초). 연속 발화 시 지연 상한선.
# 권장: 8 ~ 15
vad_max_utterance_sec = 10.0

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  STT 하이퍼파라미터
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 언어 감지 최소 신뢰도 (0.0 ~ 1.0). 이 미만이면 발화 무시.
# ★ 이 필터를 통과한 오디오만 화자 분류(diarizer)에도 전달됨.
# 권장: 0.6 ~ 0.8
stt_min_language_probability = 0.7

# Whisper beam search 너비. 클수록 정확하지만 느림.
# 권장: 3 ~ 5
stt_beam_size = 1

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Diarization — 화자 분류
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 최대 동시 인식 화자 수.
diarization_max_speakers = 8

# 화자 활성도 임계치 (tau_active). 높으면 확실한 발화만 인식.
# 권장: 0.45 ~ 0.65
diarization_tau_active = 0.8000000000000003

# 화자 임베딩 업데이트 강도 (rho_update). 낮으면 보수적 유지.
# ★ 같은 사람이 다른 언어로 말할 때 과잉 분류되면 이 값을 낮추세요.
# 권장: 0.2 ~ 0.4
diarization_rho_update = 0.3

# 새 화자 생성 임계치 (delta_new).
# ★ "화자가 너무 많이 생긴다" → 올리세요.  "다른 사람인데 같은 화자" → 내리세요.
# 권장: 1.5 ~ 2.8
diarization_delta_new = 2.2

# diarizer가 무시할 최소 세그먼트 길이 (초).
# 권장: 0.2 ~ 0.5
diarization_min_segment_duration = 0.3

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Translation — 번역 엔진
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# LLM 생성 온도 (0.0 ~ 1.0). 낮을수록 결정적 (번역에 적합).
# 권장: 0.1 ~ 0.4
translation_temperature = 0.09999999999999998

# 번역 결과 최대 토큰 수. 권장: 256 ~ 1024
translation_max_tokens = 512

# 번역 캐시 최대 항목 수. 0이면 비활성화. 권장: 100 ~ 500
translation_max_cache_size = 256

# API 요청 타임아웃 (초). 권장: 10 ~ 30
translation_request_timeout = 15.0

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  오버레이 UI
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

overlay_font_size = 18       # 자막 글꼴 크기 (pt)
overlay_opacity = 80         # 배경 불투명도 (10~100%)
overlay_max_lines = 5        # 동시 표시할 최대 자막 줄 수
overlay_position = "bottom"  # 기본 위치

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  단축키
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

hotkeys = {
    "toggle_translation": "ctrl+shift+t",
    "pause_resume": "ctrl+shift+p",
    "reset_speakers": "ctrl+shift+r",
    "toggle_overlay": "ctrl+shift+o",
    "increase_font": "ctrl+shift+=",
    "decrease_font": "ctrl+shift+-",
    "clear_subtitles": "ctrl+shift+l",
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  화자 색상 팔레트  (Speaker 1부터 순서대로)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

speaker_colors = [
    "#4FC3F7",
    "#81C784",
    "#FFB74D",
    "#CE93D8",
    "#F06292",
    "#4DB6AC",
    "#FFD54F",
    "#90A4AE",
]
