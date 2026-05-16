import logging
from pathlib import Path

from agent.config import AUDIO_SERVER_URL, AUDIO_DURATION

logger = logging.getLogger(__name__)
from agent.skills.audio_gen import AudioServerOfflineError, _AUDIO_EXTS, generate_audio_continuation, combine_audio_with_continuation
from agent.skills.continuation_gen import generate_continuations
from agent.skills.input_analyzer import analyze_input, validate_input_for_generation


def _placement_suggestions(analysis: dict, plans: list) -> list[str]:
    """Heuristic placement suggestions — no extra API call."""
    energy = float(analysis.get("energy", 0.5))
    tempo = float(analysis.get("tempo") or 120)
    suggestions = []

    # Section placement by energy
    if energy > 0.68:
        suggestions.append("Drop this under the chorus or hook — high energy matches that intensity")
    elif energy < 0.38:
        suggestions.append("Works as an intro or interlude — low energy feels like a breath before the verse")
    else:
        suggestions.append("Sits well in a pre-chorus or bridge — mid energy builds nicely into the drop")

    # Genre-based placement from first Nemotron plan
    if plans:
        genre = (plans[0].get("genre") or "").lower()
        mood  = (plans[0].get("mood") or "").lower()
        drum  = (plans[0].get("drum_pattern") or "").lower()
        if genre in ("trap", "drill"):
            suggestions.append("Layer this under a rap verse or ad-lib section — the 808s sit in the pocket")
        elif genre in ("lo-fi", "ambient"):
            suggestions.append("Use as an instrumental interlude or an outro fade-out")
        elif genre in ("house", "dance"):
            suggestions.append("Great as a build-up loop leading into a drop or chorus")
        if mood == "dark":
            suggestions.append("Pair with a spoken word section or a moody rap verse")
        elif mood == "uplifting":
            suggestions.append("Lift the final chorus with this — stack it under the top-line vocal")
        if drum == "boom_bap":
            suggestions.append("Chop this up — sample 2–4 bars as the main loop under the verse")

    # Tempo hint
    if tempo < 78:
        suggestions.append("Slow tempo — try halftime feel: play every other bar for a breakdown effect")
    elif tempo > 135:
        suggestions.append("Fast tempo — works as a double-time run or a filler between sections")

    return suggestions[:3]  # cap at 3


def run(midi_path: str, prompt: str = None, style_context: str = None, output_dir: str = "") -> dict:
    if not midi_path:
        return {"type": "error", "message": "No file loaded — drop a MIDI or MP3 first"}

    analysis = analyze_input(midi_path)
    err = validate_input_for_generation(analysis)
    if err:
        return {"type": "error", "message": err}

    combined_prompt = " ".join(filter(None, [style_context, prompt])) or None

    ref_audio = midi_path if Path(midi_path).suffix.lower() in _AUDIO_EXTS else None

    audio_continuation: str | None = None   # raw MusicGen WAV
    audio_combined: str | None = None       # original + continuation crossfaded
    audio_note = ""

    if AUDIO_SERVER_URL:
        try:
            stem = Path(midi_path).stem
            out_wav = str(Path(output_dir) / f"aux_audio_{stem}.wav")
            audio_continuation = generate_audio_continuation(
                analysis, out_wav, prompt=combined_prompt, duration=AUDIO_DURATION,
                original_audio_path=ref_audio,
            )
            if ref_audio and Path(ref_audio).exists():
                combined_out = str(Path(output_dir) / f"aux_combined_{stem}.wav")
                try:
                    audio_combined = combine_audio_with_continuation(
                        ref_audio, audio_continuation, combined_out
                    )
                except Exception as ce:
                    logger.warning("Audio combine failed (%s) — combined unavailable", ce)

            if audio_combined:
                audio_note = "\nAudio: ▶ Combined (input → continuation) | Solo continuation also saved"
            else:
                audio_note = f"\nAudio continuation: {Path(audio_continuation).name} (▶ Play above)"
        except AudioServerOfflineError as e:
            logger.error("Audio generation failed: %s — falling back to MIDI", e)
            audio_note = "\n(Audio server offline — MIDI only)"

    # MIDI generation always runs
    results = generate_continuations(
        analysis, output_dir=output_dir, prompt=combined_prompt, mode="full",
        original_midi_path=midi_path,
    )

    if not results and not audio_continuation:
        return {"type": "error", "message": "Generation failed — check NVIDIA_API_KEY"}

    # Placement suggestions
    placement = _placement_suggestions(analysis, results)

    lines = [
        f"Matched to your track: {analysis.get('key', '?')} @ {analysis.get('tempo', '?')} BPM",
        f"Chords: {' → '.join(analysis.get('chord_progression', []) or [])}",
    ]
    if audio_note:
        lines.append(audio_note)

    if placement:
        lines += ["", "Where this could fit in your song:"]
        lines += [f"  • {s}" for s in placement]

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
        "audio_path": audio_combined or audio_continuation,
        "audio_continuation": audio_continuation,
        "audio_combined": audio_combined,
    }
