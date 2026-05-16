"""Read BPM/key from MP3/WAV tags (beat producer metadata)."""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_KEY_RE = re.compile(
    r"key\s*[=:]\s*([A-G][#b]?\s*(?:m(?:in(?:or)?)?|maj(?:or)?)?)",
    re.I,
)
_BPM_RE = re.compile(r"bpm\s*[=:]\s*(\d{2,3})", re.I)


def _normalize_key(raw: str) -> str:
    raw = raw.strip()
    m = re.match(r"^([A-G][#b]?)\s*(m(?:in(?:or)?)?|maj(?:or)?)?$", raw, re.I)
    if not m:
        return raw
    root = m.group(1)
    qual = (m.group(2) or "").lower()
    if qual.startswith("m"):
        return f"{root} minor"
    if qual.startswith("maj"):
        return f"{root} major"
    return root


def _scan_text_for_tags(text: str) -> dict:
    out: dict = {}
    if not text:
        return out
    bpm_m = _BPM_RE.search(text)
    if bpm_m:
        bpm = int(bpm_m.group(1))
        if 40 <= bpm <= 220:
            out["tempo"] = float(bpm)
    key_m = _KEY_RE.search(text)
    if key_m:
        out["key"] = _normalize_key(key_m.group(1))
    return out


def _read_tags_ffprobe(file_path: str) -> dict:
    """Fallback: scan ffprobe metadata dump for Key/BPM text."""
    import subprocess

    try:
        proc = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-show_entries", "format_tags=comment:description:synopsis",
                "-of", "default=noprint_wrappers=1:nokey=1",
                file_path,
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        blob = proc.stdout or ""
        return _scan_text_for_tags(blob)
    except Exception as e:
        logger.debug(f"ffprobe tag read failed: {e}")
        return {}


def read_embedded_tags(file_path: str) -> dict:
    """
    Extract tempo/key from ID3/Vorbis comments.
    Many beat stores embed 'Key = Ab min' and 'BPM = 80' in description.
    """
    result: dict = {}
    path = Path(file_path)

    result.update(_read_tags_ffprobe(file_path))

    try:
        from mutagen import File as MutagenFile

        audio = MutagenFile(path)
        if audio is None:
            return result
        texts: list[str] = []
        if getattr(audio, "tags", None):
            for key in (
                "TIT2", "TPE1", "TXXX:KEY", "TBPM", "TKEY",
                "comment", "description", "COMM::eng", "TXXX:BPM",
            ):
                try:
                    val = audio.tags.get(key)
                    if val is not None:
                        texts.append(str(val))
                except Exception:
                    pass
            for vals in audio.tags.values():
                if isinstance(vals, (list, tuple)):
                    for v in vals:
                        texts.append(str(v))
                else:
                    texts.append(str(vals))
        for text in texts:
            result.update(_scan_text_for_tags(text))
        # TBPM numeric tag
        try:
            bpm = audio.tags.get("TBPM")
            if bpm:
                result.setdefault("tempo", float(str(bpm[0] if isinstance(bpm, list) else bpm)))
        except Exception:
            pass
    except ImportError:
        logger.debug("mutagen not installed — tag parsing uses filename only")
    except Exception as e:
        logger.debug(f"mutagen read failed: {e}")

    # Filename hints: "80bpm Ab minor"
    name = path.stem
    result.update(_scan_text_for_tags(name))

    if result:
        logger.info(f"Embedded tags from {path.name}: {result}")
    return result
