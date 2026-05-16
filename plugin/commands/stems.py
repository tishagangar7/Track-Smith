from pathlib import Path

from agent.skills.audio_gen import AudioServerOfflineError, separate_stems

_AUDIO_EXTS = {".wav", ".mp3", ".aiff", ".flac", ".ogg", ".m4a"}


def run(file_path: str | None, output_dir: str = "") -> dict:
    if not file_path:
        return {"type": "error", "message": "No file loaded — drop an audio file first"}

    path = Path(file_path)
    if path.suffix.lower() not in _AUDIO_EXTS:
        return {
            "type": "error",
            "message": (
                f"Stem separation needs an audio file (WAV/MP3/FLAC), got {path.suffix}.\n"
                "Run /fill first to generate audio, then click Separate Stems."
            ),
        }

    stems_dir = str(Path(output_dir) / "stems" / path.stem)

    try:
        stems = separate_stems(str(path), stems_dir)
    except AudioServerOfflineError as e:
        return {
            "type": "error",
            "message": (
                f"Audio server offline: {e}\n"
                "Start it on DGX: bash run_audio_server.sh"
            ),
        }

    lines = [f"Separated {len(stems)} stems from {path.name}:", ""]
    for name, fpath in sorted(stems.items()):
        lines.append(f"  {name:12s}  {Path(fpath).name}")

    return {
        "type": "stems",
        "message": "\n".join(lines),
        "stems": stems,
        "stems_dir": stems_dir,
    }
