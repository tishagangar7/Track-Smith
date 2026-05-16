"""
FL Studio integration via IAC Driver.

Primary path : write ~/aux_fl_command.json → device_Aux.py picks it up
               and ghost-produces a structured 4-bar pattern.
Fallback path: raw MIDI stream over IAC (used if FL script not installed).
"""

import mido
from plugin.fl_command import write_command

DEFAULT_PORT = "IAC Driver TrackSmith"


def list_ports() -> list[str]:
    try:
        return [p for p in mido.get_output_names() if "IAC" in p]
    except Exception:
        return []


def send_command(midi_path: str) -> str:
    """Write the FL command JSON. Returns the path written."""
    return write_command(midi_path)


def send_to_iac(midi_path: str, port_name: str = DEFAULT_PORT) -> None:
    """Fallback: stream raw MIDI over IAC (real-time, no FL script needed)."""
    mid = mido.MidiFile(midi_path)
    with mido.open_output(port_name) as port:
        for msg in mid.play():
            port.send(msg)
