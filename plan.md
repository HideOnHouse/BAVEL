# BAVEL - 실시간 화자 인식 오버레이 번역 시스템

## 1. 프로젝트 개요

특정 윈도우의 오디오를 캡처하여 실시간으로 음성을 인식(STT)하고, 화자를 분류한 뒤,
원하는 언어로 번역하여 해당 윈도우 위에 오버레이로 자막을 표시하는 데스크톱 애플리케이션.

**타겟 OS**: Windows 10 (Build 19041+) / Windows 11
**언어**: Python 3.11+

---

## 2. 기술 스택 조사 결과

### 2.1 오디오 캡처 (프로세스 단위)

| 라이브러리 | 설명 | 비고 |
|---|---|---|
| **process-audio-capture** | Windows WASAPI 기반 프로세스별 오디오 캡처 | PyPI 패키지, Win10 2004+ 필수 |
| PyAudioWPatch | WASAPI 루프백 녹음 (시스템 전체) | 특정 프로세스 지정 불가 |
| recap-capture | 윈도우 캡처 (화면+오디오) | 오디오 분리 캡처 미지원 |

**결정: `process-audio-capture`**
- 특정 프로세스의 오디오만 격리 캡처 가능 (INCLUDE/EXCLUDE 모드)
- 실시간 오디오 레벨 콜백 지원
- 윈도우 선택 → PID 추출 → 해당 PID의 오디오만 캡처하는 흐름

### 2.2 음성 인식 (STT) + 화자 분류 (Speaker Diarization)

| 기술 | 설명 | 성능 |
|---|---|---|
| **WhisperLiveKit** | Faster Whisper 기반 실시간 STT + 화자 분류 통합 | SOTA 2025, Apache 2.0, 초저지연 |
| Faster Whisper 단독 | CTranslate2 기반 Whisper (4x 빠름) | 화자 분류 별도 구현 필요 |
| diart | 실시간 화자 분류 프레임워크 | pyannote 기반, WebSocket 지원 |
| sherpa-onnx | 오프라인 STT + 화자 분류 | ONNX 기반, 임베디드 지원 |

**결정: `Faster Whisper` + `diart` (직접 통합)**

WhisperLiveKit은 서버-클라이언트 WebSocket 아키텍처로 설계되어 있어,
단일 데스크톱 앱에 내장하기엔 오버헤드가 큼. 핵심 컴포넌트를 직접 통합하는 것이 적합.

- **Faster Whisper** (`faster-whisper`): 실시간 STT 엔진
  - large-v3-turbo 모델 사용 (속도-정확도 균형)
  - GPU 가속 (CUDA) 또는 CPU 폴백
- **diart** (`diart`): 실시간 화자 분류
  - pyannote.audio 기반 사전학습 모델
  - 스트리밍 입력에서 실시간 화자 라벨링
  - Latency: 500ms 이하

### 2.3 번역 (Translation)

| 기술 | 설명 | 장단점 |
|---|---|---|
| **LM Studio (로컬 LLM)** | OpenAI 호환 REST API로 로컬 LLM 실행 | 무료, 오프라인, ~1초 지연 |
| Soniox / Palabra.ai | 클라우드 실시간 번역 API | 유료, 고성능 |
| 무료 API (2026.03 기준) | 조사 결과 실시간 번역+화자분류를 무료로 제공하는 API **없음** | - |

**결정: `LM Studio` (OpenAI 호환 API)**

2026년 3월 기준, 실시간 번역 + 화자 분류를 **무료**로 제공하는 외부 API는 발견되지 않음.
LM Studio는 로컬에서 구동되며 비용 없이 고품질 번역이 가능하므로 최적의 선택.

- **추천 모델**: `google/gemma-3-4b` (속도-정확도 균형) 또는 `Qwen3-8B` (다국어 강점)
- **API 엔드포인트**: `http://localhost:1234/v1/chat/completions`
- **지연시간**: ~0.5-1.5초 (모델 크기/하드웨어에 따라)

### 2.4 UI / 오버레이

| 기술 | 설명 | 비고 |
|---|---|---|
| **PySide6 (Qt6)** | 크로스플랫폼 GUI + 투명 오버레이 | 라이선스 우수 (LGPL) |
| PyQt6 | Qt6 바인딩 | GPL 라이선스 |
| Tkinter | 파이썬 기본 GUI | 투명 오버레이 구현 제한적 |

**결정: `PySide6`**
- `WindowStaysOnTopHint` + `FramelessWindowHint` + `WA_TranslucentBackground`로 투명 오버레이 구현
- 대상 윈도우 위치/크기에 맞춰 오버레이 자동 배치
- 화자별 색상 구분, 자막 스타일링

---

## 3. 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────┐
│                     BAVEL Application                    │
│                                                         │
│  ┌──────────┐    ┌──────────────┐    ┌───────────────┐  │
│  │  Window   │    │   Audio      │    │    STT +      │  │
│  │  Selector │───>│   Capture    │───>│  Diarization  │  │
│  │  (UI)     │    │  (WASAPI)    │    │  (Whisper +   │  │
│  └──────────┘    └──────────────┘    │   diart)      │  │
│                                      └───────┬───────┘  │
│                                              │          │
│                                   Text + Speaker Labels │
│                                              │          │
│  ┌──────────────────┐    ┌───────────────────▼───────┐  │
│  │   Overlay UI     │<───│    Translation Engine     │  │
│  │  (Transparent    │    │    (LM Studio API)        │  │
│  │   Subtitle)      │    └───────────────────────────┘  │
│  └──────────────────┘                                   │
└─────────────────────────────────────────────────────────┘
```

### 3.1 데이터 흐름

```
Audio Stream (PCM float32, 16kHz)
    │
    ▼
┌─────────────────────────┐
│  VAD (Silero VAD)       │  ← 음성 구간만 감지하여 리소스 절약
│  음성 감지 시에만 처리   │
└──────────┬──────────────┘
           │
    ┌──────┴──────┐
    │             │
    ▼             ▼
┌────────┐  ┌──────────┐
│ Faster │  │  diart   │
│Whisper │  │ (화자    │
│ (STT)  │  │  분류)   │
└───┬────┘  └────┬─────┘
    │            │
    ▼            ▼
┌─────────────────────────┐
│  Merge: Text + Speaker  │  ← "Speaker 1: Hello, how are you?"
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│  LM Studio Translation  │  ← "화자 1: 안녕하세요, 어떻게 지내세요?"
│  (비동기 API 호출)       │
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│  Overlay Renderer       │  ← 투명 오버레이에 자막 렌더링
│  (화자별 색상 구분)      │
└─────────────────────────┘
```

---

## 4. 모듈 구조

```
BAVEL/
├── main.py                     # 앱 엔트리포인트
├── requirements.txt            # 의존성
├── plan.md                     # 이 문서
├── README.md
│
├── src/
│   ├── __init__.py
│   │
│   ├── audio/
│   │   ├── __init__.py
│   │   ├── capture.py          # 프로세스별 오디오 캡처 (process-audio-capture)
│   │   ├── stream.py           # 오디오 스트림 관리 (버퍼링, 리샘플링)
│   │   └── vad.py              # Voice Activity Detection (Silero VAD)
│   │
│   ├── stt/
│   │   ├── __init__.py
│   │   ├── transcriber.py      # Faster Whisper 기반 실시간 STT
│   │   └── diarizer.py         # diart 기반 실시간 화자 분류
│   │
│   ├── translation/
│   │   ├── __init__.py
│   │   └── translator.py       # LM Studio API 기반 번역 (OpenAI 호환)
│   │
│   ├── ui/
│   │   ├── __init__.py
│   │   ├── main_window.py      # 메인 컨트롤 윈도우 (설정, 창 선택 등)
│   │   ├── overlay.py          # 투명 오버레이 윈도우 (자막 표시)
│   │   ├── window_selector.py  # 윈도우 열거 및 선택 UI
│   │   └── styles.py           # QSS 스타일시트 및 테마
│   │
│   └── core/
│       ├── __init__.py
│       ├── hotkey_manager.py   # 글로벌 단축키 등록/해제/설정 관리
│       └── config.py           # 사용자 설정 저장/로드 (단축키 매핑 포함)
│
└── assets/
    └── icon.png                # 앱 아이콘
```

---

## 5. 상세 구현 계획

### Phase 1: 기반 구축 (오디오 캡처 + 윈도우 선택)

1. **프로젝트 세팅**
   - Python 가상환경 구성
   - `requirements.txt` 작성 및 의존성 설치
   - 기본 모듈 구조 생성

2. **윈도우 선택 UI** (`ui/window_selector.py`)
   - `win32gui`로 현재 열린 윈도우 열거
   - 윈도우 목록을 리스트/드롭다운으로 표시 (아이콘 + 타이틀)
   - 선택한 윈도우의 PID, 위치, 크기 추출
   - 윈도우 핸들 추적 (이동/리사이즈 감지)

3. **오디오 캡처** (`audio/capture.py`)
   - `process-audio-capture`를 사용하여 선택된 PID의 오디오 캡처
   - PCM float32 / 16kHz 모노로 리샘플링
   - 링 버퍼 기반 오디오 스트림 관리
   - 캡처 시작/중지/일시정지 제어

### Phase 2: STT + 화자 분류

4. **VAD 통합** (`audio/vad.py`)
   - Silero VAD 모델 로드
   - 음성 구간 감지 → STT/Diarizer에 음성 청크만 전달
   - 무음 구간 스킵으로 GPU/CPU 리소스 절약

5. **실시간 STT** (`stt/transcriber.py`)
   - Faster Whisper 모델 로드 (large-v3-turbo 또는 medium)
   - 스트리밍 방식 구현: 슬라이딩 윈도우 (3-5초) + 증분 처리
   - 부분 결과(partial) / 확정 결과(final) 구분
   - 언어 자동 감지 또는 수동 설정

6. **실시간 화자 분류** (`stt/diarizer.py`)
   - diart 파이프라인 초기화 (pyannote 사전학습 모델)
   - 오디오 청크 입력 → 화자 라벨 출력
   - STT 결과와 화자 라벨 타임스탬프 기반 병합
   - 화자 수 자동 감지 (또는 상한선 설정)
   - **동적 화자 추가 감지**: 기존 임베딩 클러스터와의 유사도가 임계값 이하인 새 음성이 감지되면 자동으로 새 화자로 등록. 오버레이에 "New Speaker detected" 알림 표시.
   - **화자 초기화 기능**: 축적된 화자 임베딩/클러스터를 전부 리셋하고 화자 번호를 1부터 재할당. 환경이 바뀌거나(회의실 이동, 참여자 교체 등) 화자 분류가 꼬였을 때 사용.

### Phase 3: 번역

7. **번역 엔진** (`translation/translator.py`)
   - LM Studio OpenAI 호환 API 클라이언트
   - 번역 프롬프트 템플릿 (소스 언어 → 타겟 언어)
   - 비동기 처리 (`aiohttp` / `httpx`)로 UI 블로킹 방지
   - 번역 결과 캐싱 (반복 문장 최적화)
   - 연결 상태 확인 및 에러 핸들링

### Phase 4: UI / 오버레이

8. **메인 컨트롤 윈도우** (`ui/main_window.py`)
   - 윈도우 선택 컨트롤 (Phase 1에서 구현한 것 통합)
   - 소스 언어 / 타겟 언어 선택
   - LM Studio 연결 상태 표시
   - 번역 시작/중지 버튼
   - STT 모델 크기 선택 (tiny/base/small/medium/large)
   - 오버레이 설정 (폰트 크기, 투명도, 위치)
   - 화자 초기화 버튼 (화자 목록 + 임베딩 전체 리셋)
   - 단축키 설정 탭/섹션

9. **투명 오버레이** (`ui/overlay.py`)
   - `FramelessWindowHint` + `WindowStaysOnTopHint` + `WA_TranslucentBackground`
   - 대상 윈도우의 위치/크기에 동기화 (타이머 기반 추적)
   - 화자별 색상 지정 (최대 8명, 자동 색상 할당)
   - 새 화자 감지 시 오버레이에 일시적 알림 배지 표시
   - 자막 표시 영역:
     - 하단 고정 (기본)
     - 드래그로 위치 조절 가능
   - 자막 페이드인/아웃 애니메이션
   - 최근 N줄 표시 (오래된 자막 자동 소멸)

### Phase 5: 단축키 시스템 + 화자 관리

10. **글로벌 단축키 매니저** (`core/hotkey_manager.py`)
    - 앱이 포커스가 아닐 때도 동작하는 시스템 전역 단축키 등록
    - `pynput` 라이브러리로 키 조합 감지 (Win32 저수준 훅)
    - 사용자 정의 키 매핑: 설정 UI에서 "키 입력 대기 → 캡처" 방식으로 설정
    - 충돌 감지: 이미 등록된 시스템/앱 단축키와 겹치는 경우 경고
    - 기본 단축키 매핑 (아래 표 참조)

11. **사용자 설정 관리** (`core/config.py`)
    - JSON 기반 설정 파일 (`~/.bavel/config.json`)
    - 단축키 매핑, 오버레이 설정, 언어 설정 등 영속 저장
    - 기본값 폴백: 설정 파일 없거나 항목 누락 시 기본값 사용
    - 설정 변경 시 즉시 반영 (핫 리로드)

12. **화자 동적 관리** (`stt/diarizer.py` 확장)
    - 새 화자 감지 이벤트 → UI 알림 시그널 발행
    - 화자 초기화: 임베딩 저장소 클리어 + 화자 ID 카운터 리셋 + 색상 재할당
    - 화자 라벨 커스터마이징 (선택적): "Speaker 1" → 사용자 지정 이름

---

## 6. UI/UX 디자인

### 6.1 메인 컨트롤 패널 (컴팩트)

```
┌──────────────────────────────────────────────┐
│  🎙 BAVEL                           ─  □  ✕ │
│──────────────────────────────────────────────│
│                                              │
│  Target Window   [▼ Discord - General    ]   │
│                                              │
│  Source Language  [▼ Auto Detect         ]   │
│  Target Language  [▼ Korean (한국어)      ]   │
│                                              │
│  STT Model       [▼ large-v3-turbo      ]   │
│  LM Studio       ● Connected (gemma-3-4b)   │
│                                              │
│  ┌────────────────────────────────────────┐  │
│  │          ▶  Start Translation          │  │
│  └────────────────────────────────────────┘  │
│                                              │
│  ─── Overlay Settings ──────────────────     │
│  Font Size   ◄ ██████████░░░ ► 18pt         │
│  Opacity     ◄ ████████░░░░░ ► 80%          │
│  Max Lines   ◄ ██████░░░░░░░ ► 5            │
│                                              │
│  Status: Ready                               │
└──────────────────────────────────────────────┘
```

### 6.2 오버레이 자막 (대상 윈도우 위)

```
┌─ Target Application Window ─────────────────────────────┐
│                                                         │
│                    (앱 콘텐츠)                            │
│                                                         │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │ ■ Speaker 1: 안녕하세요, 오늘 미팅 시작하겠습니다  │    │
│  │ ■ Speaker 2: 네, 준비되었습니다                    │    │
│  │ ■ Speaker 1: 먼저 지난주 진행 상황을 공유해주세요   │    │
│  └─────────────────────────────────────────────────┘    │
│         (반투명 배경, 하단 고정, 화자별 색상 구분)          │
└─────────────────────────────────────────────────────────┘
```

**화자 색상 팔레트**:
- Speaker 1: `#4FC3F7` (하늘색)
- Speaker 2: `#81C784` (연두색)
- Speaker 3: `#FFB74D` (주황색)
- Speaker 4: `#CE93D8` (보라색)
- Speaker 5+: 자동 순환

### 6.3 화자 상태 표시 (오버레이 상단)

새 화자가 감지되면 오버레이 상단에 일시적 알림을 표시:
```
  ┌─────────────────────────────────────┐
  │  + New speaker detected (Speaker 3) │  ← 3초 후 자동 소멸
  └─────────────────────────────────────┘
```

### 6.4 단축키 설정 패널

메인 컨트롤 패널 내 탭 또는 접이식 섹션으로 배치:
```
┌──────────────────────────────────────────────┐
│  ─── Hotkey Settings ──────────────────      │
│                                              │
│  Start/Stop Translation  [ Ctrl+Shift+T ]  ✎ │
│  Pause/Resume            [ Ctrl+Shift+P ]  ✎ │
│  Reset Speakers          [ Ctrl+Shift+R ]  ✎ │
│  Toggle Overlay          [ Ctrl+Shift+O ]  ✎ │
│  Increase Font           [ Ctrl+Shift+= ]  ✎ │
│  Decrease Font           [ Ctrl+Shift+- ]  ✎ │
│  Clear Subtitles         [ Ctrl+Shift+L ]  ✎ │
│                                              │
│  ✎ = Click to reassign (press new key combo) │
│                                              │
│  [ Reset to Defaults ]                       │
└──────────────────────────────────────────────┘
```

### 6.5 단축키 기본 매핑

| 기능 | 기본 단축키 | 설명 |
|---|---|---|
| **번역 시작/중지** | `Ctrl+Shift+T` | 전체 파이프라인 토글 (캡처→STT→번역→오버레이) |
| **일시정지/재개** | `Ctrl+Shift+P` | 캡처를 멈추지 않고 번역 출력만 일시정지 |
| **화자 초기화** | `Ctrl+Shift+R` | 화자 임베딩 전체 리셋, 화자 번호 1부터 재시작 |
| **오버레이 표시/숨김** | `Ctrl+Shift+O` | 자막 오버레이 가시성 토글 |
| **폰트 크기 증가** | `Ctrl+Shift+=` | 오버레이 폰트 1pt 증가 |
| **폰트 크기 감소** | `Ctrl+Shift+-` | 오버레이 폰트 1pt 감소 |
| **자막 클리어** | `Ctrl+Shift+L` | 현재 표시 중인 자막 전부 지우기 (기록은 유지) |

모든 단축키는 앱이 포커스가 아닌 상태에서도 동작 (글로벌 핫키).
사용자가 설정 패널에서 키 조합을 자유롭게 재매핑 가능.

---

## 7. 핵심 의존성

```
# Core
PySide6>=6.7.0              # Qt6 GUI / 오버레이
faster-whisper>=1.1.0       # STT (CTranslate2 기반 Whisper)
diart>=0.9.0                # 실시간 화자 분류
pyannote.audio>=3.3.0       # 화자 분류 모델 (diart 의존)

# Audio
process-audio-capture>=1.0.0 # Windows 프로세스별 오디오 캡처
sounddevice>=0.5.0           # 오디오 I/O (폴백/테스트용)
numpy>=1.26.0                # 오디오 데이터 처리
scipy>=1.13.0                # 리샘플링

# Translation
httpx>=0.27.0                # 비동기 HTTP 클라이언트 (LM Studio API)

# Windows
pywin32>=306                 # Win32 API (윈도우 열거, PID 추출 등)

# Hotkeys
pynput>=1.7.7                # 글로벌 키보드 훅 (시스템 전역 단축키)

# Utilities
silero-vad>=5.1              # Voice Activity Detection
torch>=2.3.0                 # PyTorch (Whisper, diart, VAD 런타임)
```

---

## 8. 비기능 요구사항

### 성능 목표
| 지표 | 목표 |
|---|---|
| STT 지연 (음성→텍스트) | < 2초 |
| 화자 분류 지연 | < 1초 |
| 번역 지연 (텍스트→번역) | < 2초 |
| 전체 파이프라인 (음성→자막) | < 4초 |
| CPU 사용률 (idle) | < 5% |
| GPU VRAM 사용 | < 4GB (medium 모델 기준) |

### 스레딩 모델
- **Main Thread**: PySide6 UI 이벤트 루프
- **Audio Thread**: 오디오 캡처 + VAD (실시간 우선)
- **STT Thread**: Faster Whisper 추론
- **Diarization Thread**: diart 추론
- **Translation Thread**: LM Studio API 호출 (비동기)
- 스레드 간 통신: `queue.Queue` 또는 Qt Signal/Slot

---

## 9. 구현 우선순위 / 마일스톤

| 순서 | 마일스톤 | 예상 작업 | 상태 |
|---|---|---|---|
| 1 | 프로젝트 세팅 + 윈도우 선택 | 모듈 구조, 윈도우 열거 UI | ⬜ |
| 2 | 오디오 캡처 파이프라인 | process-audio-capture 통합, 스트림 관리 | ⬜ |
| 3 | STT 통합 | Faster Whisper 실시간 스트리밍 | ⬜ |
| 4 | 화자 분류 통합 | diart 파이프라인, STT와 병합, 동적 화자 감지 | ⬜ |
| 5 | 번역 엔진 | LM Studio API 클라이언트, 프롬프트 최적화 | ⬜ |
| 6 | 오버레이 UI | 투명 자막 오버레이, 윈도우 추적, 화자 알림 | ⬜ |
| 7 | 단축키 + 설정 시스템 | 글로벌 핫키, 키 매핑 UI, config 영속 저장 | ⬜ |
| 8 | 화자 관리 기능 | 화자 초기화, 라벨 커스터마이징 | ⬜ |
| 9 | 메인 UI 통합 | 전체 파이프라인 연결, 설정 UI | ⬜ |
| 10 | 최적화 + 폴리싱 | 지연 최소화, 에러 핸들링, UX 개선 | ⬜ |

---

## 10. 리스크 및 대안

| 리스크 | 영향 | 대안 |
|---|---|---|
| `process-audio-capture`가 특정 앱에서 작동 안 함 | 오디오 캡처 실패 | PyAudioWPatch로 시스템 전체 오디오 캡처 폴백 |
| diart 실시간 성능 부족 (저사양 PC) | 화자 분류 지연 | 화자 분류 비활성화 옵션 제공, 또는 간단한 VAD 기반 분류로 대체 |
| LM Studio 번역 품질 낮음 | 번역 결과 부정확 | 모델 변경 (Qwen3-8B, Llama 3.1 등) 또는 번역 프롬프트 튜닝 |
| GPU VRAM 부족 | STT + 화자 분류 동시 실행 불가 | 모델 크기 축소 (medium→small), 또는 CPU 모드 사용 |
| 대상 윈도우 이동/최소화 | 오버레이 위치 어긋남 | 윈도우 위치 폴링 + 최소화 시 오버레이 자동 숨김 |
| 화자 분류가 동일인을 다른 화자로 인식 (과분류) | 자막 혼란 | 유사도 임계값 튜닝 + 화자 초기화(단축키)로 즉시 리셋 가능 |
| 글로벌 단축키가 다른 앱과 충돌 | 핫키 미작동 | 충돌 감지 경고 + 사용자 재매핑 UI 제공 |

---

## 11. 기술 결정 요약

| 항목 | 선택 | 근거 |
|---|---|---|
| 오디오 캡처 | process-audio-capture | 유일한 프로세스별 오디오 격리 솔루션 (Windows) |
| STT | Faster Whisper | 로컬 실행, 무료, Whisper 대비 4x 빠름, 스트리밍 지원 |
| 화자 분류 | diart (pyannote 기반) | 실시간 스트리밍 특화, 사전학습 모델 제공 |
| 번역 | LM Studio (로컬 LLM) | 무료, 오프라인, OpenAI 호환 API, 2026.03 기준 무료 대안 없음 |
| GUI/오버레이 | PySide6 | LGPL 라이선스, Qt6 투명 오버레이 지원, 성숙한 생태계 |
| VAD | Silero VAD | 경량, 고정확도, CPU에서도 빠름 |
