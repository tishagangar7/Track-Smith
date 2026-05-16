"""Export / download helpers for generated outputs."""

import shutil
from pathlib import Path

from plugin.midi_merge import merge_input_and_continuation


def export_continuation(src: str, dest: str) -> str:
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return dest


def export_merged_preview(
    input_path: str,
    continuation_path: str,
    dest: str,
    input_type: str = "midi",
) -> str:
    """Write merged MIDI (MIDI input only). For MP3 input, exports fill + copies original path hint."""
    if input_type == "audio":
        shutil.copy2(continuation_path, dest)
        return dest
    merged = merge_input_and_continuation(input_path, continuation_path, dest)
    return merged
