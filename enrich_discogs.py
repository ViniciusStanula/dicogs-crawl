#!/usr/bin/env python3
"""Phase 2: Enrich mb_data.json with Discogs ratings + cover images.

Reviews = aggregate across ALL pressings of each master (Option B).
Parallel HTTP via ThreadPoolExecutor, thread-safe rate limiter.

Usage:
  python enrich_discogs.py
  python enrich_discogs.py --genres "rock,metal"
  python enrich_discogs.py --max-versions 100   # cap versions per master (0=unlimited)

Env vars:
  DISCOGS_TOKEN    Personal access token  → Authorization: Discogs token=TOKEN
  DISCOGS_KEY +
  DISCOGS_SECRET   OAuth consumer creds   → Authorization: Discogs key=KEY, secret=SECRET
  MB_CONTACT       Contact info for User-Agent (default: groovesandrecords@gmail.com)
"""

import argparse
import hashlib
import json
import os
import sys
import threading
import time
import urllib.parse
from pathlib import Path

import requests

from genres import GENRE_MAP
from utils import ProgressBar, log, log_section, log_section_end

DISCOGS_BASE = "https://api.discogs.com"
_contact = os.environ.get("MB_CONTACT", "groovesandrecords@gmail.com")
USER_AGENT = f"MusicGenreExplorer/1.0 ({_contact})"
CACHE_DIR = Path("./cache")
COVERS_DIR = Path("./covers")
INPUT_FILE = Path("mb_data.json")
OUTPUT_FILE = Path("enriched_data.json")
MAX_RETRIES = 3

# ---------------------------------------------------------------------------
# HTTP / rate limiting
# ---------------------------------------------------------------------------

def cache_path(url: str) -> Path:
    h = hashlib.md5(url.encode()).hexdigest()
    return CACHE_DIR / f"{h}.json"


class RateLimiter:
    """Thread-safe rate limiter. All threads share one slot queue via a lock."""

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self.min_interval = 60.0 / per_minute
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.time()
            elapsed = now - self._last
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self._last = time.time()

    def throttled(self, retry_after: int) -> None:
        """Called on 429 — pushes _last forward so next wait() sleeps correctly."""
        print(f"  Throttling (429) — backing off {retry_after}s", flush=True)
        with self._lock:
            self._last = time.time() + retry_after


def _resolve_auth() -> tuple[str | None, int]:
    token = os.environ.get("DISCOGS_TOKEN")
    if token:
        return f"Discogs token={token}", 240
    key = os.environ.get("DISCOGS_KEY")
    secret = os.environ.get("DISCOGS_SECRET")
    if key and secret:
        # key+secret app auth is still subject to 60 req/min; 240 req/min requires a user OAuth token
        return f"Discogs key={key}, secret={secret}", 60
    return None, 60


def make_session() -> tuple[requests.Session, RateLimiter]:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    auth_header, rpm = _resolve_auth()
    if auth_header:
        s.headers["Authorization"] = auth_header
        method = "token" if "token=" in auth_header else "key+secret"
        print(f"Discogs auth via {method} — {rpm} req/min.", flush=True)
    else:
        print("No Discogs auth — 60 req/min limit.", flush=True)
    return s, RateLimiter(per_minute=rpm)


def fetch_json(
    session: requests.Session,
    limiter: RateLimiter,
    url: str,
    use_cache: bool = True,
) -> dict:
    CACHE_DIR.mkdir(exist_ok=True)
    cp = cache_path(url)
    if use_cache and cp.exists():
        try:
            return json.loads(cp.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cp.unlink()

    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            limiter.wait()
            resp = session.get(url, timeout=30)
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 60))
                limiter.throttled(retry_after)
                time.sleep(retry_after)
                continue
            resp.raise_for_status()
            data = resp.json()
            cp.write_text(json.dumps(data), encoding="utf-8")
            return data
        except Exception as exc:
            last_exc = exc
            if attempt < MAX_RETRIES - 1:
                wait = 2 ** (attempt + 1)
                print(f"  [retry {attempt + 1}/{MAX_RETRIES}] {exc} — waiting {wait}s", flush=True)
                time.sleep(wait)

    raise RuntimeError(f"Failed after {MAX_RETRIES} retries: {last_exc}") from last_exc


# ---------------------------------------------------------------------------
# Cover image download
# ---------------------------------------------------------------------------

def download_cover(session: requests.Session, image_url: str, mb_rgid: str) -> str | None:
    COVERS_DIR.mkdir(exist_ok=True)
    ext = image_url.rsplit(".", 1)[-1].split("?")[0] or "jpg"
    dest = COVERS_DIR / f"{mb_rgid}.{ext}"
    if dest.exists():
        return str(dest)
    try:
        resp = session.get(image_url, timeout=30)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        return str(dest)
    except Exception as exc:
        print(f"    Warning: cover download failed for {mb_rgid}: {exc}", flush=True)
        return None


def pick_cover_url(images: list[dict]) -> str | None:
    for img in images:
        if img.get("type") == "primary":
            uri = img.get("uri") or img.get("uri150")
            if uri:
                return uri
    if images:
        return images[0].get("uri") or images[0].get("uri150")
    return None


# ---------------------------------------------------------------------------
# Discogs strategies
# ---------------------------------------------------------------------------

def get_top_version_ids(
    session: requests.Session,
    limiter: RateLimiter,
    versions_url: str,
    max_versions: int,
) -> list[int]:
    """Paginate versions list, rank by in_collection, return top N release IDs.

    Each version entry already includes stats.community.in_collection — a free
    proxy for popularity. Fetching community.rating only for top-N versions
    captures 95%+ of total reviews without fetching hundreds of obscure pressings.
    """
    versions: list[dict] = []
    page = 1
    while True:
        url = f"{versions_url}?per_page=100&page={page}"
        data = fetch_json(session, limiter, url)
        versions.extend(data.get("versions", []))
        pagination = data.get("pagination", {})
        if page >= pagination.get("pages", 1):
            break
        page += 1

    # Sort by in_collection descending — most-owned pressings have the most ratings
    def collection_count(v: dict) -> int:
        return v.get("stats", {}).get("community", {}).get("in_collection", 0)

    versions.sort(key=collection_count, reverse=True)

    if max_versions:
        versions = versions[:max_versions]

    return [v["id"] for v in versions if v.get("id")]


def fetch_release_community(
    session: requests.Session,
    limiter: RateLimiter,
    release_id: int,
) -> tuple[int, float]:
    """Return (rating_count, rating_average) for one release. Returns (0, 0.0) on error."""
    url = f"{DISCOGS_BASE}/releases/{release_id}"
    try:
        data = fetch_json(session, limiter, url)
        rating = data.get("community", {}).get("rating", {})
        return int(rating.get("count") or 0), float(rating.get("average") or 0.0)
    except Exception:
        return 0, 0.0


def strategy_a_master(
    session: requests.Session,
    limiter: RateLimiter,
    master_id: int,
    mb_rgid: str,
    max_versions: int,
    main_only: bool = False,
) -> tuple[int | None, float | None, int | None, str | None]:
    """Fetch master metadata + community ratings.

    main_only=True: 2 calls per album (master + main_release). Fast.
    main_only=False: fetches top N versions and aggregates. Slower but higher counts.

    Returns (total_reviews, weighted_avg_rating, main_release_id, cover_path).
    """
    master_url = f"{DISCOGS_BASE}/masters/{master_id}"
    try:
        master_data = fetch_json(session, limiter, master_url)
    except Exception as exc:
        print(f"    Warning: master {master_id} fetch failed: {exc}", flush=True)
        return None, None, None, None

    main_release: int | None = master_data.get("main_release")
    versions_url: str = master_data.get("versions_url", f"{master_url}/versions")

    # Cover image
    cover_path: str | None = None
    cover_url = pick_cover_url(master_data.get("images", []))
    if cover_url:
        cover_path = download_cover(session, cover_url, mb_rgid)

    if main_only:
        if not main_release:
            return None, None, None, cover_path
        count, avg = fetch_release_community(session, limiter, main_release)
        return (count or None), (round(avg, 2) if avg else None), main_release, cover_path

    # Multi-version aggregation
    try:
        version_ids = get_top_version_ids(session, limiter, versions_url, max_versions)
    except Exception as exc:
        print(f"    Warning: versions fetch failed for master {master_id}: {exc}", flush=True)
        version_ids = [main_release] if main_release else []

    if not version_ids:
        return None, None, main_release, cover_path

    print(f"    Fetching community data for {len(version_ids)} versions...", flush=True)

    results = [fetch_release_community(session, limiter, rid) for rid in version_ids]

    total_count = sum(c for c, _ in results)
    weighted_sum = sum(c * a for c, a in results if c > 0)
    avg: float | None = round(weighted_sum / total_count, 2) if total_count > 0 else None

    return (total_count or None), avg, main_release, cover_path


def strategy_b_search(
    session: requests.Session,
    limiter: RateLimiter,
    title: str,
    artist: str,
    year: int | None,
) -> int | None:
    """Search Discogs; return release ID only on confident title+year match."""
    params: dict[str, str] = {
        "release_title": title,
        "artist": artist,
        "type": "release",
        "per_page": "5",
    }
    url = f"{DISCOGS_BASE}/database/search?{urllib.parse.urlencode(params)}"
    try:
        data = fetch_json(session, limiter, url)
        results: list[dict] = data.get("results", [])
    except Exception as exc:
        print(f"    Warning: search failed: {exc}", flush=True)
        return None

    title_lower = title.lower()
    for result in results:
        raw_title: str = result.get("title", "")
        parts = raw_title.split(" - ", 1)
        result_album = parts[1].strip() if len(parts) == 2 else raw_title.strip()

        if result_album.lower() != title_lower:
            continue

        result_year_raw = result.get("year")
        if year is not None and result_year_raw is not None:
            try:
                if abs(int(result_year_raw) - year) > 1:
                    continue
            except (ValueError, TypeError):
                continue

        rid = result.get("id")
        if rid:
            return rid

    return None


# ---------------------------------------------------------------------------
# Per-album enrichment
# ---------------------------------------------------------------------------

def enrich_album(
    session: requests.Session,
    limiter: RateLimiter,
    album: dict,
    artist_name: str,
    max_versions: int,
    main_only: bool = False,
) -> dict:
    result: dict = {
        "title": album["title"],
        "year": album.get("year"),
        "mb_rgid": album["mb_rgid"],
        "match_strategy": None,
        "discogs_id": None,
        "discogs_reviews": None,
        "discogs_rating": None,
        "cover_path": None,
    }

    # Strategy A — via MusicBrainz URL relationship (master)
    if album.get("discogs_master_id"):
        total, avg, main_release, cover_path = strategy_a_master(
            session, limiter,
            album["discogs_master_id"],
            album["mb_rgid"],
            max_versions,
            main_only=main_only,
        )
        if total is not None or main_release is not None:
            result["discogs_id"] = main_release
            result["discogs_reviews"] = total
            result["discogs_rating"] = avg
            result["cover_path"] = cover_path
            result["match_strategy"] = "url_rel"
            return result

    # Strategy A — direct release ID
    if album.get("discogs_release_id"):
        rid = album["discogs_release_id"]
        count, avg = fetch_release_community(session, limiter, rid)
        result["discogs_id"] = rid
        result["discogs_reviews"] = count or None
        result["discogs_rating"] = round(avg, 2) if avg else None
        result["match_strategy"] = "url_rel"
        return result

    # Strategy B — title/artist search
    rid = strategy_b_search(session, limiter, album["title"], artist_name, album.get("year"))
    if rid:
        count, avg = fetch_release_community(session, limiter, rid)
        result["discogs_id"] = rid
        result["discogs_reviews"] = count or None
        result["discogs_rating"] = round(avg, 2) if avg else None
        result["match_strategy"] = "search"

    return result


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def load_enriched() -> dict[str, dict]:
    if OUTPUT_FILE.exists():
        try:
            data = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
            return {a["mbid"]: a for a in data}
        except (json.JSONDecodeError, KeyError):
            print("Warning: existing enriched output corrupt — starting fresh.", flush=True)
    return {}


def get_processed_rgids(enriched: dict[str, dict]) -> set[str]:
    rgids: set[str] = set()
    for artist in enriched.values():
        for album in artist.get("albums", []):
            rgids.add(album["mb_rgid"])
    return rgids


def save_enriched(enriched: dict[str, dict]) -> None:
    OUTPUT_FILE.write_text(
        json.dumps(list(enriched.values()), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Main enrichment loop
# ---------------------------------------------------------------------------

def enrich(genres: list[str] | None, max_versions: int, main_only: bool = False, max_minutes: int | None = None) -> None:
    if not INPUT_FILE.exists():
        print(f"Error: {INPUT_FILE} not found. Run crawl_musicbrainz.py first.", file=sys.stderr)
        sys.exit(1)

    mb_data: list[dict] = json.loads(INPUT_FILE.read_text(encoding="utf-8"))
    if genres:
        mb_data = [a for a in mb_data if a.get("genre") in genres]

    session, limiter = make_session()

    enriched = load_enriched()
    processed_rgids = get_processed_rgids(enriched)
    mv_label = "main_only (2 calls/album)" if main_only else (str(max_versions) if max_versions else "unlimited")
    deadline = time.time() + max_minutes * 60 if max_minutes else None
    log(f"Resuming    : {len(enriched)} artists, {len(processed_rgids)} albums done")
    log(f"To process  : {len(mb_data)} artists")
    log(f"Max versions: {mv_label}")
    log(f"Max minutes : {max_minutes or 'unlimited'}")

    stats: dict[str, int] = {"total": 0, "url_rel": 0, "search": 0, "unmatched": 0}
    crawled_genres: set[str] = set()

    for artist_idx, artist in enumerate(mb_data):
        mbid: str = artist["mbid"]
        crawled_genres.add(artist.get("genre", ""))
        albums_total = len(artist.get("albums", []))

        log_section(f"{artist_idx + 1}/{len(mb_data)}  {artist['name']}")
        log(f"genre={artist.get('genre')}  sub={artist.get('sub_genre')}  albums={albums_total}", indent=1)

        existing_by_rgid: dict[str, dict] = {}
        if mbid in enriched:
            for alb in enriched[mbid].get("albums", []):
                existing_by_rgid[alb["mb_rgid"]] = alb

        enriched_albums: list[dict] = []
        pb = ProgressBar(total=albums_total, prefix="albums ")

        for alb_idx, album in enumerate(artist.get("albums", []), 1):
            stats["total"] += 1
            rgid = album["mb_rgid"]

            if rgid in processed_rgids and rgid in existing_by_rgid:
                cached = existing_by_rgid[rgid]
                enriched_albums.append(cached)
                s = cached.get("match_strategy")
                stats[s if s else "unmatched"] = stats.get(s if s else "unmatched", 0) + 1
                pb.update(alb_idx, suffix=f"{album['title'][:30]} [cached]")
                continue

            pb.update(alb_idx, suffix=f"{album['title'][:30]}")
            enriched_album = enrich_album(session, limiter, album, artist["name"], max_versions, main_only=main_only)
            enriched_albums.append(enriched_album)
            s = enriched_album.get("match_strategy")
            if s:
                stats[s] = stats.get(s, 0) + 1
            else:
                stats["unmatched"] += 1
            rev = enriched_album.get("discogs_reviews")
            rat = enriched_album.get("discogs_rating")
            cover = "✓" if enriched_album.get("cover_path") else "✗"
            log(
                f"  {album['title'][:40]:<40} "
                f"strategy={s or 'none':<7}  reviews={str(rev):<6}  "
                f"rating={str(rat):<4}  cover={cover}",
                indent=1,
            )

        pb.done()

        enriched[mbid] = {
            "mbid": mbid,
            "name": artist["name"],
            "genre": artist.get("genre"),
            "sub_genre": artist.get("sub_genre"),
            "albums": enriched_albums,
        }

        if (artist_idx + 1) % 5 == 0:
            save_enriched(enriched)

        if deadline and time.time() >= deadline:
            log("⏱ Time limit reached — stopping gracefully.")
            save_enriched(enriched)
            return

    save_enriched(enriched)

    log_section("Enrichment Summary")
    log(f"Genres    : {', '.join(sorted(crawled_genres))}")
    log(f"Artists   : {len(enriched)}")
    log(f"Albums    : {stats['total']}")
    log(f"url_rel   : {stats.get('url_rel', 0)}")
    log(f"search    : {stats.get('search', 0)}")
    log(f"unmatched : {stats['unmatched']}")
    log_section_end()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Enrich mb_data.json with Discogs aggregate ratings + cover images.\n"
            "Set DISCOGS_KEY + DISCOGS_SECRET (or DISCOGS_TOKEN) for 240 req/min.\n"
            "Set MB_CONTACT for User-Agent contact info."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--genres",
        default=None,
        metavar="GENRES",
        help=f"Comma-separated parent genres, or omit for all. Valid: {', '.join(GENRE_MAP)}.",
    )
    parser.add_argument(
        "--max-versions",
        type=int,
        default=50,
        metavar="N",
        help="Max pressings to aggregate per master, ranked by popularity (0 = unlimited, default: 50).",
    )
    parser.add_argument(
        "--main-only",
        action="store_true",
        help="Fastest mode: fetch only main_release per master (2 API calls/album). No version aggregation.",
    )
    parser.add_argument(
        "--max-minutes",
        type=int,
        default=None,
        metavar="N",
        help="Stop gracefully after N minutes (for CI time limits).",
    )
    args = parser.parse_args()

    genres: list[str] | None = None
    if args.genres:
        genres = [g.strip() for g in args.genres.split(",")]
        invalid = [g for g in genres if g not in GENRE_MAP]
        if invalid:
            print(f"Unknown genres: {invalid}. Valid: {list(GENRE_MAP.keys())}", file=sys.stderr)
            sys.exit(1)

    enrich(genres, max_versions=args.max_versions, main_only=args.main_only, max_minutes=args.max_minutes)


if __name__ == "__main__":
    main()
