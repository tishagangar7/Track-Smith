"""
Audio Analyzer — extracts tempo, key estimate, energy, and duration
from MP3/WAV files using librosa.
"""

import logging
import numpy as np

logger = logging.getLogger(__name__)

PITCH_NAMES = ["C", "C#", "D", "D#", "E", "F",
               "F#", "G", "G#", "A", "A#", "B"]

MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09,
                           2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53,
                           2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

_MAJOR_TRIAD = [0, 4, 7]
_MINOR_TRIAD = [0, 3, 7]


def _key_from_chroma(chroma: np.ndarray, minor_bias: float = 0.06) -> str:
    """Krumhansl-Schmuckler with a slight minor bias for hip-hop/trap."""
    if chroma.sum() == 0:
        return "Unknown"
    chroma = chroma / chroma.sum()
    best_score = -np.inf
    best_key = "C major"
    for i in range(12):
        rotated = np.roll(chroma, -i)
        major_corr = float(np.corrcoef(rotated, MAJOR_PROFILE)[0, 1])
        minor_corr = float(np.corrcoef(rotated, MINOR_PROFILE)[0, 1]) + minor_bias
        if minor_corr >= major_corr and minor_corr > best_score:
            best_score = minor_corr
            best_key = f"{PITCH_NAMES[i]} minor"
        elif major_corr > best_score:
            best_score = major_corr
            best_key = f"{PITCH_NAMES[i]} major"
    return best_key


def _chord_from_chroma_segment(segment: np.ndarray) -> str:
    """Template matching against major/minor triads."""
    if segment.sum() == 0:
        return PITCH_NAMES[0]
    seg = segment / segment.sum()
    best_name = PITCH_NAMES[int(np.argmax(seg))]
    best_score = -1.0
    for root in range(12):
        for suffix, intervals in [("", _MAJOR_TRIAD), ("m", _MINOR_TRIAD)]:
            score = float(sum(seg[(root + i) % 12] for i in intervals))
            if score > best_score:
                best_score = score
                best_name = f"{PITCH_NAMES[root]}{suffix}"
    return best_name


def _chord_progression_from_chroma(chroma: np.ndarray, num_chords: int = 4) -> list:
    if chroma.size == 0 or chroma.sum() == 0:
        return []
    frames = chroma.shape[1] if chroma.ndim > 1 else 1
    if frames < num_chords:
        seg = chroma.mean(axis=1) if chroma.ndim > 1 else chroma
        return [_chord_from_chroma_segment(seg)]
    step = max(1, frames // num_chords)
    chords = []
    for i in range(num_chords):
        start = i * step
        end = min((i + 1) * step, frames)
        segment = chroma[:, start:end].mean(axis=1) if chroma.ndim > 1 else chroma
        chords.append(_chord_from_chroma_segment(segment))
    return chords


def _detect_tempo(y: np.ndarray, sr: int) -> float:
    import librosa

    raw = []

    # Method 1: standard beat tracker
    try:
        t, _ = librosa.beat.beat_track(y=y, sr=sr)
        raw.append(float(t[0]) if hasattr(t, "__len__") else float(t))
    except Exception:
        pass

    # Method 2: tempogram-based (more robust against complex rhythms)
    try:
        onset_env = librosa.onset.onset_strength(y=y, sr=sr, aggregate=np.median)
        t2 = librosa.feature.rhythm.tempo(onset_envelope=onset_env, sr=sr)
        raw.append(float(t2[0]) if hasattr(t2, "__len__") else float(t2))
    except Exception:
        pass

    # Method 3: percussive component only (helps for trap hi-hats)
    try:
        _, y_perc = librosa.effects.hpss(y)
        t3, _ = librosa.beat.beat_track(y=y_perc, sr=sr)
        raw.append(float(t3[0]) if hasattr(t3, "__len__") else float(t3))
    except Exception:
        pass

    if not raw:
        return 120.0

    # Expand with harmonic ratios — trap hi-hats often cause 4/3x detection
    # e.g. true 80 BPM detected as ~106 (80 × 4/3)
    # Use a simple range filter (no looping) so ratios don't collapse back to the original
    expanded = []
    for t in raw:
        for ratio in (1.0, 0.5, 2.0, 0.75, 4/3, 3/4, 0.25, 4.0):
            expanded.append(t * ratio)

    normalised = [round(t, 1) for t in expanded if 55 <= t <= 175]

    if not normalised:
        return 120.0

    # Cluster within 5 BPM and pick largest cluster median
    normalised.sort()
    clusters: list[list[float]] = [[normalised[0]]]
    for v in normalised[1:]:
        if v - clusters[-1][-1] <= 5:
            clusters[-1].append(v)
        else:
            clusters.append([v])
    biggest = max(clusters, key=len)
    tempo = float(np.median(biggest))

    return float(round(max(60.0, min(175.0, tempo)), 1))


def analyze_audio(file_path: str) -> dict:
    """Full analysis of an audio file for Nemotron / slash commands."""
    import librosa
    from agent.skills.audio_metadata import read_embedded_tags
    from agent.music_theory import diatonic_progression

    logger.info(f"Analyzing audio: {file_path}")
    embedded = read_embedded_tags(file_path)

    try:
        y, sr = librosa.load(file_path, sr=None, mono=True)
    except Exception as e:
        raise ValueError(
            f"Could not load audio: {e}\n"
            "Install ffmpeg for MP3 support: brew install ffmpeg"
        ) from e

    duration = float(librosa.get_duration(y=y, sr=sr))

    # Tempo
    tempo = _detect_tempo(y, sr)
    if embedded.get("tempo"):
        tempo = float(embedded["tempo"])
        logger.info(f"Using embedded BPM: {tempo}")

    # Harmonic separation — removes drums/808s that pollute key/chord detection
    try:
        y_harm = librosa.effects.harmonic(y, margin=4)
    except Exception:
        y_harm = y

    # Key — chroma_cens on harmonic component is much more stable than raw chroma_cqt
    chroma = librosa.feature.chroma_cens(y=y_harm, sr=sr)
    chroma_mean = chroma.mean(axis=1)
    key = _key_from_chroma(chroma_mean)
    chord_progression = _chord_progression_from_chroma(chroma)

    if embedded.get("key"):
        key = embedded["key"]
        chord_progression = diatonic_progression(key)
        logger.info(f"Using embedded key: {key} → chords {chord_progression}")

    rms = librosa.feature.rms(y=y)[0]
    energy = float(round(min(1.0, np.mean(rms) * 4.0), 3))

    centroid = librosa.feature.spectral_centroid(y=y, sr=sr)[0]
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    onset_density = float(
        len(librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr)) / max(duration, 0.1)
    )

    audio_features = {
        "spectral_centroid_mean": float(round(np.mean(centroid), 1)),
        "onset_density": round(onset_density, 2),
        "brightness": "bright" if np.mean(centroid) > 2500 else "warm",
    }

    result = {
        "source_type": "audio",
        "tempo": tempo,
        "key": key,
        "duration": round(duration, 2),
        "instruments": ["audio"],
        "total_notes": 0,
        "has_notes": False,
        "energy": energy,
        "chord_progression": chord_progression,
        "num_tracks": 1,
        "note_events": [],
        "pitch_classes": [],
        "audio_features": audio_features,
    }

    logger.info(f"Audio analysis: {result}")
    return result
