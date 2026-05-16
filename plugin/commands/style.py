def run(artist: str) -> dict:
    if not artist.strip():
        return {"type": "error", "message": "Usage: /style <artist>  e.g. /style Burial"}
    return {
        "type": "style",
        "message": f"Style locked to: {artist.strip()}\nThis will influence /fill, /suggest, and /mix.",
        "style": artist.strip(),
    }
