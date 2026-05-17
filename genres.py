"""Shared genre/sub-genre mapping used by crawl_musicbrainz.py and enrich_discogs.py."""

GENRE_MAP: dict[str, list[str]] = {
    "rock": [
        "classic rock",
        "hard rock",
        "alternative rock",
        "indie rock",
        "progressive rock",
        "psychedelic rock",
        "blues rock",
        "garage rock",
        "grunge",
        "glam rock",
        "southern rock",
        "folk rock",
        "new wave",
        "post-rock",
        "shoegaze",
        "britpop",
        "rockabilly",
        "math rock",
    ],
    "electronic": ["house", "techno", "ambient", "synth-pop", "electro"],
    "hip-hop":    ["hip hop"],
    "jazz":       ["jazz"],
    "metal":      ["heavy metal", "doom metal", "black metal", "thrash metal"],
    "pop":        ["pop"],
    "soul-funk-rnb": ["soul", "funk", "r&b"],
    "punk":       ["punk", "post-punk"],
    "reggae":     ["reggae"],
}

SUB_TO_GENRE: dict[str, str] = {
    sub: genre for genre, subs in GENRE_MAP.items() for sub in subs
}
