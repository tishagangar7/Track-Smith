from agent.skills.style_presets import resolve, GENRE_PRESETS, ARTIST_PRESETS


def run(artist: str) -> dict:
    if not artist.strip():
        genres = ", ".join(GENRE_PRESETS.keys())
        artists = ", ".join(k.title() for k in list(ARTIST_PRESETS.keys())[:6]) + ", ..."
        return {
            "type": "error",
            "message": (
                "Usage: /style <artist or genre>\n"
                f"Genres: {genres}\n"
                f"Artists: {artists}"
            ),
        }
    enriched = resolve(artist)
    label = artist.strip().title() if enriched != artist.strip() else artist.strip()
    return {
        "type": "style",
        "message": f"Style locked to: {label}\n{enriched}",
        "style": enriched,
    }
