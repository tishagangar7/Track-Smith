import logging
from pathlib import Path

from agent.config import AUDIO_SERVER_URL, AUDIO_DURATION

logger = logging.getLogger(__name__)
from agent.skills.audio_gen import AudioServerOfflineError, _AUDIO_EXTS, generate_audio_continuation
from agent.skills.continuation_gen import generate_continuations
from agent.skills.input_analyzer import analyze_input, validate_input_for_generation


def run(midi_path: str, prompt: str = None, style_context: str = None, output_dir: str = "") -> dict:
    if not midi_path:
        return {"type": "error", "message": "No file loaded — drop a MIDI or MP3 first"}

    analysis = analyze_input(midi_path)
    err = validate_input_for_generation(analysis)
    if err:
        return {"type": "error", "message": err}

    combined_prompt = " ".join(filter(None, [style_context, prompt])) or None

    # Audio-first: try MusicGen on DGX
    # Pass original file as conditioning reference only when it's audio (not MIDI)
    ref_audio = midi_path if Path(midi_path).suffix.lower() in _AUDIO_EXTS else None

    audio_path: str | None = None
    audio_note = ""
    if AUDIO_SERVER_URL:
        try:
            stem = Path(midi_path).stem
            out_wav = str(Path(output_dir) / f"aux_audio_{stem}.wav")
            audio_path = generate_audio_continuation(
                analysis, out_wav, prompt=combined_prompt, duration=AUDIO_DURATION,
                original_audio_path=ref_audio,
            )
            audio_note = f"\nAudio continuation: {Path(audio_path).name} (▶ Play above)"
        except AudioServerOfflineError as e:
            logger.error("Audio generation failed: %s — falling back to MIDI", e)
            audio_note = "\n(Audio server offline — MIDI only)"

    # MIDI generation always runs as primary / fallback
    results = generate_continuations(
        analysis, output_dir=output_dir, prompt=combined_prompt, mode="full",
        original_midi_path=midi_path,
    )

    if not results and not audio_path:
        return {"type": "error", "message": "Generation failed — check NVIDIA_API_KEY"}

    lines = [
        f"Matched to your track: {analysis.get('key', '?')} @ {analysis.get('tempo', '?')} BPM",
        f"Chords: {' → '.join(analysis.get('chord_progression', []) or [])}",
    ]
    if audio_note:
        lines.append(audio_note)
    lines += [
        "",
        f"Generated {len(results)} MIDI continuations (full 6-track producer loop):",
        "",
    ]
    for r in results:
        lines.append(f"[{r['option']}] {r.get('vibe', '')} · {r.get('key', '')} · {r.get('tempo', '')} BPM")
        lines.append(f"    {r.get('description', '')}")
        lines.append(f"    Chords: {' → '.join(r.get('chord_progression', []))}")
        lines.append("")

    lines.append("Select a result from the left panel, then click '→ Ghost Produce in FL Studio'.")

    return {
        "type": "files",
        "message": "\n".join(lines),
        "files": results,
        "analysis": analysis,
        "audio_path": audio_path,
    }
