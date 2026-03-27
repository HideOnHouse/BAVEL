# BAVEL 개발 기록

## 세션 1 — 2026-03-27: 초기 구현

### 목표
`plan.md`에 정의된 실시간 화자 인식 오버레이 번역 시스템 전체 빌드.

---

### 구현된 모듈

| 모듈 | 파일 | 설명 |
|---|---|---|
| **Core** | `src/core/config.py` | JSON 기반 설정 관리 (`~/.bavel/config.json`), 핫 리로드, 기본값 폴백 |
| | `src/core/hotkey_manager.py` | `pynput` 기반 글로벌 단축키, 키 캡처 모드, 충돌 감지 |
| **Audio** | `src/audio/capture.py` | PyAudioWPatch WASAPI 루프백으로 시스템 오디오 실시간 캡처 |
| | `src/audio/stream.py` | 링 버퍼, 16kHz 리샘플링, 슬라이딩 윈도우 청크 디스패치 |
| | `src/audio/vad.py` | Silero VAD 상태 머신 기반 발화 경계 감지 (onset/offset) |
| **STT** | `src/stt/transcriber.py` | Faster Whisper 실시간 STT, CUDA/CPU 자동 폴백 |
| | `src/stt/diarizer.py` | diart + pyannote 실시간 화자 분류 |
| **Translation** | `src/translation/translator.py` | LM Studio OpenAI 호환 API, 비동기 번역, 캐싱, 패스스루 폴백 |
| **UI** | `src/ui/main_window.py` | 메인 컨트롤 패널 (창 선택, 언어, 모델, 설정, 단축키 탭) |
| | `src/ui/overlay.py` | 드래그 가능 플로팅 자막 바, always-on-top, 화자별 색상 |
| | `src/ui/window_selector.py` | Win32 API 윈도우 열거, DWM 기반 정확한 창 영역 감지 |
| | `src/ui/styles.py` | 다크 테마 QSS (Catppuccin Mocha 계열) |
| **Entry** | `main.py` | 전체 파이프라인 오케스트레이션, DPI awareness, torchaudio 호환 패치 |

---

### 해결한 문제들

#### 1. torchaudio 호환성 (pyannote/diart/speechbrain)
- **문제**: `torchaudio >= 2.1`에서 `set_audio_backend`, `list_audio_backends`, `get_audio_backend` 제거됨. pyannote/diart가 import 시점에 호출.
- **해결**: `main.py` 최상단에서 monkey-patch로 no-op 스텁 주입.

#### 2. diart `torchaudio.io` import 오류
- **문제**: `diart/sources.py`가 `from torchaudio.io import StreamReader` 사용. torchaudio 2.11에서 제거됨.
- **해결**: `diarizer.py`에서 `diart.sources` / `diart.inference` import 제거. `diart.blocks.diarization`에서 직접 import.

#### 3. pyannote gated model 인증
- **문제**: `pyannote/segmentation`, `pyannote/embedding` 모델이 HuggingFace gated repo.
- **해결**: `huggingface_hub.login()` 토큰 저장 + 웹에서 모델 약관 동의.

#### 4. process-audio-capture API 불일치
- **문제**: 라이브러리가 파일 출력 전용 (실시간 스트리밍 콜백 미제공).
- **해결**: `PyAudioWPatch` WASAPI 루프백으로 전환. 시스템 전체 오디오 실시간 캡처.

#### 5. Silero VAD 프레임 크기 오류
- **문제**: VAD가 512ms(8192 샘플)를 보냈으나, Silero는 정확히 512 샘플(32ms) 필요.
- **해결**: `VAD_WINDOW_SAMPLES_16K = 512`로 수정.

#### 6. VAD → Transcriber 오디오 분절 문제
- **문제**: VAD가 짧은 음성 조각을 개별 전달. Whisper가 짧은 오디오에서 텍스트 생성 실패.
- **해결**: VAD를 상태 머신으로 재설계. 발화 시작(onset) → 끝(offset) 감지하여 완성된 발화 단위로 디스패치.

#### 7. cuBLAS DLL 누락
- **문제**: Faster Whisper CUDA 모드에서 `cublas64_12.dll` 미발견.
- **해결**: `nvidia-cublas-cu12` 설치 + 런타임 DLL 경로 자동 추가 + CUDA 실패 시 CPU 자동 폴백.

#### 8. 화자 과다 감지
- **문제**: diart 기본 `delta_new=1.0`이 너무 낮아 5초마다 새 화자 생성.
- **해결**: `delta_new=1.9`, `rho_update=0.4`, `tau_active=0.55`로 임계값 조정.

#### 9. 오버레이 위치 문제 (DPI/윈도우 동기화)
- **문제**: 투명 오버레이가 대상 창 위에 정확히 겹치지 않음. DPI 스케일링 + DWM 그림자 테두리.
- **해결**: 윈도우 동기화 방식 폐기. 드래그 가능 플로팅 자막 바로 전환. 사용자가 직접 위치 조절.

#### 10. 언어 감지 신뢰도 필터
- **문제**: 음악/잡음이 낮은 확률로 언어 감지되어 의미 없는 자막 생성.
- **해결**: `language_probability < 0.8`이면 해당 발화 무시.

---

### 자막 표시 형식
```
Speaker 1: 번역된 텍스트
(Original English text)
```
- 번역 있을 때: 번역문 + 작은 회색 원문
- 번역 없을 때 (LM Studio 미연결): 원문만 표시

---

### 설치된 추가 패키지 (plan.md 외)
- `PyAudioWPatch` — WASAPI 루프백 오디오 캡처
- `nvidia-cublas-cu12` — Faster Whisper CUDA cuBLAS
- `torchcodec` → 설치 후 DLL 로드 실패로 제거
- pyannote 의존성 업그레이드 (core 6.0.1, database 6.1.1, metrics 4.0.0, pipeline 4.0.0)
- opentelemetry, pyannoteai-sdk, safetensors 등 pyannote-audio 4.0.4 요구사항

---

### 현재 상태
- **동작**: 앱 실행, 오디오 캡처, VAD, 화자 분류, 오버레이 표시 모두 정상
- **STT**: CUDA 사용 시 cuBLAS 필요 (없으면 CPU 자동 폴백)
- **번역**: LM Studio 선택적 (없으면 원문 패스스루)
- **알려진 제한**: 독점 전체화면(DirectX Exclusive) 앱에서는 오버레이 가려짐

---

## 세션 2 — 2026-03-27: 버그 수정 + 클라우드 API 지원

### 수정된 문제들

#### 1. 같은 발화가 2번 표시되는 문제
- **원인**: `AudioStream`의 슬라이딩 윈도우가 3초 chunk에 1.5초 hop(50% 오버랩)을 사용. 같은 오디오 샘플이 VAD 상태 머신에 2번 입력되어, 동일 발화가 중복 감지됨.
- **해결**: `HOP_DURATION_SEC`을 `CHUNK_DURATION_SEC`과 동일하게 3.0초로 변경. VAD가 각 오디오 샘플을 정확히 1번만 처리하도록 수정.

#### 2. 원문 표기 안 되는 문제
- **원인**: `_translate_async`에서 번역 API 오류 발생 시 callback이 호출되지 않아 원문이 완전히 소실됨.
- **해결**: 모든 예외 경로에서 passthrough(`original == translated`) 결과를 emit하도록 수정. 번역 실패 시 원문이 그대로 오버레이에 표시됨.

#### 3. LM Studio 의존성 제거 — 클라우드 API 지원
- **원인**: 번역이 localhost:1234 LM Studio에만 의존.
- **해결**: OpenAI 호환 API를 사용하는 4개 프로바이더 지원:

| Provider | URL | 무료 티어 | 특징 |
|---|---|---|---|
| **Local** | localhost:1234 | 무제한 | LM Studio, Ollama 등 |
| **Groq** | api.groq.com | 30 RPM | 매우 빠름 (LPU), Llama 4 Scout 등 |
| **Gemini** | generativelanguage.googleapis.com | 15 RPM | Flash-Lite, 번역 최적화 |
| **OpenRouter** | openrouter.ai | 20 RPM | 27+ 무료 모델, DeepSeek V3 등 |

- UI에 프로바이더 선택 드롭다운, API 키 입력, 모델 설정 추가.
- 런타임 프로바이더 전환 가능 (Apply 버튼).

#### 4. Speaker 과다 인식
- **원인**: `delta_new=1.9`이 여전히 낮아 새 화자를 과도하게 생성. 짧은 세그먼트도 화자로 인식.
- **해결**:
  - `delta_new` 1.9 → 2.2로 상향 (새 화자 생성 임계치 강화)
  - `rho_update` 0.4 → 0.3으로 하향 (화자 임베딩 업데이트 보수적)
  - 0.3초 미만 세그먼트 무시 필터 추가
  - chunk당 가장 긴 dominant speaker만 emit (모든 세그먼트 대신)

#### 5. 새 화자 발언 무시 문제
- **원인**: speaker 정보가 파이프라인에서 일관되게 전달되지 않음. `_on_transcription`에서 `_latest_speaker`를 사용하고, `_on_translation`에서 다시 텍스트 파싱으로 speaker를 유추하는 이중 구조. 비동기 타이밍에 의해 `_latest_speaker`가 중간에 변경되면 잘못된 화자가 표시됨.
- **해결**: `TranslationResult`에 `speaker_label`, `speaker_id` 필드 추가. 번역 요청 시점의 speaker 정보가 번역 결과까지 일관되게 전달되도록 파이프라인 전체 수정.

### 변경된 파일
| 파일 | 변경 내용 |
|---|---|
| `src/audio/stream.py` | hop=chunk (오버랩 제거) |
| `src/translation/translator.py` | 멀티 프로바이더, API 키, 에러 시 패스스루, speaker 정보 전달 |
| `src/core/config.py` | `translation_provider`, `translation_api_key`, `translation_model` 필드 추가 |
| `src/ui/main_window.py` | 프로바이더 선택 UI, API 키 입력, 모델 설정 |
| `src/stt/diarizer.py` | delta_new/rho_update 조정, 세그먼트 필터, dominant speaker 선택 |
| `main.py` | provider 변경 시그널 연결, speaker 정보 일관 전달, 연결 체크 개선 |
