from agent.skills.input_analyzer import analyze_input, validate_input_for_generation
from agent.skills.continuation_gen import generate_continuations


def run(midi_path: str, prompt: str = None, style_context: str = None) -> dict:
    if not midi_path:
        return {"type": "error", "message": "No file loaded — drop a MIDI or MP3 first"}

    analysis = analyze_input(midi_path)
    err = validate_input_for_generation(analysis)
    if err:
        return {"type": "error", "message": err}

    combined_prompt = " ".join(filter(None, [style_context, prompt])) or None
    result = generate_continuations(analysis, output_dir="", prompt=combined_prompt, mode="suggest")

    return {"type": "text", "message": result}
