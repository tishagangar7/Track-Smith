"""Merge input MIDI with a continuation for in-app preview."""

from pathlib import Path

import pretty_midi


def merge_input_and_continuation(
    input_path: str,
    continuation_path: str,
    output_path: str | None = None,
) -> str:
    """
    Append continuation notes after the input timeline.
    Returns path to merged MIDI file.
    """
    input_mid = pretty_midi.PrettyMIDI(input_path)
    cont_mid = pretty_midi.PrettyMIDI(continuation_path)

    offset = input_mid.get_end_time()
    if offset <= 0:
        offset = 0.01

    out = pretty_midi.PrettyMIDI()
    try:
        tempos = input_mid.get_tempo_changes()[1]
        tempo = float(tempos[0]) if len(tempos) else 120.0
    except Exception:
        tempo = 120.0
    out = pretty_midi.PrettyMIDI(initial_tempo=tempo)

    for inst in input_mid.instruments:
        new_inst = pretty_midi.Instrument(
            program=inst.program, is_drum=inst.is_drum, name=inst.name or ""
        )
        for note in inst.notes:
            new_inst.notes.append(
                pretty_midi.Note(
                    velocity=note.velocity,
                    pitch=note.pitch,
                    start=note.start,
                    end=note.end,
                )
            )
        if new_inst.notes:
            out.instruments.append(new_inst)

    for inst in cont_mid.instruments:
        new_inst = pretty_midi.Instrument(
            program=inst.program, is_drum=inst.is_drum, name=inst.name or ""
        )
        for note in inst.notes:
            new_inst.notes.append(
                pretty_midi.Note(
                    velocity=note.velocity,
                    pitch=note.pitch,
                    start=note.start + offset,
                    end=note.end + offset,
                )
            )
        if new_inst.notes:
            out.instruments.append(new_inst)

    if not out.instruments:
        out = cont_mid

    if output_path is None:
        output_path = str(Path(input_path).parent / "preview_merge.mid")

    out.write(output_path)
    return output_path
