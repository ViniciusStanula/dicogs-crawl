#!/usr/bin/env python3
"""Rock Record Rankings — Streamlit Dashboard.

Usage:
  pip install streamlit pandas
  streamlit run dashboard.py
"""

import base64
import html
import json
from pathlib import Path

import pandas as pd
import streamlit as st

DATA_FILE = Path("enriched_data.json")
COVERS_DIR = Path("covers")

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Wax & Rankings",
    page_icon="🎵",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ──────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,700;0,900;1,400&family=IBM+Plex+Mono:wght@400;500;700&display=swap');

:root {
    --bg:       #080808;
    --surface:  #111111;
    --surface2: #191919;
    --border:   #252015;
    --gold:     #c9a84c;
    --gold-dim: #5a4820;
    --text:     #e0d8c8;
    --muted:    #5a5248;
    --red:      #9b2335;
    --green:    #2d7a4f;
}

html, body, [data-testid="stApp"] {
    background-color: var(--bg) !important;
    color: var(--text);
    font-family: 'IBM Plex Mono', monospace;
}

/* Hide Streamlit chrome */
#MainMenu, footer { visibility: hidden; }

/* Sidebar */
[data-testid="stSidebar"] {
    background: var(--surface) !important;
    border-right: 1px solid var(--border) !important;
}

/* Metric cards */
[data-testid="metric-container"] {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-top: 2px solid var(--gold) !important;
    border-radius: 0 !important;
    padding: 1rem 1.2rem !important;
}
[data-testid="metric-container"] label {
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.6rem !important;
    letter-spacing: 0.15em !important;
    text-transform: uppercase !important;
    color: var(--muted) !important;
}
[data-testid="metric-container"] [data-testid="stMetricValue"] {
    font-family: 'Playfair Display', serif !important;
    font-size: 1.8rem !important;
    color: var(--gold) !important;
}

/* Tabs */
.stTabs [data-baseweb="tab-list"] {
    background: transparent !important;
    border-bottom: 1px solid var(--border) !important;
    gap: 0 !important;
}
.stTabs [data-baseweb="tab"] {
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.65rem !important;
    letter-spacing: 0.15em !important;
    text-transform: uppercase !important;
    color: var(--muted) !important;
    padding: 0.6rem 1.5rem !important;
    border-radius: 0 !important;
    background: transparent !important;
}
.stTabs [aria-selected="true"] {
    color: var(--gold) !important;
    border-bottom: 2px solid var(--gold) !important;
    background: transparent !important;
}

/* DataFrame */
[data-testid="stDataFrame"] iframe {
    background: var(--surface) !important;
}

/* Sliders */
[data-testid="stSlider"] [data-baseweb="slider"] [data-testid="stThumbValue"] {
    color: var(--gold) !important;
}

/* Divider */
hr { border-color: var(--border) !important; margin: 1rem 0 !important; }

/* Album cards */
.album-row {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 12px 16px;
    border-bottom: 1px solid var(--border);
    transition: background 0.15s;
}
.album-row:hover { background: var(--surface2); }
.album-row:first-child { border-top: 1px solid var(--border); }

.rank {
    font-family: 'Playfair Display', serif;
    font-size: 1.4rem;
    font-weight: 900;
    color: var(--border);
    min-width: 40px;
    text-align: right;
    line-height: 1;
}
.rank.gold { color: var(--gold); }
.rank.silver { color: #909090; }
.rank.bronze { color: #8b6340; }

.cover-thumb {
    width: 52px;
    height: 52px;
    object-fit: cover;
    border: 1px solid var(--border);
    flex-shrink: 0;
    filter: grayscale(20%);
}
.cover-placeholder {
    width: 52px;
    height: 52px;
    background: var(--surface2);
    border: 1px solid var(--border);
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.2rem;
}

.album-info { flex: 1; min-width: 0; }
.album-title {
    font-family: 'Playfair Display', serif;
    font-size: 0.95rem;
    font-weight: 700;
    color: var(--text);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.album-artist {
    font-size: 0.7rem;
    color: var(--muted);
    margin-top: 3px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.album-sub {
    display: inline-block;
    font-size: 0.55rem;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--gold-dim);
    border: 1px solid var(--gold-dim);
    padding: 1px 5px;
    margin-top: 4px;
}

.album-stats { text-align: right; flex-shrink: 0; }
.stars { color: var(--gold); font-size: 0.65rem; letter-spacing: 2px; }
.rating-val {
    font-family: 'Playfair Display', serif;
    font-size: 1.1rem;
    font-weight: 700;
    color: var(--gold);
}
.review-count { font-size: 0.62rem; color: var(--muted); margin-top: 2px; }
.year-badge { font-size: 0.62rem; color: var(--muted); }

/* Artist consistency card */
.artist-row {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 14px 16px;
    border-bottom: 1px solid var(--border);
}
.artist-row:hover { background: var(--surface2); }
.artist-row:first-child { border-top: 1px solid var(--border); }

.artist-name {
    font-family: 'Playfair Display', serif;
    font-size: 1rem;
    font-weight: 700;
    color: var(--text);
}
.artist-sub { font-size: 0.65rem; color: var(--muted); margin-top: 3px; }

.consistency-bar-bg {
    height: 3px;
    background: var(--surface2);
    border-radius: 0;
    margin-top: 6px;
    width: 120px;
}
.consistency-bar-fill {
    height: 3px;
    background: var(--gold);
    border-radius: 0;
}

.stat-chip {
    font-size: 0.6rem;
    letter-spacing: 0.08em;
    color: var(--muted);
    text-transform: uppercase;
}
.stat-val {
    font-family: 'Playfair Display', serif;
    font-size: 1rem;
    color: var(--text);
}

/* Sidebar logo */
.sidebar-logo {
    font-family: 'Playfair Display', serif;
    font-size: 1.4rem;
    font-weight: 900;
    color: var(--gold);
    letter-spacing: -0.02em;
    line-height: 1;
}
.sidebar-sub {
    font-size: 0.55rem;
    letter-spacing: 0.2em;
    text-transform: uppercase;
    color: var(--muted);
    margin-top: 4px;
}

/* Page title */
.page-title {
    font-family: 'Playfair Display', serif;
    font-size: 2.8rem;
    font-weight: 900;
    color: var(--gold);
    letter-spacing: -0.03em;
    line-height: 1;
}
.page-subtitle {
    font-size: 0.7rem;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    color: var(--muted);
    margin-top: 6px;
}

.section-label {
    font-size: 0.6rem;
    letter-spacing: 0.2em;
    text-transform: uppercase;
    color: var(--muted);
    margin-bottom: 0;
}
</style>
""", unsafe_allow_html=True)


# ── Data loading ─────────────────────────────────────────────────────────────

@st.cache_data
def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    if not DATA_FILE.exists():
        return pd.DataFrame(), pd.DataFrame()

    raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))

    rows = []
    for artist in raw:
        for album in artist.get("albums", []):
            reviews = album.get("discogs_reviews")
            rating = album.get("discogs_rating")
            if not reviews or not rating:
                continue
            rows.append({
                "artist":    artist["name"],
                "mbid":      artist["mbid"],
                "genre":     artist.get("genre", ""),
                "sub_genre": artist.get("sub_genre", ""),
                "title":     album["title"],
                "year":      album.get("year"),
                "mb_rgid":   album["mb_rgid"],
                "reviews":   int(reviews),
                "rating":    float(rating),
                "cover":     album.get("cover_path") or "",
                "strategy":  album.get("match_strategy", ""),
            })

    if not rows:
        return pd.DataFrame(), pd.DataFrame()

    df = pd.DataFrame(rows)

    # Per-artist consistency stats (min 2 matched albums)
    stats = (
        df.groupby(["artist", "mbid", "sub_genre"])
        .agg(
            albums=("title", "count"),
            avg_rating=("rating", "mean"),
            min_rating=("rating", "min"),
            max_rating=("rating", "max"),
            std_rating=("rating", "std"),
            total_reviews=("reviews", "sum"),
            avg_reviews=("reviews", "mean"),
        )
        .reset_index()
    )
    stats["std_rating"] = stats["std_rating"].fillna(0)
    # Consistency = avg penalised by variance; bonus for many albums
    stats["consistency"] = (
        stats["avg_rating"] - stats["std_rating"] * 0.4
    ).round(3)
    stats = stats[stats["albums"] >= 2].copy()

    return df, stats


def img_b64(path: str) -> str | None:
    try:
        p = Path(path)
        if p.exists():
            return base64.b64encode(p.read_bytes()).decode()
    except Exception:
        pass
    return None


def stars(rating: float) -> str:
    full = int(round(rating))
    return "★" * full + "☆" * (5 - full)


def rank_cls(i: int) -> str:
    return {0: "gold", 1: "silver", 2: "bronze"}.get(i, "")


# ── Load ─────────────────────────────────────────────────────────────────────
df, artist_stats = load_data()

if df.empty:
    st.error("No data found — run `enrich_discogs.py` first.")
    st.stop()

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
        <div class="sidebar-logo">Wax &<br>Rankings</div>
        <div class="sidebar-sub">Rock record intelligence</div>
    """, unsafe_allow_html=True)
    st.markdown("---")

    all_subs = sorted(df["sub_genre"].unique())
    sub_options = ["— All styles —"] + all_subs
    selected_sub = st.selectbox("Style", sub_options, label_visibility="collapsed")
    if selected_sub == "— All styles —":
        selected_sub = None

    st.markdown("---")
    st.markdown('<div class="section-label">Filters</div>', unsafe_allow_html=True)
    min_reviews = st.slider("Min reviews", 0, 1000, 20, step=10)
    top_n       = st.slider("Show top N", 5, 50, 20, step=5)
    sort_by     = st.radio("Rank albums by", ["Rating", "Review count"], horizontal=True)

    st.markdown("---")
    st.markdown('<div class="section-label">Consistency</div>', unsafe_allow_html=True)
    min_albums = st.slider("Min albums per artist", 2, 10, 3)

# ── Filter ───────────────────────────────────────────────────────────────────
filtered = df[df["reviews"] >= min_reviews].copy()
if selected_sub:
    filtered = filtered[filtered["sub_genre"] == selected_sub]

sort_col  = "rating" if sort_by == "Rating" else "reviews"
top_albums = filtered.nlargest(top_n, sort_col).reset_index(drop=True)

a_filtered = artist_stats.copy()
if selected_sub:
    a_filtered = a_filtered[a_filtered["sub_genre"] == selected_sub]
a_filtered = a_filtered[
    (a_filtered["albums"] >= min_albums) &
    (a_filtered["avg_reviews"] >= min_reviews)
]
top_artists = a_filtered.nlargest(top_n, "consistency").reset_index(drop=True)

# ── Header ────────────────────────────────────────────────────────────────────
title_label = selected_sub.title() if selected_sub else "All Rock"
st.markdown(
    f'<div class="page-title">{title_label}</div>'
    f'<div class="page-subtitle">'
    f'{len(filtered):,} albums · {filtered["artist"].nunique():,} artists'
    f'</div>',
    unsafe_allow_html=True,
)
st.markdown("<br>", unsafe_allow_html=True)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Albums",        f"{len(filtered):,}")
c2.metric("Artists",       f"{filtered['artist'].nunique():,}")
c3.metric("Avg Rating",    f"{filtered['rating'].mean():.2f}" if not filtered.empty else "—")
c4.metric("Total Reviews", f"{filtered['reviews'].sum():,}")

st.markdown("<br>", unsafe_allow_html=True)

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_alb, tab_art = st.tabs(["TOP ALBUMS", "MOST CONSISTENT ARTISTS"])

# ─ Albums tab ────────────────────────────────────────────────────────────────
with tab_alb:
    if top_albums.empty:
        st.info("No albums match current filters.")
    else:
        html_rows = []
        for i, row in top_albums.iterrows():
            rc    = rank_cls(i)
            b64   = img_b64(row["cover"])
            ext   = Path(row["cover"]).suffix.lstrip(".") or "jpeg" if row["cover"] else "jpeg"
            mime  = "png" if ext == "png" else "jpeg"
            img_html = (
                f'<img class="cover-thumb" src="data:image/{mime};base64,{b64}">'
                if b64 else
                '<div class="cover-placeholder">♪</div>'
            )
            year  = str(int(row["year"])) if pd.notna(row["year"]) else "—"
            title = html.escape(row["title"])
            artist = html.escape(row["artist"])
            sub   = html.escape(row["sub_genre"])
            html_rows.append(f"""
            <div class="album-row">
                <div class="rank {rc}">#{i + 1}</div>
                {img_html}
                <div class="album-info">
                    <div class="album-title">{title}</div>
                    <div class="album-artist">{artist}</div>
                    <span class="album-sub">{sub}</span>
                </div>
                <div class="album-stats">
                    <div class="stars">{stars(row['rating'])}</div>
                    <div class="rating-val">{row['rating']:.2f}</div>
                    <div class="review-count">{row['reviews']:,} reviews</div>
                    <div class="year-badge">{year}</div>
                </div>
            </div>""")

        st.markdown("".join(html_rows), unsafe_allow_html=True)

# ─ Artists tab ───────────────────────────────────────────────────────────────
with tab_art:
    if top_artists.empty:
        st.info("No artists match current filters.")
    else:
        st.markdown(
            '<div style="font-size:0.65rem;color:var(--muted,#5a5248);letter-spacing:0.1em;'
            'margin-bottom:8px">Consistency = avg rating − (std dev × 0.4). '
            'Rewards artists with uniformly great records.</div>',
            unsafe_allow_html=True,
        )
        html_rows = []
        max_c = top_artists["consistency"].max()

        for i, row in top_artists.iterrows():
            rc       = rank_cls(i)
            bar_pct  = int(row["consistency"] / max_c * 100) if max_c else 0
            std_str  = f"±{row['std_rating']:.2f}" if row["std_rating"] else "±0.00"
            artist_e = html.escape(row["artist"])
            sub_e    = html.escape(row["sub_genre"])
            html_rows.append(f"""
            <div class="artist-row">
                <div class="rank {rc}">#{i + 1}</div>
                <div style="flex:1;min-width:0">
                    <div class="artist-name">{artist_e}</div>
                    <div class="artist-sub">{sub_e} · {int(row['albums'])} albums · {std_str} variance</div>
                    <div class="consistency-bar-bg">
                        <div class="consistency-bar-fill" style="width:{bar_pct}%"></div>
                    </div>
                </div>
                <div style="text-align:right;flex-shrink:0">
                    <div class="stars">{stars(row['avg_rating'])}</div>
                    <div class="rating-val">{row['avg_rating']:.2f}</div>
                    <div class="review-count">{int(row['total_reviews']):,} total reviews</div>
                </div>
                <div style="text-align:right;flex-shrink:0;margin-left:20px;min-width:80px">
                    <div class="stat-chip">consistency</div>
                    <div class="stat-val">{row['consistency']:.3f}</div>
                </div>
            </div>""")

        st.markdown("".join(html_rows), unsafe_allow_html=True)
