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


def _key_from_chroma(chroma: np.ndarray) -> str:
    if chroma.sum() == 0:
        return "Unknown"
    chroma = chroma / chroma.sum()
    best_score = -np.inf
    best_key = "C major"
    for i in range(12):
        rotated = np.roll(chroma, -i)
        major_corr = float(np.corrcoef(rotated, MAJOR_PROFILE)[0, 1])
        minor_corr = float(np.corrcoef(rotated, MINOR_PROFILE)[0, 1])
        if minor_corr >= major_corr and minor_corr > best_score:
            best_score = minor_corr
            best_key = f"{PITCH_NAMES[i]} minor"
        elif major_corr > best_score:
            best_score = major_corr
            best_key = f"{PITCH_NAMES[i]} major"
    return best_key


def _chord_progression_from_chroma(chroma: np.ndarray, num_chords: int = 4) -> list:
    if chroma.size == 0 or chroma.sum() == 0:
        return []
    frames = chroma.shape[1] if chroma.ndim > 1 else 1
    if frames < num_chords:
        return [_key_from_chroma(chroma if chroma.ndim == 1 else chroma.mean(axis=1)).split()[0]]
    step = max(1, frames // num_chords)
    chords = []
    for i in range(num_chords):
        start = i * step
        end = min((i + 1) * step, frames)
        segment = chroma[:, start:end].mean(axis=1) if chroma.ndim > 1 else chroma
        if segment.sum() > 0:
            chords.append(PITCH_NAMES[int(np.argmax(segment))])
    return chords


def _refine_tempo_candidates(y, sr, rough: float) -> float:
    """Pick the most likely BPM for hip-hop/pop (often 70–100 or half-time)."""
    import librosa

    candidates = {rough}
    for factor in (0.5, 2.0, 1.5, 0.75):
        candidates.add(rough * factor)
    # Common producer tempos near detected value
    for target in (80, 90, 100, 70, 140, 160):
        if abs(target - rough) < 18:
            candidates.add(float(target))

    best, best_score = rough, -1.0
    try:
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        for cand in candidates:
            if not (40 <= cand <= 200):
                continue
            score = 0.0
            # Prefer standard beat tempos
            if 68 <= cand <= 110:
                score += 2.0
            if cand % 5 == 0:
                score += 0.5
            # Closer to librosa estimate is slightly preferred
            score -= abs(cand - rough) / 40.0
            if score > best_score:
                best_score, best = score, cand
    except Exception:
        pass
    return float(round(best, 1))


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

    tempo = 120.0
    try:
        tempo_est, _ = librosa.beat.beat_track(y=y, sr=sr)
        if hasattr(tempo_est, "__len__"):
            tempo = float(tempo_est[0]) if len(tempo_est) else 120.0
        else:
            tempo = float(tempo_est)
        # librosa often returns half/double tempo — pick sensible octave
        while tempo < 70 and tempo > 0:
            tempo *= 2
        while tempo > 180:
            tempo /= 2
    except Exception:
        pass
    tempo = _refine_tempo_candidates(y, sr, tempo)
    tempo = float(round(max(40.0, min(300.0, tempo)), 1))
    if embedded.get("tempo"):
        tempo = float(embedded["tempo"])
        logger.info(f"Using embedded BPM: {tempo}")

    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
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
    onset_density = float(len(librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr)) / max(duration, 0.1))

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
