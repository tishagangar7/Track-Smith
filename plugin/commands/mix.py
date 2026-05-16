from pathlib import Path

from agent.config import AUDIO_SERVER_URL, AUDIO_DURATION
from agent.skills.audio_gen import AudioServerOfflineError, generate_audio_continuation
from agent.skills.continuation_gen import generate_continuations
from agent.skills.input_analyzer import analyze_input, validate_input_for_generation


def run(midi_path: str, prompt: str = None, style_context: str = None, output_dir: str = "") -> dict:
    if not midi_path:
        return {"type": "error", "message": "No file loaded — drop a MIDI or MP3 first"}

    analysis = analyze_input(midi_path)
    err = validate_input_for_generation(analysis)
    if err:
        return {"type": "error", "message": err}

    instruments = ", ".join(analysis.get("instruments", [])) or "melody"
    mix_directive = (
        f"Generate a complementary stem that pairs with: {instruments}. "
        "Add a new instrument layer that fills harmonic space."
    )
    combined_prompt = " ".join(filter(None, [style_context, mix_directive, prompt])) or mix_directive

    # Audio-first: try MusicGen on DGX
    audio_path: str | None = None
    audio_note = ""
    if AUDIO_SERVER_URL:
        try:
            stem = Path(midi_path).stem
            out_wav = str(Path(output_dir) / f"aux_mix_{stem}.wav")
            audio_path = generate_audio_continuation(
                analysis, out_wav, prompt=combined_prompt, duration=AUDIO_DURATION
            )
            audio_note = f"\nAudio mix: {Path(audio_path).name} (▶ Play above)"
        except AudioServerOfflineError:
            audio_note = "\n(Audio server offline — MIDI only)"

    # MIDI generation always runs
    results = generate_continuations(
        analysis, output_dir=output_dir, prompt=combined_prompt, mode="full",
        original_midi_path=midi_path,
    )

    if not results and not audio_path:
        return {"type": "error", "message": "Mix generation failed — check NVIDIA_API_KEY"}

    lines = [f"Generated {len(results)} complementary stems:", ""]
    if audio_note:
        lines.insert(0, audio_note)
        lines.insert(1, "")
    for r in results:
        lines.append(f"[{r['option']}] {r.get('vibe', '')} · {r.get('key', '')} · {r.get('tempo', '')} BPM")
        lines.append(f"    {r.get('description', '')}")
        lines.append("")

    lines.append("Select a result from the left panel, then click '→ Ghost Produce in FL Studio'.")

    return {
        "type": "files",
        "message": "\n".join(lines),
        "files": results,
        "analysis": analysis,
        "audio_path": audio_path,
    }
