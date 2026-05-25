#!/usr/bin/env python3
"""Phase 1: Crawl MusicBrainz for artists by genre tags.

Usage:
  python crawl_musicbrainz.py --genres "all"
  python crawl_musicbrainz.py --genres "rock,metal"
  python crawl_musicbrainz.py --genres "rock" --min-score 90
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
from pathlib import Path

import requests

from genres import GENRE_MAP, SUB_TO_GENRE
from utils import RunStats, log, log_section, log_section_end

MB_BASE = "https://musicbrainz.org/ws/2"
_contact = os.environ.get("MB_CONTACT", "groovesandrecords@gmail.com")
USER_AGENT = f"MusicGenreExplorer/1.0 ({_contact})"
CACHE_DIR = Path("./cache")
OUTPUT_FILE = Path("mb_data.json")
STATE_FILE  = Path("crawl_state.json")
SLEEP_INTERVAL = 1.1
MAX_RETRIES = 3

_MASTER_RE = re.compile(r"discogs\.com/master/(\d+)")
_RELEASE_RE = re.compile(r"discogs\.com/release/(\d+)")


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    return s


def cache_path(url: str) -> Path:
    h = hashlib.md5(url.encode()).hexdigest()
    return CACHE_DIR / f"{h}.json"


def fetch_json(session: requests.Session, url: str) -> dict:
    CACHE_DIR.mkdir(exist_ok=True)
    cp = cache_path(url)
    if cp.exists():
        try:
            return json.loads(cp.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cp.unlink()

    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            time.sleep(SLEEP_INTERVAL)
            resp = session.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            cp.write_text(json.dumps(data), encoding="utf-8")
            return data
        except Exception as exc:
            last_exc = exc
            if attempt < MAX_RETRIES - 1:
                wait = 2 ** (attempt + 1)
                log(f"[retry {attempt + 1}/{MAX_RETRIES}] {exc} — waiting {wait}s", indent=2)
                time.sleep(wait)
    raise RuntimeError(f"Failed after {MAX_RETRIES} retries: {last_exc}") from last_exc


# ---------------------------------------------------------------------------
# MusicBrainz helpers
# ---------------------------------------------------------------------------

def search_artists_by_tag(session: requests.Session, tag: str) -> list[dict]:
    results: list[dict] = []
    offset = 0
    limit = 100
    while True:
        query = f'tag:"{tag}"'
        url = (
            f"{MB_BASE}/artist"
            f"?query={urllib.parse.quote(query)}"
            f"&limit={limit}&offset={offset}&fmt=json"
        )
        log(f"Fetching page offset={offset} collected={len(results)} ...", indent=1)
        data = fetch_json(session, url)
        batch: list[dict] = data.get("artists", [])
        results.extend(batch)
        total: int = data.get("artist-count", 0)
        offset += len(batch)
        if len(batch) < limit or offset >= total:
            break
    return results


def fetch_artist_detail(session: requests.Session, mbid: str) -> dict:
    url = f"{MB_BASE}/artist/{mbid}?inc=tags+release-groups+url-rels&fmt=json"
    return fetch_json(session, url)


def fetch_rg_url_rels(session: requests.Session, rgid: str) -> list[dict]:
    url = f"{MB_BASE}/release-group/{rgid}?inc=url-rels&fmt=json"
    return fetch_json(session, url).get("relations", [])


def parse_discogs_from_rels(relations: list[dict]) -> tuple[int | None, int | None]:
    master_id: int | None = None
    release_id: int | None = None
    for rel in relations:
        resource = rel.get("url", {}).get("resource", "")
        m = _MASTER_RE.search(resource)
        if m and master_id is None:
            master_id = int(m.group(1))
        r = _RELEASE_RE.search(resource)
        if r and release_id is None:
            release_id = int(r.group(1))
    return master_id, release_id


def find_best_tag(tags: list[dict], valid_subs: set[str]) -> str | None:
    """Pick the sub-genre tag whose parent genre has the highest aggregate vote count.

    Prevents Metallica being classified as 'hard rock' just because that tag
    has slightly more votes than 'heavy metal' — metal wins if the SUM of all
    metal tag votes beats the sum of all rock tag votes.
    """
    # Collect vote count per matching sub-tag
    tag_votes: dict[str, int] = {}
    for tag in tags:
        name = tag.get("name", "").lower().strip()
        if name in valid_subs:
            tag_votes[name] = tag.get("count", 0)

    if not tag_votes:
        return None

    # Sum votes per parent genre, track best sub-tag within each genre
    genre_votes: dict[str, int] = {}
    genre_best: dict[str, tuple[str, int]] = {}  # genre -> (sub_tag, votes)
    for sub, votes in tag_votes.items():
        genre = SUB_TO_GENRE[sub]
        genre_votes[genre] = genre_votes.get(genre, 0) + votes
        if genre not in genre_best or votes > genre_best[genre][1]:
            genre_best[genre] = (sub, votes)

    best_genre = max(genre_votes, key=lambda g: genre_votes[g])
    return genre_best[best_genre][0]


def process_artist(
    session: requests.Session,
    mbid: str,
    valid_subs: set[str],
) -> dict | None:
    detail = fetch_artist_detail(session, mbid)
    matched_tag = find_best_tag(detail.get("tags", []), valid_subs)
    if matched_tag is None:
        return None

    albums: list[dict] = []
    rgs = [
        rg for rg in detail.get("release-groups", [])
        if rg.get("primary-type") == "Album" and not rg.get("secondary-types")
    ]

    for i, rg in enumerate(rgs):
        rgid: str = rg["id"]
        year_str: str = rg.get("first-release-date", "") or ""
        discogs_master_id = discogs_release_id = None
        try:
            rels = fetch_rg_url_rels(session, rgid)
            discogs_master_id, discogs_release_id = parse_discogs_from_rels(rels)
        except Exception as exc:
            log(f"url-rels failed for rg {rgid}: {exc}", indent=3)

        albums.append({
            "title": rg.get("title", ""),
            "year": int(year_str[:4]) if len(year_str) >= 4 else None,
            "mb_rgid": rgid,
            "discogs_master_id": discogs_master_id,
            "discogs_release_id": discogs_release_id,
        })

    return {
        "mbid": mbid,
        "name": detail.get("name", ""),
        "disambiguation": detail.get("disambiguation", ""),
        "genre": SUB_TO_GENRE[matched_tag],
        "sub_genre": matched_tag,
        "albums": albums,
    }


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def load_state() -> set[str]:
    if STATE_FILE.exists():
        try:
            return set(json.loads(STATE_FILE.read_text(encoding="utf-8")).get("completed_tags", []))
        except (json.JSONDecodeError, AttributeError):
            pass
    return set()


def save_state(completed_tags: set[str]) -> None:
    STATE_FILE.write_text(
        json.dumps({"completed_tags": sorted(completed_tags)}, indent=2),
        encoding="utf-8",
    )


def load_output() -> dict[str, dict]:
    if OUTPUT_FILE.exists():
        try:
            data = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
            return {a["mbid"]: a for a in data}
        except (json.JSONDecodeError, KeyError):
            log("Warning: existing output corrupt — starting fresh.")
    return {}


def save_output(artists: dict[str, dict]) -> None:
    OUTPUT_FILE.write_text(
        json.dumps(list(artists.values()), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Main crawl
# ---------------------------------------------------------------------------

def crawl(
    genres: list[str],
    limit: int | None = None,
    min_score: int = 0,
    max_minutes: int | None = None,
) -> None:
    session = make_session()
    artists = load_output()
    completed_tags = load_state()
    stats = RunStats()
    deadline = time.time() + max_minutes * 60 if max_minutes else None

    log(f"User-Agent     : {USER_AGENT}")
    log(f"Genres         : {', '.join(genres)}")
    log(f"Min score      : {min_score or 'off'}")
    log(f"Limit          : {limit or 'none'}")
    log(f"Max minutes    : {max_minutes or 'unlimited'}")
    log(f"Resuming       : {len(artists)} artists already saved")
    log(f"Completed tags : {len(completed_tags)}")

    valid_subs: set[str] = set()
    for g in genres:
        valid_subs.update(GENRE_MAP[g])

    new_count = 0

    for genre in genres:
        if limit and new_count >= limit:
            break

        for sub_tag in GENRE_MAP[genre]:
            if limit and new_count >= limit:
                break

            if sub_tag in completed_tags:
                log(f"  ↷ {genre} › {sub_tag} — already completed, skipping")
                continue

            log_section(f"{genre} › {sub_tag}")
            try:
                candidates = search_artists_by_tag(session, sub_tag)
            except Exception as exc:
                log(f"✗ tag search failed: {exc} — skipping", indent=1)
                save_output(artists)
                log_section_end()
                continue

            if min_score:
                before = len(candidates)
                candidates = [c for c in candidates if c.get("score", 0) >= min_score]
                log(f"{len(candidates)}/{before} candidates pass score≥{min_score}", indent=1)
            else:
                log(f"{len(candidates)} candidates", indent=1)

            log_section_end()

            total_c = len(candidates)
            for idx, stub in enumerate(candidates):
                if limit and new_count >= limit:
                    break

                mbid = stub.get("id")
                if not mbid:
                    continue

                pos = f"{idx + 1:>4}/{total_c}"
                name = stub.get("name", "?")
                score = stub.get("score", "?")

                if deadline and time.time() >= deadline:
                    log(f"⏱ Time limit reached — stopping gracefully.")
                    save_output(artists)
                    log(f"Finished. {stats.summary_line()}")
                    return

                if mbid in artists:
                    log(f"{pos} | score={score:>3} | {name} — already done", indent=1)
                    stats.skipped += 1
                    continue

                log(f"{pos} | score={score:>3} | {name}", indent=1)
                try:
                    artist = process_artist(session, mbid, valid_subs)
                    if artist:
                        artists[mbid] = artist
                        new_count += 1
                        stats.found += 1
                        log(
                            f"✓ {artist['genre']} › {artist['sub_genre']} "
                            f"| {len(artist['albums'])} albums "
                            f"| total saved: {len(artists)} | {stats.summary_line()}",
                            indent=2,
                        )
                    else:
                        stats.no_match += 1
                        log("✗ no matching tag", indent=2)
                except Exception as exc:
                    stats.errors += 1
                    log(f"✗ ERROR: {exc}", indent=2)

                if (idx + 1) % 10 == 0:
                    save_output(artists)

            else:
                # for-loop completed without break → all candidates processed
                if not (limit and new_count >= limit):
                    completed_tags.add(sub_tag)
                    save_state(completed_tags)
                    log(f"  ✓ tag '{sub_tag}' marked complete", indent=1)

    save_output(artists)
    save_state(completed_tags)
    log(f"Finished. {stats.summary_line()}")
    log(f"Total artists in output: {len(artists)}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Crawl MusicBrainz for genre-tagged artists and their albums.\n"
            "Set MB_CONTACT env var to your email/URL for the User-Agent."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--genres", default="all", metavar="GENRES",
        help=f"Comma-separated parent genres or 'all'. Valid: {', '.join(GENRE_MAP)}.",
    )
    parser.add_argument(
        "--limit", type=int, default=None, metavar="N",
        help="Stop after N new artists (testing).",
    )
    parser.add_argument(
        "--min-score", type=int, default=85, metavar="N",
        help="Min MusicBrainz search score (0-100). Default: 85. Use 0 to disable.",
    )
    parser.add_argument(
        "--max-minutes", type=int, default=None, metavar="N",
        help="Stop gracefully after N minutes (for CI time limits).",
    )
    args = parser.parse_args()

    if args.genres.strip().lower() == "all":
        genres = list(GENRE_MAP.keys())
    else:
        genres = [g.strip() for g in args.genres.split(",")]
        invalid = [g for g in genres if g not in GENRE_MAP]
        if invalid:
            print(f"Unknown genres: {invalid}. Valid: {list(GENRE_MAP.keys())}", file=sys.stderr)
            sys.exit(1)

    crawl(genres, limit=args.limit, min_score=args.min_score, max_minutes=args.max_minutes)


if __name__ == "__main__":
    main()
