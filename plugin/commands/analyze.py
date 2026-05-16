from agent.skills.midi_analyzer import analyze_midi


def run(midi_path: str) -> dict:
    analysis = analyze_midi(midi_path)
    lines = [
        f"Key:         {analysis['key']}",
        f"Tempo:       {analysis['tempo']:.1f} BPM",
        f"Duration:    {analysis['duration']:.1f}s",
        f"Energy:      {analysis['energy']:.2f}  (0=low, 1=high)",
        f"Tracks:      {analysis['num_tracks']}",
        f"Total notes: {analysis['total_notes']}",
        f"Instruments: {', '.join(analysis['instruments']) or 'none detected'}",
        f"Chords:      {' → '.join(analysis.get('chord_progression', [])) or 'n/a'}",
    ]
    return {"type": "text", "message": "\n".join(lines), "analysis": analysis}
