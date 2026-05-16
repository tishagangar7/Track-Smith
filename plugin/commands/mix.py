from agent.skills.midi_analyzer import analyze_midi
from agent.skills.continuation_gen import generate_continuations


def run(midi_path: str, prompt: str = None, style_context: str = None, output_dir: str = "") -> dict:
    if not midi_path:
        return {"type": "error", "message": "No MIDI loaded — drop a file first"}

    analysis = analyze_midi(midi_path)

    instruments = ", ".join(analysis.get("instruments", [])) or "melody"
    mix_directive = f"Generate a complementary stem that pairs with: {instruments}. Add a new instrument layer that fills harmonic space."
    combined_prompt = " ".join(filter(None, [style_context, mix_directive, prompt])) or mix_directive

    results = generate_continuations(analysis, output_dir=output_dir, prompt=combined_prompt, mode="full")

    if not results:
        return {"type": "error", "message": "Mix generation failed — check NVIDIA_API_KEY"}

    lines = [f"Generated {len(results)} complementary stems:", ""]
    for r in results:
        lines.append(f"[{r['option']}] {r.get('vibe', '')} · {r.get('key', '')} · {r.get('tempo', '')} BPM")
        lines.append(f"    {r.get('description', '')}")
        lines.append("")

    lines.append("Click → Piano Roll on any result to send it to FL Studio.")

    return {"type": "files", "message": "\n".join(lines), "files": results, "analysis": analysis}
