# BAVEL

Real-time speaker-aware overlay translation system for Windows.

Captures audio from a specific window, transcribes speech with speaker identification, translates it via a local LLM, and displays subtitles as a transparent overlay on top of the target application.

## Requirements

- Windows 10 (Build 19041+) / Windows 11
- Python 3.11+
- CUDA-capable GPU recommended (CPU fallback available)
- [LM Studio](https://lmstudio.ai/) running locally for translation

## Setup

```bash
pip install -r requirements.txt
```

### Hugging Face Token (for pyannote speaker diarization)

```bash
# Required for downloading pyannote models
huggingface-cli login
```

### LM Studio

1. Install and launch LM Studio
2. Load a translation model (recommended: `gemma-3-4b` or `Qwen3-8B`)
3. Start the local server (default: `http://localhost:1234`)

## Usage

```bash
python main.py
```

1. Select a target window from the dropdown
2. Choose source/target languages
3. Click **Start Translation**

## Hotkeys (global, works when app is not focused)

| Action | Default |
|---|---|
| Start/Stop Translation | `Ctrl+Shift+T` |
| Pause/Resume | `Ctrl+Shift+P` |
| Reset Speakers | `Ctrl+Shift+R` |
| Toggle Overlay | `Ctrl+Shift+O` |
| Increase Font | `Ctrl+Shift+=` |
| Decrease Font | `Ctrl+Shift+-` |
| Clear Subtitles | `Ctrl+Shift+L` |

All hotkeys are reassignable from the Hotkeys tab in the control panel.

## Architecture

```
Audio Capture (WASAPI) -> VAD (Silero) -> STT (Faster Whisper) + Diarization (diart)
    -> Translation (LM Studio) -> Overlay (PySide6 transparent window)
```

## Tech Stack

- **Audio**: `process-audio-capture` (per-process WASAPI capture)
- **STT**: `faster-whisper` (CTranslate2-based Whisper)
- **Diarization**: `diart` + `pyannote.audio`
- **Translation**: LM Studio (OpenAI-compatible local API)
- **UI/Overlay**: PySide6 (Qt6)
- **VAD**: Silero VAD
- **Hotkeys**: pynput
