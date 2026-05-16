# CLAUDE.md — Aux

## Project

AI music production agent. Two modes: Telegram bot (`main.py`) and PyQt6 desktop companion (`plugin_main.py`). Both use the same `agent/` pipeline. Runs Nemotron-4-340B via NVIDIA API. Hardware: ASUS DGX Spark GX10.

## Media input

Drop zone accepts **MIDI** (`.mid`) and **audio** (`.mp3`, `.wav`). MP3 requires `ffmpeg` (`brew install ffmpeg`).

Playback modes: **Input + Fill** (default), Input only, Fill only. MP3 input + continuation plays audio then MIDI sequentially.

## Run

```bash
# Desktop plugin (primary)
python plugin_main.py

# Telegram bot (secondary, unchanged)
python main.py

# Test without API calls
STUB_MODE=true python plugin_main.py
```

## Env vars (`.env`)
```
NVIDIA_API_KEY=...       # required for both modes
TELEGRAM_TOKEN=...       # required for main.py only
TELEGRAM_CHAT_ID=...     # required for main.py only
STUB_MODE=true           # skip Nemotron calls (test/CI)
```

## Key files

| Path | Purpose |
|------|---------|
| `agent/skills/midi_analyzer.py` | Key detection (Krumhansl-Schmuckler), energy, chord progression |
| `agent/skills/continuation_gen.py` | Nemotron reasoning + MIDI generation + drum patterns |
| `agent/skills/composer.py` | Vibe text → Nemotron → MIDI (3 energy variations) |
| `agent/skills/dj_engine.py` | Autonomous set-making, Nemotron track selection |
| `agent/config.py` | All env vars + Nemotron model config |
| `plugin/commands/router.py` | Slash command parser + dispatcher |
| `plugin/app.py` | QMainWindow — left panel (MIDI drop + file list) + right panel (chat) |
| `plugin/ui/chat_panel.py` | QTextEdit log + QLineEdit input + QThread inference workers |
| `plugin/fl_script/aux_import.py` | FL Studio Script Pad file: `pending.mid` → piano roll via `flp.score.addNote()` |
| `plugin_output/` | All generated MIDI lands here. `pending.mid` = file queued for FL import |

## Slash commands

`/fill` `/vibe <text>` `/suggest` `/analyze` `/mix` `/style <artist>`

All commands call existing `agent/skills/` functions — no new inference logic in `plugin/commands/`.

## FL Studio integration

File-based IPC. No sockets.

1. App writes `plugin_output/pending.mid`
2. User opens FL Studio Script Pad → pastes `aux_import.py` (app pre-fills path via "FL Script Setup" button)
3. User clicks Run → notes inserted into piano roll via `flp.score.addNote()`
4. `pending.mid` deleted by script after import

## Architecture rules

- `agent/` is the AI core — never import from `plugin/` inside `agent/`
- `plugin/commands/` are thin wrappers — no inference logic lives there
- All Nemotron calls happen in `QThread` workers (`_InferenceWorker` in `chat_panel.py`) — never on the UI thread
- Style context (`/style`) stored as `_style_context` in `ChatPanel`, injected into next `/fill`/`/mix`/`/suggest`
- `validate()` in `agent/config.py` checks Telegram vars too — `plugin_main.py` does its own lighter check (NVIDIA_API_KEY only)

## Do not

- Import `bot/` from `plugin/` or vice versa
- Call Nemotron on the Qt main thread (blocks UI)
- Add error handling for impossible cases inside `agent/skills/` — they already have fallbacks
- Build a VST or modify FL Studio's Python MIDI Controller Script path (sandbox blocks networking)

## Dependencies

```
PyQt6>=6.6.0   # desktop UI
pretty_midi    # MIDI read/write
mido           # MIDI parsing (also needed in FL Script Pad)
librosa        # audio analysis
requests       # Nemotron API calls
watchdog       # folder watcher
python-dotenv  # .env loading
python-telegram-bot==21.3
```

Python 3.11 recommended (matches Dockerfile). Python 3.14 on macOS has broken `libexpat` — use pyenv or a venv.
