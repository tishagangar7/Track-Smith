# Aux — Product Requirements Document

## Overview

Aux is an AI music production agent built for the NVIDIA NemoClaw hackathon. It runs on an ASUS DGX Spark (GX10) with Nemotron-4-340B running locally. Core concept: **generative fill for DAWs** — drop a MIDI file and a text prompt, get back musical continuations analyzed from context (key, tempo, energy, chord progression).

## Problem

Producers hit creative blocks mid-session. Existing AI music tools are cloud-only, slow, and don't integrate into the production workflow. There's no tool that:
- Lives inside or alongside a DAW
- Understands the musical context of an existing MIDI
- Generates continuations that are immediately editable in the piano roll

## Solution

Two delivery modes, same AI pipeline:

### Mode 1 — Telegram Bot (existing)
Drop a MIDI into the `/watched` folder. Bot asks for creative direction. Nemotron reasons about 3 continuation options. MIDI files sent back to Telegram.

### Mode 2 — Desktop Plugin Companion (new)
PyQt6 app runs alongside FL Studio. Slash command chat interface. Generated MIDI injects directly into FL Studio piano roll via Script Pad. Notes fully editable immediately.

---

## Target Users

- Independent producers working in FL Studio
- Hackathon context: NVIDIA engineers and judges evaluating Nemotron-powered creative tools

---

## Features

### Slash Commands

| Command | Description | Powered By |
|---------|-------------|------------|
| `/fill` | Analyze loaded MIDI + generate 3 MIDI continuations | `midi_analyzer` + `continuation_gen` |
| `/vibe <text>` | Compose original track from text description | `composer.compose_from_vibe` |
| `/suggest` | 3 text-only production ideas, no MIDI generated | `continuation_gen` suggest mode |
| `/analyze` | Read key, tempo, energy, chord progression from MIDI | `midi_analyzer` |
| `/mix` | Generate complementary stem for loaded MIDI | `continuation_gen` with instrument directive |
| `/style <artist>` | Nudge all subsequent generation toward artist reference | Prompt injection into Nemotron |

### Piano Roll Injection
- App writes selected output to `plugin_output/pending.mid`
- FL Studio Script Pad script (`aux_import.py`) reads `pending.mid` → inserts notes via `flp.score.addNote()`
- Notes appear in piano roll, fully editable

### UI
- Dark DAW-aesthetic theme (QSS)
- Drag-and-drop MIDI zone (left panel)
- Scrolling chat log + slash command input (right panel)
- Output file list with "→ Piano Roll" per-file button
- "FL Script Setup" button: pre-fills and copies `aux_import.py` with correct path

---

## Architecture

```
plugin_main.py              ← PyQt6 entry point
plugin/
  app.py                    ← QMainWindow, layout, signal wiring
  ui/
    chat_panel.py           ← QTextEdit log + QLineEdit input + QThread workers
    midi_drop_zone.py       ← QLabel with dragEnterEvent / dropEvent
    styles.qss              ← Dark DAW theme
  commands/
    router.py               ← Parses /cmd args, dispatches
    analyze.py              ← Wraps midi_analyzer.analyze_midi
    vibe.py                 ← Wraps composer.compose_from_vibe
    fill.py                 ← Wraps continuation_gen (mode='full')
    suggest.py              ← Wraps continuation_gen (mode='suggest')
    mix.py                  ← continuation_gen with instrument directive
    style.py                ← Returns style token, stored in ChatPanel state
  fl_script/
    aux_import.py           ← FL Studio Script Pad: pending.mid → piano roll

agent/                      ← Core AI pipeline (unchanged)
  skills/
    midi_analyzer.py        ← Key detection, energy, chord progression
    continuation_gen.py     ← Nemotron reasoning + MIDI generation + drums
    composer.py             ← Vibe-to-MIDI pipeline
    dj_engine.py            ← Autonomous set-making agent
  config.py
  pairing.py
  watcher.py

bot/
  telegram_bot.py           ← Telegram interface (unchanged, runs via main.py)

main.py                     ← Telegram + folder watcher entry point
plugin_main.py              ← Desktop app entry point
plugin_output/              ← Generated MIDI files land here
```

### FL Studio Bridge (file-based IPC)
```
Companion App → /fill → Nemotron inference → writes plugin_output/pending.mid
FL Script Pad → user clicks Run → reads pending.mid → flp.score.addNote() → piano roll
```

No sockets, no network calls between app and FL Studio.

---

## Technical Stack

| Component | Technology |
|-----------|-----------|
| LLM inference | NVIDIA Nemotron-4-340B-Instruct via NVIDIA API |
| Hardware | ASUS DGX Spark GX10 |
| MIDI analysis | `pretty_midi`, `librosa`, Krumhansl-Schmuckler key detection |
| MIDI generation | `pretty_midi`, `mido` |
| Desktop UI | PyQt6 |
| Telegram interface | `python-telegram-bot` 21.x |
| Folder watching | `watchdog` |

---

## Non-Goals

- True VST/VST3 plugin (C++ build time incompatible with hackathon timeline)
- FL Studio MIDI Controller Script (sandbox blocks HTTP/sockets)
- Real-time piano roll sync (requires JUCE/COM)
- Cloud inference (all inference runs locally on GX10)
- DAW-agnostic support (FL Studio only for piano roll injection; Telegram mode is DAW-agnostic)

---

## Success Criteria (Demo)

1. Drop a MIDI → `/analyze` → correct key/tempo/energy displayed
2. `/vibe dark trap heavy 808s` → 3 MIDI variations generated in < 30s
3. `/fill` → 3 continuation MIDIs → click "→ Piano Roll" → notes appear in FL Studio piano roll
4. Notes are fully editable in FL after import
5. `/suggest` → 3 text ideas displayed, no MIDI files written
6. Telegram bot still works independently via `python main.py`
