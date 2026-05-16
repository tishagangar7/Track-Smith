from agent.skills.composer import compose_from_vibe


def run(vibe_text: str, output_dir: str) -> dict:
    if not vibe_text.strip():
        return {"type": "error", "message": "Usage: /vibe <description>  e.g. /vibe dark trap heavy 808s"}

    results = compose_from_vibe(vibe_text.strip(), output_dir)
    if not results:
        return {"type": "error", "message": "Composition failed — check NVIDIA_API_KEY"}

    lines = [f"Generated {len(results)} variations for: \"{vibe_text}\"", ""]
    for r in results:
        lines.append(f"[{r['variation']}] {r.get('vibe', '')} · {r.get('key', '')} · {r.get('tempo', '')} BPM")
        lines.append(f"    {r.get('description', '')}")
        lines.append(f"    {r['filepath']}")
        lines.append("")

    return {"type": "files", "message": "\n".join(lines), "files": results}
