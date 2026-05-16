"""
Converts a generated MIDI file to the structured command JSON
that device_Aux.py (FL Studio MIDI Controller Script) expects.

Command schema:
{
  "tempo": 140,
  "bars": 4,
  "notes": [
    {"beat": 0.0, "pitch": 60, "velocity": 100, "duration_beats": 0.5, "channel": 0},
    ...
  ]
}

channel 0  = melodic (FL channel rack index 0)
channel 9  = drums   (FL channel rack index 1, GM drum map)
"""

import json
import pretty_midi
from pathlib import Path

COMMAND_FILE = Path.home() / "aux_fl_command.json"
BARS = 4
BEATS_PER_BAR = 4
MAX_BEATS = BARS * BEATS_PER_BAR  # 16


def midi_to_fl_command(midi_path: str, bars: int = BARS) -> dict:
    mid = pretty_midi.PrettyMIDI(midi_path)
    tempo_map = mid.get_tempo_changes()
    tempo = float(tempo_map[1][0]) if len(tempo_map[1]) else 120.0
    spb = 60.0 / tempo
    max_beat = bars * BEATS_PER_BAR

    notes = []

    for instrument in mid.instruments:
        ch = 9 if instrument.is_drum else 0
        for note in instrument.notes:
            beat = note.start / spb
            if beat >= max_beat:
                continue
            dur = min((note.end - note.start) / spb, max_beat - beat)
            notes.append({
                "beat": round(beat, 3),
                "pitch": note.pitch,
                "velocity": note.velocity,
                "duration_beats": round(max(0.05, dur), 3),
                "channel": ch,
            })

    notes.sort(key=lambda n: n["beat"])

    return {"tempo": round(tempo), "bars": bars, "notes": notes}


def write_command(midi_path: str) -> str:
    cmd = midi_to_fl_command(midi_path)
    COMMAND_FILE.write_text(json.dumps(cmd, indent=2))
    return str(COMMAND_FILE)
