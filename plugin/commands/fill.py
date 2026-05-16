from agent.skills.input_analyzer import analyze_input, validate_input_for_generation
from agent.skills.continuation_gen import generate_continuations


def run(midi_path: str, prompt: str = None, style_context: str = None, output_dir: str = "") -> dict:
    if not midi_path:
        return {"type": "error", "message": "No file loaded — drop a MIDI or MP3 first"}

    analysis = analyze_input(midi_path)
    err = validate_input_for_generation(analysis)
    if err:
        return {"type": "error", "message": err}

    combined_prompt = " ".join(filter(None, [style_context, prompt])) or None
    results = generate_continuations(analysis, output_dir=output_dir, prompt=combined_prompt, mode="full")

    if not results:
        return {"type": "error", "message": "Generation failed — check NVIDIA_API_KEY"}

    lines = [
        f"Matched to your track: {analysis.get('key', '?')} @ {analysis.get('tempo', '?')} BPM",
        f"Chords: {' → '.join(analysis.get('chord_progression', []) or [])}",
        "",
        f"Generated {len(results)} continuations (each is a different layer):",
        "",
    ]
    for r in results:
        lines.append(f"[{r['option']}] {r.get('vibe', '')} · {r.get('key', '')} · {r.get('tempo', '')} BPM")
        lines.append(f"    {r.get('description', '')}")
        lines.append(f"    Chords: {' → '.join(r.get('chord_progression', []))}")
        lines.append("")

    lines.append("Select a result from the left panel, then click '→ Ghost Produce in FL Studio'.")

    return {"type": "files", "message": "\n".join(lines), "files": results, "analysis": analysis}
