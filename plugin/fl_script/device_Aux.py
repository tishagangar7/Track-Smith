"""
Aux — FL Studio MIDI Controller Script
=======================================
Place this file at:
  ~/Documents/Image-Line/FL Studio/Settings/Hardware/Aux/device_Aux.py

Then in FL Studio:
  Options → MIDI Settings → select "Aux" as Controller for the IAC input → Enable

What this script does:
  - Polls ~/aux_fl_command.json every idle tick
  - When a command arrives: sets tempo hint, arms a 4-bar record loop,
    and injects notes at the right beat via channels.midiNoteOn()
  - Handles melodic notes on channel rack slot 0, drums on slot 1
"""

import channels
import transport
import patterns
import ui
import time
import json
import os

# ── config ────────────────────────────────────────────────────────────────────
COMMAND_FILE  = os.path.expanduser("~/aux_fl_command.json")
MELODIC_SLOT  = 0   # channel rack index for harmony/melody
DRUM_SLOT     = 1   # channel rack index for drums

# ── state ─────────────────────────────────────────────────────────────────────
_notes        = []        # sorted list of note dicts from the command
_tempo        = 120.0
_bars         = 4
_loop_beats   = 16.0      # bars × 4
_start_time   = None      # wall-clock time when playback started
_active       = {}        # pitch -> (slot, off_time_sec)
_fired        = set()     # (beat_rounded, pitch, slot) already triggered this loop
_running      = False


def OnInit():
    ui.setHintMsg("Aux: loaded — waiting for ghost produce command...")


def OnDeInit():
    global _running
    _running = False
    ui.setHintMsg("")


def OnIdle():
    global _notes, _tempo, _bars, _loop_beats, _start_time, _active, _fired, _running

    # ── check for new command ─────────────────────────────────────────────────
    if os.path.exists(COMMAND_FILE):
        try:
            with open(COMMAND_FILE) as f:
                cmd = json.load(f)
            os.remove(COMMAND_FILE)
        except Exception:
            return

        _notes      = sorted(cmd.get("notes", []), key=lambda n: n["beat"])
        _tempo      = float(cmd.get("tempo", 120))
        _bars       = int(cmd.get("bars", 4))
        _loop_beats = float(_bars * 4)
        _active     = {}
        _fired      = set()
        _running    = True
        _start_time = time.time()

        ui.setHintMsg(
            f"Aux: ghost producing — {len(_notes)} notes · {_bars} bars · {_tempo:.0f} BPM"
        )

        # Put FL in record mode so notes land in the current pattern
        if not transport.isRecording():
            transport.record()

        return  # let the first note tick fire next idle

    if not _running or _start_time is None:
        return

    # ── tick: calculate current beat position ─────────────────────────────────
    spb          = 60.0 / _tempo
    elapsed      = time.time() - _start_time
    current_beat = elapsed / spb

    # ── stop after one full loop ───────────────────────────────────────────────
    if current_beat >= _loop_beats:
        _running    = False
        _start_time = None
        # release any stuck notes
        for pitch, (slot, _) in list(_active.items()):
            channels.midiNoteOn(slot, pitch, 0)
        _active.clear()
        transport.stop()
        ui.setHintMsg("Aux: done — pattern ready in piano roll")
        return

    # ── release notes whose duration has expired ───────────────────────────────
    now = time.time()
    for pitch, (slot, off_t) in list(_active.items()):
        if now >= off_t:
            channels.midiNoteOn(slot, pitch, 0)
            del _active[pitch]

    # ── fire notes whose start beat we have passed ────────────────────────────
    for note in _notes:
        beat = note["beat"]
        if beat > current_beat:
            break  # sorted, so nothing later can be due

        slot     = DRUM_SLOT if note.get("channel", 0) == 9 else MELODIC_SLOT
        key      = (round(beat, 2), note["pitch"], slot)

        if key in _fired:
            continue

        pitch    = note["pitch"]
        vel      = note.get("velocity", 80)
        dur_sec  = note.get("duration_beats", 0.25) * spb

        channels.midiNoteOn(slot, pitch, vel)
        _fired.add(key)
        _active[pitch] = (slot, now + dur_sec)


def OnMidiMsg(event):
    event.handled = False  # pass all MIDI through so IAC notes still work
