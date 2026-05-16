"""
Aux — FL Studio Script Pad importer

Paste this into FL Studio's Script Pad (Tools → Script → Score, or Alt+Shift+S).
Click Run after the companion app writes pending.mid.

IMPORTANT: Update PENDING_MID to the absolute path shown in the companion app
           (click "FL Script Setup" button → path is pre-filled for you).
"""

import flp
import os

# The companion app fills this in automatically via "FL Script Setup"
PENDING_MID = r"<UPDATE_THIS_PATH>"

# ──────────────────────────────────────────────────────────────────────────────

if not os.path.exists(PENDING_MID):
    raise FileNotFoundError(
        f"pending.mid not found at:\n  {PENDING_MID}\n\n"
        "Click '→ Piano Roll' in the Aux app first, then run this script."
    )

try:
    import mido
except ImportError:
    raise ImportError(
        "mido is not installed in FL Studio's Python environment.\n"
        "Open FL Studio's script console and run: import pip; pip.main(['install', 'mido'])"
    )

mid = mido.MidiFile(PENDING_MID)
ticks_per_beat = mid.ticks_per_beat
ppq = flp.score.PPQ  # FL Studio's pulses per quarter note

flp.score.clear(True)  # clear existing notes before inserting

imported = 0
for track in mid.tracks:
    tick = 0
    active = {}
    for msg in track:
        tick += msg.time
        fl_tick = int(tick * ppq / ticks_per_beat)

        if msg.type == "note_on" and msg.velocity > 0:
            active[msg.note] = (fl_tick, msg.velocity)

        elif msg.type in ("note_off", "note_on") and msg.note in active:
            start, vel = active.pop(msg.note)
            length = max(1, fl_tick - start)

            n = flp.Note()
            n.number = msg.note
            n.time = start
            n.length = length
            n.velocity = round(vel / 127, 3)
            flp.score.addNote(n)
            imported += 1

# clean up — pending.mid is consumed
os.remove(PENDING_MID)

print(f"Aux: imported {imported} notes into piano roll.")
