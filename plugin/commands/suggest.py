from agent.skills.midi_analyzer import analyze_midi
from agent.skills.continuation_gen import generate_continuations


def run(midi_path: str, prompt: str = None, style_context: str = None) -> dict:
    if not midi_path:
        return {"type": "error", "message": "No MIDI loaded — drop a file first"}

    combined_prompt = " ".join(filter(None, [style_context, prompt])) or None
    analysis = analyze_midi(midi_path)
    result = generate_continuations(analysis, output_dir="", prompt=combined_prompt, mode="suggest")

    return {"type": "text", "message": result}
