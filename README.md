# TrackSmith

**Make music with an agent.**

TrackSmith is an agentic AI music production assistant that lives inside a producer's workflow. Drop in a beat, loop, or unfinished idea — TrackSmith analyzes it, reasons about what it needs, generates continuations, separates stems, and writes everything back into your DAW session.

Built for independent creators who deserve the same creative feedback loop that professional producers already have.

---

## What it does

- **Analyze** — BPM, key, chord progression, energy, brightness, onset density
- **Reason** — NVIDIA Nemotron (123B) interprets what those features mean creatively via a ReAct loop
- **Validate** — Qwen checks whether suggestions are musically coherent
- **Generate** — MusicGen creates audible audio continuations matched to your track
- **Separate** — Demucs splits your track into drums, bass, melody, harmony
- **Export** — Send MIDI and audio directly into FL Studio in one click

---

## Stack

| Layer | Model / Tool |
|-------|-------------|
| Reasoning | NVIDIA Nemotron-3-Super 123B (local, DGX Spark) |
| Validation | Qwen 3.6 35B (local) |
| Audio generation | MusicGen (local, DGX Spark) |
| Stem separation | Demucs |
| Security | NemoClaw — policy-controlled agent execution |
| UI | PyQt6 desktop app |

---

## Run

```bash
# Desktop app
python plugin_main.py

# Test without API calls
STUB_MODE=true python plugin_main.py
```

## Env vars (`.env`)

```
NVIDIA_API_KEY=...
DGX_OLLAMA_URL=http://localhost:11435/v1
AUDIO_SERVER_URL=http://100.77.70.20:8001
OPENROUTER_API_KEY=...
```

## Slash commands

| Command | What it does |
|---------|-------------|
| `/fill` | Generate MIDI + audio continuation |
| `/analyze` | Full harmonic analysis |
| `/style <artist>` | Lock style context (any artist or genre) |
| `/vibe <text>` | Freeform creative direction |
| `/mix` | DJ-style transition generation |
| `/stems` | Separate into drums, bass, melody, harmony |

---

## Security

TrackSmith handles unreleased music and private project files. **NemoClaw** enforces strict policy rules — the agent can only read/write approved locations and call approved local endpoints. Every action is logged in the policy panel.

---

## Hardware

Runs on **ASUS DGX Spark GX10** with local Nemotron-3-Super (123B), Qwen (35B), and MusicGen. Falls back to OpenRouter when local is unavailable.
