GENRE_PRESETS: dict[str, str] = {
    "lofi":     "lo-fi hip hop: dusty samples, vinyl crackle, slow 70-90 BPM, jazz chords, mellow melodies",
    "808s":     "trap 808s: heavy sub-bass 808 slides, hi-hat rolls, sparse kick, dark minor keys, 130-140 BPM",
    "r&b":      "contemporary R&B: lush chords, soulful melodies, syncopated grooves, smooth bass, 70-90 BPM",
    "pop":      "modern pop: catchy hooks, bright synths, four-on-the-floor or electronic drums, polished production",
    "rap":      "hip hop rap: punchy 808 kick, crisp snare, chopped samples, boom-bap or trap energy, 85-140 BPM",
    "edm":      "EDM: driving four-on-the-floor kick, build-drop structure, supersaws, sidechained bass, 128 BPM",
    "drill":    "UK/Chicago drill: menacing minor melodies, sliding 808s, offbeat hi-hats, dark atmosphere, 140-150 BPM",
    "soul":     "classic soul: warm organ, live drums, gospel-influenced vocals implied, rich horn stabs",
    "jazz":     "jazz: extended chords (7ths, 9ths, 13ths), walking bass, brushed drums, improvisational feel",
    "ambient":  "ambient: slow evolving pads, minimal percussion, spacious reverb, long note durations, meditative",
    "afrobeats": "afrobeats: polyrhythmic percussion, talking drum patterns, bright guitar, 100-110 BPM, danceable",
    "phonk":    "phonk: Memphis rap sample chops, faint choir, distorted 808, triple hi-hat bounce, 130-140 BPM",
}

ARTIST_PRESETS: dict[str, str] = {
    # rap / hip hop
    "drake":          "Drake: melodic rap-singing, minor key piano loops, 808 bass, emotional introspective hooks, Toronto sound",
    "kendrick lamar": "Kendrick Lamar: complex rhythmic flow, jazz-influenced samples, dense layered production, West Coast feel",
    "travis scott":   "Travis Scott: psychedelic trap, pitch-shifted ad-libs, heavy reverb, distorted 808s, astroworld atmosphere",
    "j. cole":        "J. Cole: boom-bap inspired, soulful samples, introspective piano chords, clean 808 kick, lyrical cadence",
    "21 savage":      "21 Savage: minimalist trap, cold ominous pads, deep 808, sparse melodies, Atlanta drill influence",
    "future":         "Future: melodic auto-tune, dark trap pads, cascading hi-hats, heavy 808 sub-bass, hypnotic repetition",
    # pop
    "taylor swift":   "Taylor Swift: anthemic pop, layered synths and guitars, major-key emotional builds, confessional storytelling arc",
    "billie eilish":  "Billie Eilish: whisper-pop, dark minimal production, sub-bass rumble, ASMR-textured layers, intimate atmosphere",
    "the weeknd":     "The Weeknd: dark synth-wave R&B, 80s-influenced pads, minor keys, cinematic builds, breathy melodic hooks",
    "dua lipa":       "Dua Lipa: disco-pop, four-on-the-floor groove, punchy bass, bright synth leads, danceable retro energy",
    "ariana grande":  "Ariana Grande: trap-influenced pop, lush reverb pads, glittery synths, high-register melodic runs, R&B feel",
    "olivia rodrigo": "Olivia Rodrigo: pop-rock, distorted power chords, raw emotional dynamics, piano-driven verses, angsty energy",
    # r&b / soul
    "frank ocean":    "Frank Ocean: neo-soul, lush jazz chords, lo-fi textures, unconventional song structure, emotional intimacy",
    "sza":            "SZA: alternative R&B, organic live instruments, airy pads, complex chord voicings, confessional vulnerability",
    "daniel caesar":  "Daniel Caesar: gospel-influenced R&B, warm acoustic guitar, mellow drum grooves, rich harmonic progressions",
    # electronic
    "daft punk":      "Daft Punk: French house, filtered disco samples, vocoder hooks, tight funky bass, robotic rhythmic groove",
    "burial":         "Burial: UK garage, halftime broken beats, crackling vinyl noise, sub-bass weight, melancholic pitch-shifted vocals",
    "aphex twin":     "Aphex Twin: IDM, complex polyrhythmic drums, acid synth lines, lush ambient pads, unsettling melodic beauty",
    "fred again":     "Fred Again: emotional UK house, chopped vocal samples, rolling 4/4 groove, euphoric builds, rave energy",
    # lofi / chill
    "nujabes":        "Nujabes: lo-fi hip hop, jazzy chord samples, boom-bap drums, warm melancholic melodies, Japanese aesthetic",
    "j dilla":        "J Dilla: soulful boom-bap, deliberately swinging off-grid drums, lush soul samples, Detroit warmth",
}


def resolve(raw: str) -> str:
    """Return enriched description for a preset, or the raw string if not found."""
    key = raw.strip().lower()
    return GENRE_PRESETS.get(key) or ARTIST_PRESETS.get(key) or raw.strip()


def all_labels() -> list[str]:
    """Return display labels for all presets (genres first, then artists)."""
    genres = list(GENRE_PRESETS.keys())
    artists = [k.title() for k in ARTIST_PRESETS.keys()]
    return genres + artists
