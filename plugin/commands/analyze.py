from agent.skills.input_analyzer import analyze_input


def run(midi_path: str) -> dict:
    analysis = analyze_input(midi_path)
    src = analysis.get("source_type", "midi")
    lines = [
        f"Source:      {src}",
        f"Key:         {analysis['key']}",
        f"Tempo:       {analysis['tempo']:.1f} BPM",
        f"Duration:    {analysis['duration']:.1f}s",
        f"Energy:      {analysis['energy']:.2f}  (0=low, 1=high)",
    ]

    if src == "audio":
        af = analysis.get("audio_features") or {}
        lines.append(f"Character:   {af.get('brightness', 'n/a')} · onsets {af.get('onset_density', '?')}/s")
    else:
        lines.extend([
            f"Tracks:      {analysis['num_tracks']}",
            f"Total notes: {analysis['total_notes']}",
            f"Instruments: {', '.join(analysis['instruments']) or 'none detected'}",
        ])
        if analysis["total_notes"] == 0:
            lines.append("WARNING:     0 notes detected — export MIDI with piano-roll notes")

    lines.append(f"Chords:      {' → '.join(analysis.get('chord_progression', [])) or 'n/a'}")

    if analysis.get("note_events"):
        sample = analysis["note_events"][:8]
        note_str = ", ".join(f"{e.get('name')}@{e.get('start_beat')}b" for e in sample)
        lines.append(f"Notes:       {note_str}")

    return {"type": "text", "message": "\n".join(lines), "analysis": analysis}
