"""Beat grid detection from audio — aligns generated fills to the groove."""

import logging

import numpy as np

logger = logging.getLogger(__name__)


def analyze_beat_grid(y, sr: int, tempo: float) -> dict:
    """
    Detect beat times and groove hints from audio waveform.
    Returns dict with beat_times_sec, swing_hint, bar_count.
    """
    import librosa

    out = {
        "beat_times_sec": [],
        "downbeat_times_sec": [],
        "swing_hint": "straight",
        "bars_estimate": 4,
    }
    try:
        tempo_est, beat_frames = librosa.beat.beat_track(y=y, sr=sr, bpm=tempo)
        if hasattr(tempo_est, "__len__"):
            tempo_est = float(tempo_est[0]) if len(tempo_est) else tempo
        else:
            tempo_est = float(tempo_est)
        beat_times = librosa.frames_to_time(beat_frames, sr=sr)
        out["beat_times_sec"] = [round(float(t), 3) for t in beat_times[:32]]
        # Every 4th beat ≈ downbeat
        out["downbeat_times_sec"] = [
            round(float(t), 3) for i, t in enumerate(beat_times) if i % 4 == 0
        ][:8]
        duration = len(y) / sr
        spb = 60.0 / max(tempo_est, 1.0)
        out["bars_estimate"] = max(1, int(duration / (4 * spb)))
    except Exception as e:
        logger.debug(f"beat grid detection failed: {e}")

    try:
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        onsets = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr, units="time")
        if len(onsets) >= 6:
            gaps = np.diff(onsets[:12])
            if len(gaps) >= 2:
                ratio = float(np.mean(gaps[1::2])) / max(float(np.mean(gaps[0::2])), 0.01)
                if ratio > 1.15:
                    out["swing_hint"] = "swung"
    except Exception:
        pass

    return out


def tempo_from_beat_times(beat_grid: dict) -> float | None:
    """Median BPM from detected beat times (often more stable than librosa headline tempo)."""
    times = beat_grid.get("beat_times_sec") or []
    if len(times) < 4:
        return None
    gaps = np.diff(np.array(times, dtype=float))
    gaps = gaps[(gaps > 0.25) & (gaps < 1.25)]
    if len(gaps) < 2:
        return None
    return float(round(60.0 / float(np.median(gaps)), 1))
