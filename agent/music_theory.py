"""Key/chord helpers shared by analyzers and MIDI generation."""

import re

PITCH_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLAT_TO_SHARP = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#", "Cb": "B", "Fb": "E"}

ROOT_TO_PC = {
    "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5,
    "F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11,
}

NATURAL_MINOR_QUALITIES = ["m", "dim", "M", "m", "m", "M", "M"]
MAJOR_QUALITIES = ["M", "m", "m", "M", "M", "m", "dim"]


def normalize_root(name: str) -> str:
    name = name.strip()
    if name in FLAT_TO_SHARP:
        return FLAT_TO_SHARP[name]
    return name


def parse_key(key_str: str) -> tuple[int, bool]:
    """Return (root pitch class 0-11, is_minor)."""
    if not key_str or key_str == "Unknown":
        return 9, True  # A minor default
    s = key_str.strip()
    m = re.match(r"^([A-G][#b]?)\s*(m|min|minor|maj|major)?$", s, re.I)
    if not m:
        m = re.match(r"^([A-G][#b]?)", s)
    if not m:
        return 9, True
    root = normalize_root(m.group(1))
    pc = ROOT_TO_PC.get(root, 9)
    qual = (m.group(2) or "").lower() if m.lastindex and m.lastindex >= 2 else ""
    is_minor = qual in ("m", "min", "minor") or "minor" in s.lower()
    is_major = qual in ("maj", "major") or ("major" in s.lower() and "minor" not in s.lower())
    if is_major:
        is_minor = False
    elif not qual and "minor" in s.lower():
        is_minor = True
    return pc, is_minor


def pc_to_root_name(pc: int, prefer_flats: bool = False) -> str:
    names_sharp = PITCH_NAMES
    names_flat = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
    return (names_flat if prefer_flats else names_sharp)[pc % 12]


def chord_label(root_pc: int, quality: str) -> str:
    root = pc_to_root_name(root_pc, prefer_flats=True)
    if quality == "m":
        return f"{root}m"
    if quality == "dim":
        return f"{root}dim"
    return root


def diatonic_progression(key_str: str, length: int = 4) -> list[str]:
    """Common pop/hip-hop progression in the detected key."""
    root_pc, is_minor = parse_key(key_str)
    if is_minor:
        # i – VI – VII – iv (e.g. Am – F – G – Dm)
        degrees = [0, 5, 6, 3, 4, 0]
        quals = NATURAL_MINOR_QUALITIES
    else:
        # I – V – vi – IV
        degrees = [0, 4, 5, 3, 0, 4]
        quals = MAJOR_QUALITIES
    chords = []
    for deg in degrees:
        r = (root_pc + deg) % 12
        q = quals[deg]
        label = chord_label(r, q)
        chords.append(label)
        if len(chords) >= length:
            break
    return chords


def scale_pitch_classes(key_str: str) -> list[int]:
    root_pc, is_minor = parse_key(key_str)
    if is_minor:
        intervals = [0, 2, 3, 5, 7, 8, 10]
    else:
        intervals = [0, 2, 4, 5, 7, 9, 11]
    return [(root_pc + i) % 12 for i in intervals]


def chord_to_pitches(chord_name: str, octave: int = 4) -> list[int]:
    import re
    m = re.match(r"^([A-G][#b]?)(m|maj|dim|aug)?$", chord_name.strip())
    if not m:
        return [60, 64, 67]
    root = normalize_root(m.group(1))
    root_pc = ROOT_TO_PC.get(root, 0)
    qual = (m.group(2) or "").lower()
    if qual in ("m", "min"):
        intervals = [0, 3, 7]
    elif qual == "dim":
        intervals = [0, 3, 6]
    else:
        intervals = [0, 4, 7]
    base = (octave + 1) * 12
    return [base + root_pc + i for i in intervals]


def melody_pitches_for_key(key_str: str, octave: int = 4) -> list[int]:
    root_pc, is_minor = parse_key(key_str)
    scale = scale_pitch_classes(key_str)
    base = (octave + 1) * 12
    # pentatonic-ish: root, 3rd, 4th, 5th, 7th
    degrees = [0, 2, 3, 4, 6] if is_minor else [0, 2, 4, 5, 6]
    return [base + scale[d % len(scale)] for d in degrees]
