from agent.skills.midi_analyzer import analyze_midi
from agent.skills.continuation_gen import generate_continuations


def run(midi_path: str, prompt: str = None, style_context: str = None, output_dir: str = "") -> dict:
    if not midi_path:
        return {"type": "error", "message": "No MIDI loaded — drop a file first"}

    combined_prompt = " ".join(filter(None, [style_context, prompt])) or None
    analysis = analyze_midi(midi_path)
    results = generate_continuations(analysis, output_dir=output_dir, prompt=combined_prompt, mode="full")

    if not results:
        return {"type": "error", "message": "Generation failed — check NVIDIA_API_KEY"}

    lines = [f"Generated {len(results)} continuations:", ""]
    for r in results:
        lines.append(f"[{r['option']}] {r.get('vibe', '')} · {r.get('key', '')} · {r.get('tempo', '')} BPM")
        lines.append(f"    {r.get('description', '')}")
        lines.append(f"    Chords: {' → '.join(r.get('chord_progression', []))}")
        lines.append("")

    lines.append("Select a result from the left panel, then click '→ Ghost Produce in FL Studio'.")

    return {"type": "files", "message": "\n".join(lines), "files": results, "analysis": analysis}
