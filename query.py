#!/usr/bin/env python3
"""Phase 3: Query CLI for enriched_data.json.

Commands:
  python query.py top-genres   --n 10
  python query.py top-artists  --genre rock --n 20
  python query.py top-albums   --genre rock [--sub-genre "indie rock"] --n 20
  python query.py stats
"""

import argparse
import json
import sys
from pathlib import Path

INPUT_FILE = Path("enriched_data.json")


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data() -> list[dict]:
    if not INPUT_FILE.exists():
        print(
            f"Error: {INPUT_FILE} not found. Run enrich_discogs.py first.",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        return json.loads(INPUT_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"Error: could not parse {INPUT_FILE}: {exc}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Table renderer (stdlib only)
# ---------------------------------------------------------------------------

def print_table(headers: list[str], rows: list[list]) -> None:
    if not rows:
        print("No data.")
        return

    col_widths = [
        max(len(str(headers[i])), max(len(str(row[i])) for row in rows))
        for i in range(len(headers))
    ]

    sep = "+" + "+".join("-" * (w + 2) for w in col_widths) + "+"
    fmt = "|" + "|".join(f" {{:<{w}}} " for w in col_widths) + "|"

    print(sep)
    print(fmt.format(*[str(h) for h in headers]))
    print(sep)
    for row in rows:
        print(fmt.format(*[str(v) for v in row]))
    print(sep)
    print(f"{len(rows)} row(s)")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_top_genres(data: list[dict], n: int) -> None:
    """Genres ranked by average album review count (albums with reviews > 0)."""
    from collections import defaultdict

    genre_reviews: dict[str, list[int]] = defaultdict(list)
    for artist in data:
        genre = artist.get("genre", "unknown")
        for album in artist.get("albums", []):
            reviews = album.get("discogs_reviews")
            if reviews and reviews > 0:
                genre_reviews[genre].append(reviews)

    ranked = sorted(
        [
            (genre, len(counts), round(sum(counts) / len(counts), 1))
            for genre, counts in genre_reviews.items()
        ],
        key=lambda x: x[2],
        reverse=True,
    )[:n]

    print_table(
        ["#", "Genre", "Albums (w/ reviews)", "Avg Reviews"],
        [[i + 1, g, c, avg] for i, (g, c, avg) in enumerate(ranked)],
    )


def cmd_top_artists(data: list[dict], genre: str, n: int) -> None:
    """Artists in genre ranked by total reviews across all albums."""
    rows = []
    for artist in data:
        if artist.get("genre") != genre:
            continue
        total = sum(
            a.get("discogs_reviews") or 0
            for a in artist.get("albums", [])
        )
        album_count = len(artist.get("albums", []))
        rows.append((artist["name"], artist.get("sub_genre", ""), album_count, total))

    rows.sort(key=lambda x: x[3], reverse=True)
    rows = rows[:n]

    print_table(
        ["#", "Artist", "Sub-genre", "Albums", "Total Reviews"],
        [[i + 1, name, sg, albums, rev] for i, (name, sg, albums, rev) in enumerate(rows)],
    )


def cmd_top_albums(
    data: list[dict],
    genre: str,
    sub_genre: str | None,
    n: int,
) -> None:
    """Albums in genre ranked by discogs_reviews."""
    rows = []
    for artist in data:
        if artist.get("genre") != genre:
            continue
        if sub_genre and artist.get("sub_genre") != sub_genre:
            continue
        for album in artist.get("albums", []):
            reviews = album.get("discogs_reviews") or 0
            rating = album.get("discogs_rating")
            rating_str = f"{rating:.2f}" if rating is not None else "—"
            rows.append((
                album.get("title", ""),
                artist["name"],
                album.get("year") or "—",
                reviews,
                rating_str,
                album.get("match_strategy") or "—",
            ))

    rows.sort(key=lambda x: x[3], reverse=True)
    rows = rows[:n]

    print_table(
        ["#", "Album", "Artist", "Year", "Reviews", "Rating", "Match"],
        [
            [i + 1, title, name, year, rev, rating, match]
            for i, (title, name, year, rev, rating, match) in enumerate(rows)
        ],
    )


def cmd_stats(data: list[dict]) -> None:
    """Overall statistics and per-genre breakdown."""
    from collections import defaultdict

    total_artists = len(data)
    total_albums = 0
    matched = 0
    unmatched = 0
    url_rel = 0
    search = 0

    genre_stats: dict[str, dict] = defaultdict(lambda: {
        "artists": 0, "albums": 0, "matched": 0, "unmatched": 0,
    })

    for artist in data:
        genre = artist.get("genre", "unknown")
        genre_stats[genre]["artists"] += 1
        for album in artist.get("albums", []):
            total_albums += 1
            genre_stats[genre]["albums"] += 1
            s = album.get("match_strategy")
            if s == "url_rel":
                url_rel += 1
                matched += 1
                genre_stats[genre]["matched"] += 1
            elif s == "search":
                search += 1
                matched += 1
                genre_stats[genre]["matched"] += 1
            else:
                unmatched += 1
                genre_stats[genre]["unmatched"] += 1

    print(f"\nTotal genres:   {len(genre_stats)}")
    print(f"Total artists:  {total_artists}")
    print(f"Total albums:   {total_albums}")
    print(f"  Matched:      {matched}  (url_rel={url_rel}, search={search})")
    print(f"  Unmatched:    {unmatched}")
    print()

    rows = sorted(genre_stats.items(), key=lambda x: x[1]["artists"], reverse=True)
    print_table(
        ["Genre", "Artists", "Albums", "Matched", "Unmatched"],
        [
            [g, s["artists"], s["albums"], s["matched"], s["unmatched"]]
            for g, s in rows
        ],
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Query enriched MusicBrainz/Discogs data.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python query.py top-genres --n 10
  python query.py top-artists --genre rock --n 20
  python query.py top-albums --genre rock --n 20
  python query.py top-albums --genre rock --sub-genre "indie rock" --n 20
  python query.py stats
""",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # top-genres
    p_tg = sub.add_parser("top-genres", help="Genres by average album review count")
    p_tg.add_argument("--n", type=int, default=10, help="Number of results (default: 10)")

    # top-artists
    p_ta = sub.add_parser("top-artists", help="Artists ranked by total reviews")
    p_ta.add_argument("--genre", required=True, help="Parent genre to filter")
    p_ta.add_argument("--n", type=int, default=20, help="Number of results (default: 20)")

    # top-albums
    p_tab = sub.add_parser("top-albums", help="Albums ranked by review count")
    p_tab.add_argument("--genre", required=True, help="Parent genre to filter")
    p_tab.add_argument("--sub-genre", dest="sub_genre", default=None, help="Sub-genre to filter")
    p_tab.add_argument("--n", type=int, default=20, help="Number of results (default: 20)")

    # stats
    sub.add_parser("stats", help="Overall statistics and genre breakdown")

    args = parser.parse_args()
    data = load_data()

    if args.command == "top-genres":
        cmd_top_genres(data, args.n)
    elif args.command == "top-artists":
        cmd_top_artists(data, args.genre, args.n)
    elif args.command == "top-albums":
        cmd_top_albums(data, args.genre, args.sub_genre, args.n)
    elif args.command == "stats":
        cmd_stats(data)


if __name__ == "__main__":
    main()
