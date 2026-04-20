#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DiscoveryLastFM.py · v2.2.0 (GenreDiscovery fork)
– Lidarr/Headphones integration via modular service layer
– Supports both services with config-driven switching
– GitHub auto-update system with backup and rollback
– Maintains identical workflow and cache compatibility with v1.7.x
– Zero breaking changes for existing configurations
– [NEW v2.2] Genre-aware discovery: groups artists by genre and
  discovers similar artists per genre instead of per individual artist
– [NEW v2.2] Loved/Starred tracks priority phase (Last.fm + Navidrome)
– [NEW v2.2] Navidrome/Subsonic integration (optional)
"""

import sys
from pathlib import Path

# When running in Docker, /config holds user data (config.py, cache, logs)
_CONFIG_DIR = Path("/config")
if _CONFIG_DIR.exists():
    sys.path.insert(0, str(_CONFIG_DIR))

# ─────────────────── CONFIG ───────────────────
try:
    from config import *
except ImportError:
    print("Warning: config.py not found. Using example values.")
    print("Please copy config.example.py to config.py and update with your credentials.")
    LASTFM_USERS = ["your_lastfm_username"]
    LASTFM_API_KEY = "your_lastfm_api_key"
    HP_API_KEY = "your_headphones_api_key"
    HP_ENDPOINT = "http://your-headphones-server:port"
    MUSIC_SERVICE = "headphones"

# Default configuration values (can be overridden in config.py)
if 'RECENT_MONTHS' not in globals():
    RECENT_MONTHS = 3
if 'MIN_PLAYS' not in globals():
    MIN_PLAYS = 20
if 'REQUEST_LIMIT' not in globals():
    REQUEST_LIMIT = 1/5
if 'MBZ_DELAY' not in globals():
    MBZ_DELAY = 1.1
if 'SIMILAR_MATCH_MIN' not in globals():
    SIMILAR_MATCH_MIN = 0.46
if 'MAX_SIMILAR_PER_ART' not in globals():
    MAX_SIMILAR_PER_ART = 20
if 'MAX_POP_ALBUMS' not in globals():
    MAX_POP_ALBUMS = 5
if 'CACHE_TTL_HOURS' not in globals():
    CACHE_TTL_HOURS = 24
if 'DEBUG_PRINT' not in globals():
    DEBUG_PRINT = True
if 'MUSIC_SERVICE' not in globals():
    MUSIC_SERVICE = "headphones"

# ── Genre Discovery defaults ──
if 'GENRE_DISCOVERY_ENABLED' not in globals():
    GENRE_DISCOVERY_ENABLED = True
if 'GENRE_TOP_N' not in globals():
    GENRE_TOP_N = 5
if 'GENRE_SIMILAR_LIMIT' not in globals():
    GENRE_SIMILAR_LIMIT = 10
if 'GENRE_SCROBBLE_PERIOD' not in globals():
    GENRE_SCROBBLE_PERIOD = "6month"
if 'GENRE_TOP_ARTISTS_LIMIT' not in globals():
    GENRE_TOP_ARTISTS_LIMIT = 200
if 'GENRE_BUCKETS' not in globals():
    GENRE_BUCKETS = {}

# ── Loved Tracks defaults ──
if 'LOVED_TRACKS_ENABLED' not in globals():
    LOVED_TRACKS_ENABLED = True
if 'LOVED_TRACKS_LIMIT' not in globals():
    LOVED_TRACKS_LIMIT = 500
if 'LOVED_STUDIO_ONLY' not in globals():
    LOVED_STUDIO_ONLY = True

# ── Navidrome defaults ──
if 'NAVIDROME_ENABLED' not in globals():
    NAVIDROME_ENABLED = False
if 'NAVIDROME_ENDPOINT' not in globals():
    NAVIDROME_ENDPOINT = ""
if 'NAVIDROME_USERS' not in globals():
    NAVIDROME_USERS = []
if 'DRY_RUN' not in globals():
    DRY_RUN = False
if 'SCHEDULE_MODE' not in globals():
    SCHEDULE_MODE = "daily"
if 'SCHEDULE_HOUR' not in globals():
    SCHEDULE_HOUR = 3
if 'SCHEDULE_DAY_OF_WEEK' not in globals():
    SCHEDULE_DAY_OF_WEEK = 0
if 'SCHEDULE_DAY_OF_MONTH' not in globals():
    SCHEDULE_DAY_OF_MONTH = 1

BAD_SEC = {
    "Compilation", "Live", "Remix", "Soundtrack", "DJ-Mix",
    "Mixtape/Street", "EP", "Single", "Interview", "Audiobook"
}

# ─────────────────── IMPORTS ───────────────────
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
import json
import logging
import os
import sys
import time
import urllib.parse
import requests

from services import MusicServiceFactory, ArtistInfo, AlbumInfo, ServiceError, ConfigurationError
from sources import (
    rate_limited, dprint, lf_request,
    get_artist_top_tags, get_top_artists_by_period,
    get_tag_top_artists, get_loved_tracks,
    NavidromeClient, get_all_starred_artist_names, get_all_starred_albums,
)

SCRIPT_DIR = Path(__file__).resolve().parent
_DATA_DIR = _CONFIG_DIR if _CONFIG_DIR.exists() else SCRIPT_DIR
CACHE_FILE = _DATA_DIR / "lastfm_similar_cache.json"
LOG_DIR = _DATA_DIR / "log"
LOG_FILE = LOG_DIR / "discover.log"
DRY_RUN_LOG_FILE = LOG_DIR / "dry_run.log"
TRIGGER_FILE = _DATA_DIR / "trigger.run"

# ─────────────────── LOGGER ───────────────────
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    level=logging.DEBUG,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE)
    ],
)
log = logging.getLogger("lfm2hp")

logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)
logging.getLogger("requests.packages.urllib3").setLevel(logging.WARNING)

# ── Dry-run clean report logger ──
# Writes only the human-readable "what would change" lines, no noise.
_dry_log = logging.getLogger("lfm2hp.dryrun")
_dry_log.propagate = False
_dry_log.setLevel(logging.INFO)
if DRY_RUN:
    _dry_handler = logging.FileHandler(DRY_RUN_LOG_FILE, mode="w", encoding="utf-8")
    _dry_handler.setFormatter(logging.Formatter("%(message)s"))
    _dry_log.addHandler(_dry_handler)


def dry_log(msg: str) -> None:
    """Log a dry-run action to both the main log and the clean dry-run report file."""
    log.info(msg)
    _dry_log.info(msg)


def dry_section(title: str) -> None:
    """Write a section banner to the dry-run report (no-op when DRY_RUN is False)."""
    if DRY_RUN:
        _dry_log.info("")
        _dry_log.info(f"{'━' * 44}")
        _dry_log.info(f"  {title}")
        _dry_log.info(f"{'━' * 44}")


# ─────────────────── MusicBrainz ───────────────────
@rate_limited(MBZ_DELAY)
def mbz_request(path, **params):
    """MusicBrainz API call with robust retry handling."""
    base = "https://musicbrainz.org/ws/2/"
    params.setdefault("fmt", "json")

    headers = {"User-Agent": "DiscoveryLastFM/2.2.0 ( genrediscovery@example.com )"}

    max_retries = 3
    retry_delay = 2

    for attempt in range(max_retries):
        try:
            dprint(f"MBZ → {path} (attempt {attempt+1}/{max_retries})")
            r = requests.get(base + path, params=params, headers=headers, timeout=30)
            dprint(f"MBZ ← {r.status_code}")

            if r.status_code == 429 and attempt < max_retries - 1:
                wait_time = int(r.headers.get('Retry-After', retry_delay * 2))
                log.warning(f"Rate limit hit (MusicBrainz), waiting {wait_time}s")
                time.sleep(wait_time)
                continue

            if r.status_code != 200:
                if attempt < max_retries - 1:
                    log.warning(f"MusicBrainz HTTP {r.status_code}, attempt {attempt+1}/{max_retries}")
                    time.sleep(retry_delay * (attempt + 1))
                    continue
                else:
                    log.warning(f"MusicBrainz HTTP {r.status_code}: {r.text[:200]}")
                    return None

            try:
                return r.json()
            except Exception:
                if attempt < max_retries - 1:
                    log.warning(f"MusicBrainz invalid JSON, attempt {attempt+1}/{max_retries}")
                    time.sleep(retry_delay)
                    continue
                else:
                    log.warning(f"MusicBrainz invalid JSON: {r.text[:200]}")
                    return None

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, ConnectionResetError) as e:
            if attempt < max_retries - 1:
                log.warning(f"MusicBrainz connection error: {e}, attempt {attempt+1}/{max_retries}")
                time.sleep(retry_delay * (attempt + 1))
                continue
            else:
                log.error(f"MusicBrainz connection failed after {max_retries} attempts: {e}")
                return None
        except Exception as e:
            if attempt < max_retries - 1:
                log.warning(f"MusicBrainz error: {e}, attempt {attempt+1}/{max_retries}")
                time.sleep(retry_delay * (attempt + 1))
            else:
                log.error(f"MusicBrainz error after {max_retries} attempts: {e}")
                return None

    return None


# ────────────── CORE FUNCTIONS ──────────────
def load_cache():
    """Load cache from JSON file."""
    try:
        with open(CACHE_FILE, "r") as f:
            cache = json.load(f)

        if "added_albums" in cache and isinstance(cache["added_albums"], list):
            cache["added_albums"] = set(cache["added_albums"])
        elif "added_albums" not in cache:
            cache["added_albums"] = set()

        return cache
    except Exception:
        return {"similar_cache": {}, "added_albums": set()}


def save_cache(cache):
    """Save cache to JSON file with atomic write."""
    try:
        cache_to_save = {}
        for key, value in cache.items():
            if key == "added_albums" and isinstance(value, set):
                cache_to_save[key] = list(value)
            else:
                cache_to_save[key] = value

        temp_file = CACHE_FILE.with_suffix('.tmp')
        with open(temp_file, "w") as f:
            json.dump(cache_to_save, f, indent=2, separators=(',', ':'))

        temp_file.replace(CACHE_FILE)

    except Exception as e:
        log.error(f"Cache save error: {e}")
        if 'temp_file' in locals() and temp_file.exists():
            temp_file.unlink()


def recent_artists():
    """Fetch recently played artists across all LASTFM_USERS, merging play counts."""
    end = int(time.time())
    start = end - (RECENT_MONTHS * 30 * 24 * 3600)

    artist_plays = defaultdict(int)
    processed_tracks = 0

    for username in LASTFM_USERS:
        page = 1
        total_pages = 1
        while page <= total_pages and page <= 10:
            js = lf_request("user.getRecentTracks", user=username,
                             from_=start, to_=end, limit=200, page=page)
            if not js:
                break

            recenttracks = js.get("recenttracks", {})
            tracks = recenttracks.get("track", [])

            if page == 1:
                attr = recenttracks.get("@attr", {})
                total_pages = min(int(attr.get("totalPages", 1)), 10)
                log.info(f"[{username}] Processing {attr.get('total', 0)} recent tracks across {total_pages} pages")

            for t in tracks:
                if isinstance(t, dict):
                    artist = t.get("artist", {})
                    name = artist.get("#text", "") if isinstance(artist, dict) else str(artist)
                    if name:
                        artist_plays[name] += 1
                        processed_tracks += 1

            page += 1

    log.info(f"Processed {processed_tracks} tracks from {len(artist_plays)} unique artists across {len(LASTFM_USERS)} account(s)")

    result = []
    qualifying_artists = [(name, plays) for name, plays in artist_plays.items() if plays >= MIN_PLAYS]
    log.info(f"Found {len(qualifying_artists)} artists with ≥{MIN_PLAYS} plays")

    for name, plays in qualifying_artists:
        js = lf_request("artist.getInfo", artist=name)
        if js:
            mbid = js.get("artist", {}).get("mbid")
            if mbid:
                result.append((name, mbid))
                log.debug(f"Artist {name}: {plays} plays, MBID: {mbid}")

    log.info(f"Final result: {len(result)} artists with valid MBIDs")
    return result


def cached_similars(cache, aid):
    """Return cached similar artists for aid if within TTL, else None."""
    if aid not in cache["similar_cache"]:
        return None

    entry = cache["similar_cache"][aid]
    age_hours = (time.time() - entry["ts"]) / 3600

    if age_hours > CACHE_TTL_HOURS:
        dprint(f"Cache expired for {aid} ({age_hours:.1f}h)")
        return None

    return entry["data"]


def top_albums(artist_mbid):
    """Fetch top album MBIDs for an artist, filtered to MAX_POP_ALBUMS."""
    js = lf_request("artist.getTopAlbums", mbid=artist_mbid, limit=MAX_POP_ALBUMS * 2)
    if not js:
        return []

    albums = js.get("topalbums", {}).get("album", [])
    return [a.get("mbid") for a in albums if a.get("mbid")][:MAX_POP_ALBUMS]


def release_to_rg(rel_id):
    """Convert a Release MBID to its Release Group MBID."""
    if not rel_id:
        return None

    js = mbz_request(f"release/{rel_id}", inc="release-groups")
    if js and "release-group" in js:
        return js["release-group"]["id"]
    return None


def is_studio_rg(rg_id):
    """Return True if the release group is a studio album, False if not, None if unknown."""
    if not rg_id:
        return None

    js = mbz_request(f"release-group/{rg_id}")
    if not js:
        return None

    primary = js.get("primary-type")
    if primary != "Album":
        return False

    secondary = js.get("secondary-types", [])
    if any(s in BAD_SEC for s in secondary):
        return False

    return True


def search_release_group_mbid(artist_name, album_title):
    """Search MusicBrainz for a release group by artist + album title. Returns rg_id or None."""
    a = artist_name.replace('"', '\\"')
    t = album_title.replace('"', '\\"')
    js = mbz_request("release-group", query=f'artist:"{a}" AND releasegroup:"{t}"', limit=1)
    if not js:
        return None
    results = js.get("release-groups", [])
    return results[0].get("id") if results else None


def release_group_info(rel_id):
    """Return (rg_id, is_studio) from a single MBZ request instead of two.

    The release/{id}?inc=release-groups response already contains the full
    release-group object, so we skip the second GET /release-group/{id} call.
    """
    if not rel_id:
        return None, None
    js = mbz_request(f"release/{rel_id}", inc="release-groups")
    if not js or "release-group" not in js:
        return None, None
    rg = js["release-group"]
    rg_id = rg.get("id")
    if rg.get("primary-type") != "Album":
        return rg_id, False
    if any(s in BAD_SEC for s in rg.get("secondary-types", [])):
        return rg_id, False
    return rg_id, True


# ────────────── SHARED ALBUM PROCESSING ──────────────
def process_similar_artist(sim_name, sid, music_service, cache, added_albums,
                            seen, fallback_ids, counters, context=""):
    """
    Shared logic: adds a similar artist to the music service and processes
    their top albums. Used by both sync() and genre_sync().

    counters is a dict with keys: success, error, skipped
    context is an optional string for log messages (e.g. genre name)
    """
    prefix = f"[{context}] " if context else ""

    if not sid or sid in seen:
        return
    seen.add(sid)

    log.info(f"{prefix}Processing similar artist: {sim_name} ({sid})")

    similar_artist_info = ArtistInfo(mbid=sid, name=sim_name)
    if DRY_RUN:
        dry_log(f"{prefix}[DRY RUN] Would add artist: {sim_name}")
    else:
        try:
            if not music_service.add_artist(similar_artist_info):
                log.error(f"{prefix}Failed to add similar artist {sim_name} ({sid})")
                counters["error"] += 1
                return
        except (ServiceError, Exception) as e:
            log.error(f"{prefix}Error adding similar artist {sim_name}: {e}")
            counters["error"] += 1
            return

        music_service.refresh_artist(sid)

    albums = top_albums(sid)
    log.info(f"{prefix}Found {len(albums)} albums for {sim_name}")

    js_albums = lf_request("artist.getTopAlbums", mbid=sid, limit=MAX_POP_ALBUMS * 2)
    albums_raw = js_albums.get("topalbums", {}).get("album", []) if js_albums else []
    mbid_to_title = {a.get("mbid"): a.get("name") for a in albums_raw if a.get("mbid")}

    for rel_id in albums:
        rg_id, studio = release_group_info(rel_id)
        title = mbid_to_title.get(rel_id, rel_id)

        if not rg_id:
            log.info(f"{prefix}Fallback: album without MBID (artist: {sim_name}, title: {title})")
            continue

        if music_service.album_exists(rg_id, added_albums) or music_service.album_exists(rel_id, added_albums):
            log.debug(f"{prefix}Album {rel_id} already exists — skipping")
            counters["skipped"] += 1
            continue
        if studio is False:
            log.debug(f"{prefix}Album {rel_id} is not a studio album — skipping")
            continue

        try:
            album_info = AlbumInfo(
                mbid=rg_id if studio else rel_id,
                title=title,
                artist_mbid=sid,
                artist_name=sim_name
            )

            if studio is None:
                album_info.mbid = rel_id
                fallback_ids.append(rel_id)

            if DRY_RUN:
                label = " (fallback)" if studio is None else ""
                dry_log(f"{prefix}[DRY RUN]   → Would add album{label}: {title}")
                counters["success"] += 1
            else:
                if studio is None:
                    log.info(f"{prefix}Adding album (fallback) {rel_id}")
                else:
                    log.info(f"{prefix}Adding album {rg_id}")
                try:
                    if music_service.add_album(album_info):
                        if music_service.queue_album(album_info, force_new=True):
                            added_albums.add(album_info.mbid)
                            counters["success"] += 1
                        else:
                            log.warning(f"{prefix}Album {album_info.title} added but queue failed")
                    else:
                        counters["error"] += 1
                        log.error(f"{prefix}Failed to add album {album_info.title}")
                except (ServiceError, Exception) as e:
                    counters["error"] += 1
                    log.error(f"{prefix}Error adding album {album_info.title}: {e}")

        except Exception as e:
            counters["error"] += 1
            log.error(f"{prefix}Error processing album {rel_id or rg_id}: {e}")


# ────────────── GENRE DISCOVERY HELPERS ──────────────
def resolve_genre(tags, buckets):
    """
    Map a list of Last.fm tags to a genre bucket name.
    Tries each tag against each bucket in order; first match wins.
    Falls back to raw first tag, or 'unknown'.
    """
    if not buckets:
        return tags[0] if tags else "unknown"

    lower_buckets = {
        bucket: [t.lower() for t in tag_list]
        for bucket, tag_list in buckets.items()
    }
    for tag in tags:
        for bucket_name, bucket_tags in lower_buckets.items():
            if tag.lower() in bucket_tags:
                return bucket_name

    return tags[0] if tags else "unknown"


def group_artists_by_genre(top_artists, buckets):
    """
    Fetch Last.fm tags per artist and group into genres.
    Returns dict: genre_name -> list of artist dicts (sorted by playcount desc).
    """
    genre_groups = defaultdict(list)
    total = len(top_artists)

    for i, artist in enumerate(top_artists, 1):
        name = artist.get("name", "").strip()
        if not name:
            continue
        tags = get_artist_top_tags(name)
        genre = resolve_genre(tags, buckets)
        genre_groups[genre].append(artist)

        if i % 25 == 0 or i == total:
            log.info(f"Genre tagging: {i}/{total} artists processed")

    # Sort each genre by playcount descending
    for genre in genre_groups:
        genre_groups[genre].sort(
            key=lambda a: int(a.get("playcount", 0)), reverse=True
        )

    return dict(genre_groups)


# ────────────── PHASE: LOVED TRACKS ──────────────
def phase_loved_tracks(music_service):
    """
    Priority phase: fetch loved/starred artists from Last.fm and optionally
    Navidrome, then ensure all of them are in the music service.
    Also adds the specific albums that contain each loved track.

    Runs before genre discovery so loved artists are always prioritized.
    Returns count of newly added artists.
    """
    log.info("══════════════════════════════════════════")
    log.info("Phase 1: Loved / Starred tracks (priority)")
    log.info("══════════════════════════════════════════")
    dry_section("Phase 1 — Loved / Starred Tracks")

    loved_tracks = get_loved_tracks(LOVED_TRACKS_LIMIT)
    log.info(f"Last.fm loved tracks: {len(loved_tracks)} unique tracks across {len(LASTFM_USERS)} account(s)")

    # Unique artists from loved tracks
    loved_artist_names: set[str] = {artist for artist, _ in loved_tracks}

    # ── Navidrome (optional) ──
    nav_starred_albums = []
    if NAVIDROME_ENABLED and NAVIDROME_ENDPOINT and NAVIDROME_USERS:
        nav_artists = get_all_starred_artist_names(NAVIDROME_ENDPOINT, NAVIDROME_USERS)
        log.info(f"Navidrome starred: {len(nav_artists)} artists across {len(NAVIDROME_USERS)} account(s)")
        loved_artist_names |= nav_artists
        nav_starred_albums = get_all_starred_albums(NAVIDROME_ENDPOINT, NAVIDROME_USERS)
        log.info(f"Navidrome starred albums: {len(nav_starred_albums)}")

    log.info(f"Total loved/starred artists to process: {len(loved_artist_names)}")

    # ── Step 1: add all unique artists ──
    artist_mbids: dict[str, str] = {}
    added = 0
    for name in sorted(loved_artist_names):
        try:
            js = lf_request("artist.getInfo", artist=name)
            mbid = js.get("artist", {}).get("mbid", "") if js else ""
            artist_mbids[name] = mbid
            artist_info = ArtistInfo(mbid=mbid, name=name)

            if DRY_RUN:
                dry_log(f"  [loved] Would add artist: {name}")
                added += 1
            else:
                result = music_service.add_artist(artist_info)
                if result:
                    log.info(f"[loved] Added artist: {name}")
                    added += 1
        except (ServiceError, Exception) as e:
            log.warning(f"[loved] Could not add artist {name}: {e}")

    # ── Step 2: add specific albums that contain loved tracks ──
    log.info(f"Fetching album info for {len(loved_tracks)} loved tracks...")
    added_albums_loved: set[str] = set()

    for artist_name, track_name in loved_tracks:
        try:
            js = lf_request("track.getInfo", artist=artist_name, track=track_name)
            if not js:
                continue
            album = js.get("track", {}).get("album", {})
            rel_id = album.get("mbid", "")
            title = album.get("title", "")
            if not rel_id:
                if not title:
                    log.debug(f"[loved] No album info for '{track_name}' by {artist_name} — skipping")
                    continue
                rg_id = search_release_group_mbid(artist_name, title)
                if not rg_id:
                    log.debug(f"[loved] No MBz match for album '{title}' by {artist_name} — skipping")
                    continue
                studio = is_studio_rg(rg_id)
                if LOVED_STUDIO_ONLY and not studio:
                    log.debug(f"[loved] '{title}' by {artist_name} is not a studio album — skipping")
                    continue
                mbid_to_add = rg_id
            else:
                rg_id, studio = release_group_info(rel_id)
                if not rg_id:
                    log.debug(f"[loved] Could not resolve release group for '{title}' — skipping")
                    continue
                if LOVED_STUDIO_ONLY and studio is False:
                    log.debug(f"[loved] '{title}' by {artist_name} is not a studio album — skipping")
                    continue
                mbid_to_add = rg_id
            if mbid_to_add in added_albums_loved or music_service.album_exists(mbid_to_add, set()):
                log.debug(f"[loved] Album '{title}' already queued — skipping")
                continue

            artist_mbid = artist_mbids.get(artist_name, "")
            album_info = AlbumInfo(
                mbid=mbid_to_add,
                title=title,
                artist_mbid=artist_mbid,
                artist_name=artist_name,
            )

            if DRY_RUN:
                dry_log(f"  [loved] Would add album: {title} (by {artist_name})")
                added_albums_loved.add(mbid_to_add)
            else:
                if music_service.add_album(album_info):
                    music_service.queue_album(album_info, force_new=True)
                    added_albums_loved.add(mbid_to_add)
                    log.info(f"[loved] Added album: {title} (by {artist_name})")

        except (ServiceError, Exception) as e:
            log.warning(f"[loved] Could not add album for '{track_name}' by {artist_name}: {e}")

    # ── Step 3: add starred albums from Navidrome ──
    if nav_starred_albums:
        log.info(f"Processing {len(nav_starred_albums)} starred Navidrome albums...")
        for nav_album in nav_starred_albums:
            title = nav_album["title"]
            artist_name = nav_album["artist"]
            rel_id = nav_album["mbid"]
            try:
                if rel_id:
                    rg_id, studio = release_group_info(rel_id)
                    mbid_to_add = rg_id if rg_id and studio is not False else rel_id
                else:
                    # No MBID from Navidrome — skip (can't look up without an ID)
                    log.debug(f"[navidrome] No MBID for '{title}' by {artist_name} — skipping")
                    continue

                if mbid_to_add in added_albums_loved or music_service.album_exists(mbid_to_add, set()):
                    log.debug(f"[navidrome] Album '{title}' already queued — skipping")
                    continue

                artist_mbid = artist_mbids.get(artist_name, "")
                album_info = AlbumInfo(
                    mbid=mbid_to_add,
                    title=title,
                    artist_mbid=artist_mbid,
                    artist_name=artist_name,
                )

                if DRY_RUN:
                    dry_log(f"  [navidrome] Would add album: {title} (by {artist_name})")
                    added_albums_loved.add(mbid_to_add)
                else:
                    if music_service.add_album(album_info):
                        music_service.queue_album(album_info, force_new=True)
                        added_albums_loved.add(mbid_to_add)
                        log.info(f"[navidrome] Added album: {title} (by {artist_name})")

            except (ServiceError, Exception) as e:
                log.warning(f"[navidrome] Could not add album '{title}' by {artist_name}: {e}")

    log.info(f"Phase 1 complete: {added} artists and {len(added_albums_loved)} albums added from loved/starred tracks")
    return added


# ────────────── MUSIC SERVICE INTEGRATION ──────────────
def validate_configuration():
    """Validate configuration for all services with detailed checks."""
    config_dict = {k: v for k, v in globals().items() if k.isupper()}
    service_type = config_dict.get("MUSIC_SERVICE", "headphones").lower()

    log.info("Starting configuration validation...")

    required_base = ["LASTFM_USERS", "LASTFM_API_KEY"]
    missing_base = [k for k in required_base if not config_dict.get(k)]
    if missing_base:
        raise ConfigurationError(f"Missing base configuration: {missing_base}")

    numeric_params = {
        "RECENT_MONTHS": (1, 12),
        "MIN_PLAYS": (1, 1000),
        "MAX_SIMILAR_PER_ART": (1, 100),
        "MAX_POP_ALBUMS": (1, 50),
        "CACHE_TTL_HOURS": (1, 168),
    }

    for param, (min_val, max_val) in numeric_params.items():
        value = config_dict.get(param)
        if value is not None:
            if not isinstance(value, (int, float)) or not (min_val <= value <= max_val):
                raise ConfigurationError(
                    f"{param} must be between {min_val} and {max_val}, got {value}"
                )

    request_limit = config_dict.get("REQUEST_LIMIT", 1/5)
    if request_limit <= 0 or request_limit > 10:
        raise ConfigurationError(f"REQUEST_LIMIT must be between 0 and 10, got {request_limit}")

    mbz_delay = config_dict.get("MBZ_DELAY", 1.1)
    if mbz_delay < 0.5 or mbz_delay > 10:
        raise ConfigurationError(f"MBZ_DELAY must be between 0.5 and 10, got {mbz_delay}")

    if not MusicServiceFactory.validate_service_config(service_type, config_dict):
        available = ", ".join(MusicServiceFactory.get_available_services())
        raise ConfigurationError(
            f"Invalid configuration for {service_type}. Available services: {available}"
        )

    genre_buckets = config_dict.get("GENRE_BUCKETS", {})
    if not isinstance(genre_buckets, dict):
        raise ConfigurationError("GENRE_BUCKETS must be a dict")

    log.info(f"Configuration validated successfully for {service_type}")
    log.info(f"- Discovery scope: {config_dict.get('RECENT_MONTHS', 3)} months, {config_dict.get('MIN_PLAYS', 20)} min plays")
    log.info(f"- Rate limits: LastFM {request_limit}/s, MusicBrainz {mbz_delay}s delay")
    log.info(f"- Processing limits: {config_dict.get('MAX_SIMILAR_PER_ART', 20)} similar artists, {config_dict.get('MAX_POP_ALBUMS', 5)} albums each")

    if config_dict.get("GENRE_DISCOVERY_ENABLED", True):
        log.info(f"- Genre discovery: ENABLED (period={config_dict.get('GENRE_SCROBBLE_PERIOD', '6month')}, "
                 f"top_n={config_dict.get('GENRE_TOP_N', 5)}, buckets={len(genre_buckets)})")
    else:
        log.info("- Genre discovery: DISABLED (standard discovery active)")

    if config_dict.get("LOVED_TRACKS_ENABLED", True):
        nav = "+ Navidrome" if config_dict.get("NAVIDROME_ENABLED") else ""
        log.info(f"- Loved tracks phase: ENABLED (Last.fm {nav})")
    else:
        log.info("- Loved tracks phase: DISABLED")


# ────────────── GENRE SYNC ──────────────
def genre_sync(music_service, cache, added_albums):
    """
    Genre-aware discovery phase.

    Flow per genre:
      1. Sort genre artists by playcount, take top GENRE_TOP_N
      2. Fetch similar artists for each
      3. Fallback to tag.getTopArtists if no similar artists found
      4. Process albums for each candidate
    """
    log.info("══════════════════════════════════════════")
    log.info("Phase 2 (Genre): Genre-aware discovery")
    log.info("══════════════════════════════════════════")
    dry_section("Phase 2 — Genre-Aware Discovery")

    top_artists = get_top_artists_by_period(
        period=GENRE_SCROBBLE_PERIOD,
        limit=GENRE_TOP_ARTISTS_LIMIT,
    )

    if not top_artists:
        log.warning("No top artists returned from Last.fm — skipping genre discovery")
        return 0, 0, 0

    log.info(f"Grouping {len(top_artists)} artists by genre...")
    genre_groups = group_artists_by_genre(top_artists, GENRE_BUCKETS)
    log.info(f"Genres detected: {list(genre_groups.keys())}")

    seen = set()
    fallback_ids = []
    counters = {"success": 0, "error": 0, "skipped": 0}

    for genre, artists in genre_groups.items():
        log.info(f"── Genre [{genre}]: {len(artists)} artists ──")

        top_n = artists[:GENRE_TOP_N]
        log.info(f"[{genre}] Top {len(top_n)}: {[a['name'] for a in top_n]}")

        candidates = []
        for artist in top_n:
            name = artist.get("name", "")
            mbid = artist.get("mbid", "")

            if mbid:
                js = lf_request("artist.getSimilar", mbid=mbid, limit=GENRE_SIMILAR_LIMIT)
            else:
                js = lf_request("artist.getSimilar", artist=name, limit=GENRE_SIMILAR_LIMIT)

            sims = js.get("similarartists", {}).get("artist", []) if js else []

            if sims and mbid:
                cache.setdefault("similar_cache", {})[mbid] = {
                    "ts": time.time(), "data": sims
                }

            candidates.extend(sims)
            log.debug(f"[{genre}] Similar to {name}: {[s['name'] for s in sims[:3]]}")

        if not candidates:
            fallback_tag = (
                GENRE_BUCKETS[genre][0].lower()
                if genre in GENRE_BUCKETS and GENRE_BUCKETS[genre]
                else genre.lower()
            )
            log.info(f"[{genre}] No similar artists — fallback to tag: '{fallback_tag}'")
            tag_artists = get_tag_top_artists(fallback_tag, limit=GENRE_SIMILAR_LIMIT * GENRE_TOP_N)
            candidates = tag_artists

        seen_mbids = {}
        deduped = []
        for c in candidates:
            cid = c.get("mbid")
            cname = c.get("name", "")
            if not cid or cid in seen_mbids:
                continue
            seen_mbids[cid] = True
            deduped.append((cname, cid, float(c.get("match", 0))))

        log.info(f"[{genre}] {len(deduped)} unique candidates")

        for sim_name, sid, sim_match in deduped:
            if sim_match > 0 and sim_match < SIMILAR_MATCH_MIN:
                log.debug(f"[{genre}] Skip {sim_name}: match too low ({sim_match:.2f})")
                continue

            process_similar_artist(
                sim_name=sim_name,
                sid=sid,
                music_service=music_service,
                cache=cache,
                added_albums=added_albums,
                seen=seen,
                fallback_ids=fallback_ids,
                counters=counters,
                context=genre,
            )

    if fallback_ids and not DRY_RUN:
        log.info(f"Force-searching {len(fallback_ids)} fallback albums...")
        try:
            music_service.force_search()
        except ServiceError as e:
            log.error(f"Force search failed: {e}")

    return counters["success"], counters["error"], counters["skipped"]


# ────────────── STANDARD SYNC (used when genre discovery is disabled) ──────────────
def sync(music_service, cache, added_albums):
    """
    Standard sync — used when GENRE_DISCOVERY_ENABLED = False.
    Identical behaviour to v2.1.x.
    """
    log.info("══════════════════════════════════════════")
    log.info("Phase 2 (Standard): Artist-based discovery")
    log.info("══════════════════════════════════════════")
    dry_section("Phase 2 — Standard Artist-Based Discovery")

    recent = recent_artists()
    log.info("Analysing %d artists...", len(recent))

    seen = set()
    fallback_ids = []
    counters = {"success": 0, "error": 0, "skipped": 0}

    for name, aid in recent:
        if not aid:
            continue

        log.info(f"Processing artist: {name} ({aid})")
        artist_info = ArtistInfo(mbid=aid, name=name)

        if DRY_RUN:
            dry_log(f"[DRY RUN] Would add artist: {name}")
        else:
            try:
                if not music_service.add_artist(artist_info):
                    log.error(f"Failed to add artist {name} ({aid})")
                    counters["error"] += 1
                    continue
            except (ServiceError, Exception) as e:
                log.error(f"Error adding artist {name}: {e}")
                counters["error"] += 1
                continue

            music_service.refresh_artist(aid)

        sims = cached_similars(cache, aid)
        if not sims:
            log.info(f"Fetching similar artists for {name}...")
            js = lf_request("artist.getSimilar", mbid=aid, limit=50)
            sims = js.get("similarartists", {}).get("artist", []) if js else []
            if sims:
                cache["similar_cache"][aid] = {"ts": time.time(), "data": sims}

        proc = 0
        for s in sims:
            sim_name = s.get("name", "Unknown")
            sid = s.get("mbid")
            sim_match = float(s.get("match", 0))

            if proc >= MAX_SIMILAR_PER_ART:
                break
            if not sid or sid in seen:
                continue
            if sim_match < SIMILAR_MATCH_MIN:
                continue

            proc += 1
            process_similar_artist(
                sim_name=sim_name,
                sid=sid,
                music_service=music_service,
                cache=cache,
                added_albums=added_albums,
                seen=seen,
                fallback_ids=fallback_ids,
                counters=counters,
            )

    if fallback_ids and not DRY_RUN:
        log.info(f"Force-searching {len(fallback_ids)} fallback albums...")
        try:
            music_service.force_search()
        except ServiceError as e:
            log.error(f"Force search failed: {e}")

    return counters["success"], counters["error"], counters["skipped"]


# ────────────── MAIN ORCHESTRATOR ──────────────
def run_discovery():
    """
    Main discovery orchestrator.

    Execution order:
      1. Loved/Starred tracks phase (if LOVED_TRACKS_ENABLED)
      2a. Genre-aware discovery     (if GENRE_DISCOVERY_ENABLED)
      2b. Standard discovery        (if GENRE_DISCOVERY_ENABLED = False)
    """
    start_time = time.time()

    if DRY_RUN:
        log.warning("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        log.warning("DRY RUN MODE — no changes will be made to the music service")
        log.warning(f"Clean report will be written to: {DRY_RUN_LOG_FILE}")
        log.warning("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        _dry_log.info(f"=== DRY RUN REPORT ===")
        _dry_log.info(f"Started : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        _dry_log.info(f"Accounts: {', '.join(LASTFM_USERS)}")
        _dry_log.info(f"Service : {MUSIC_SERVICE}")

    try:
        config_dict = {k: v for k, v in globals().items() if k.isupper()}
        service_type = config_dict.get("MUSIC_SERVICE", "headphones")

        music_service = MusicServiceFactory.create_service(service_type, config_dict)
        log.info(f"Using {service_type} service: {music_service.get_service_info()}")

        cache = load_cache()
        added_albums = set(cache.get("added_albums", []))

        total_loved = 0
        total_success = 0
        total_error = 0
        total_skipped = 0

        # ── Phase 1: Loved / Starred tracks (priority) ──
        if LOVED_TRACKS_ENABLED:
            total_loved = phase_loved_tracks(music_service)
        else:
            log.info("Loved tracks phase: DISABLED (set LOVED_TRACKS_ENABLED = True to enable)")

        # ── Phase 2: Discovery ──
        if GENRE_DISCOVERY_ENABLED:
            s, e, sk = genre_sync(music_service, cache, added_albums)
        else:
            log.info("Genre discovery: DISABLED (set GENRE_DISCOVERY_ENABLED = True to enable)")
            s, e, sk = sync(music_service, cache, added_albums)

        total_success += s
        total_error += e
        total_skipped += sk

        # ── Save cache ──
        cache["added_albums"] = list(added_albums)
        save_cache(cache)

        elapsed = time.time() - start_time
        log.info("══════════════════════════════════════════")
        log.info("Discovery completed in %.1f minutes.", elapsed / 60)
        log.info("- Loved artists added: %d", total_loved)
        log.info("- Albums added:        %d", total_success)
        log.info("- Errors:              %d", total_error)
        log.info("- Skipped:             %d", total_skipped)
        log.info("══════════════════════════════════════════")

        if DRY_RUN:
            _dry_log.info("")
            _dry_log.info(f"{'━' * 44}")
            _dry_log.info("  SUMMARY")
            _dry_log.info(f"{'━' * 44}")
            _dry_log.info(f"  Loved artists : {total_loved}")
            _dry_log.info(f"  Albums        : {total_success}")
            _dry_log.info(f"  Errors        : {total_error}")
            _dry_log.info(f"  Skipped       : {total_skipped}")
            _dry_log.info(f"  Elapsed       : {elapsed/60:.1f} min")

    except (ServiceError, ConfigurationError) as e:
        log.error(f"Service error: {e}")
        raise
    except Exception as e:
        log.error(f"Unexpected error: {e}")
        raise
    finally:
        try:
            cache["added_albums"] = list(added_albums)
            save_cache(cache)
        except Exception:
            pass
        import gc
        gc.collect()
        log.debug("Memory cleanup completed")


# ────────────── SCHEDULER / DAEMON ──────────────
def next_run_time():
    """Return the next datetime when discovery should run, based on SCHEDULE_MODE."""
    now = datetime.now()
    hour = SCHEDULE_HOUR

    if SCHEDULE_MODE == "daily":
        candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    if SCHEDULE_MODE == "weekly":
        days_ahead = SCHEDULE_DAY_OF_WEEK - now.weekday()
        if days_ahead < 0 or (days_ahead == 0 and now.hour >= hour):
            days_ahead += 7
        candidate = (now + timedelta(days=days_ahead)).replace(
            hour=hour, minute=0, second=0, microsecond=0
        )
        return candidate

    if SCHEDULE_MODE == "monthly":
        try:
            candidate = now.replace(day=SCHEDULE_DAY_OF_MONTH, hour=hour, minute=0, second=0, microsecond=0)
        except ValueError:
            candidate = now.replace(day=28, hour=hour, minute=0, second=0, microsecond=0)
        if candidate <= now:
            if now.month == 12:
                candidate = candidate.replace(year=now.year + 1, month=1)
            else:
                candidate = candidate.replace(month=now.month + 1)
        return candidate

    return None  # manual


def run_daemon():
    """Run discovery immediately, then loop on schedule or manual trigger."""
    log.info(f"Daemon started (schedule: {SCHEDULE_MODE}, trigger file: {TRIGGER_FILE})")

    def _run():
        try:
            validate_configuration()
            run_discovery()
        except Exception as e:
            log.error(f"Discovery run failed: {e}")

    _run()

    if SCHEDULE_MODE == "manual":
        log.info("Schedule mode: MANUAL — waiting for trigger file (python DiscoveryLastFM.py --trigger)")
        while True:
            if TRIGGER_FILE.exists():
                TRIGGER_FILE.unlink(missing_ok=True)
                log.info("Manual trigger detected — starting discovery run...")
                _run()
            time.sleep(60)
    else:
        while True:
            nxt = next_run_time()
            log.info(f"Next scheduled run: {nxt.strftime('%Y-%m-%d %H:%M')}")
            while True:
                if TRIGGER_FILE.exists():
                    TRIGGER_FILE.unlink(missing_ok=True)
                    log.info("Manual trigger detected — starting discovery run early...")
                    break
                if datetime.now() >= nxt:
                    log.info("Scheduled run time reached — starting discovery run...")
                    break
                time.sleep(60)
            _run()


# ────────────── UPDATE SYSTEM ──────────────
def handle_update_command():
    """Handle the --update command."""
    from utils.updater import create_updater_from_config, get_current_version

    config_dict = {k: v for k, v in globals().items() if k.isupper()}
    config_dict["PROJECT_ROOT"] = os.path.dirname(os.path.abspath(__file__))

    updater = create_updater_from_config(config_dict)

    print(f"DiscoveryLastFM Auto-Update System")
    print(f"Current version: {get_current_version()}")
    print(f"Repository: {updater.repo_owner}/{updater.repo_name}")
    print()

    print("Checking for updates...")
    release_info = updater.check_for_updates()

    if not release_info:
        print("✅ Already up to date!")
        return

    print(f"🆕 Update available: {release_info['version']}")
    print(f"   Release: {release_info['name']}")
    print(f"   Published: {release_info['published_at']}")

    if release_info.get('prerelease'):
        print("   ⚠️  This is a pre-release version")

    print()
    print("Release Notes:")
    print("-" * 50)
    print(release_info['body'][:500] + ("..." if len(release_info['body']) > 500 else ""))
    print("-" * 50)
    print()

    while True:
        response = input("Do you want to install this update? [y/N]: ").strip().lower()
        if response in ['y', 'yes']:
            break
        elif response in ['n', 'no', '']:
            print("Update cancelled.")
            return
        else:
            print("Please enter 'y' or 'n'")

    print("\n🚀 Starting update process...")
    success = updater.perform_update(release_info)

    if success:
        print("✅ Update completed successfully!")
        print(f"   Updated to version: {release_info['version']}")
        print("   Your configuration and cache files have been preserved.")
        print("\n🔄 Please restart the application to use the new version.")
    else:
        print("❌ Update failed!")
        print("   Your previous version has been restored.")
        print("   Check the logs for more details.")


def handle_update_status():
    from utils.updater import create_updater_from_config

    config_dict = {k: v for k, v in globals().items() if k.isupper()}
    config_dict["PROJECT_ROOT"] = os.path.dirname(os.path.abspath(__file__))

    updater = create_updater_from_config(config_dict)
    status = updater.get_update_status()

    print("DiscoveryLastFM Update Status")
    print("=" * 40)
    print(f"Current Version: {status['current_version']}")
    print(f"Repository: {status['repo']}")
    print(f"Auto-update: {'Enabled' if status['auto_update_enabled'] else 'Disabled'}")

    if status['last_check']:
        print(f"Last Check: {status['last_check']}")
    else:
        print("Last Check: Never")

    if status['available_version']:
        if status['available_version'] != status['current_version']:
            print(f"Available Version: {status['available_version']} ⚠️")
        else:
            print(f"Available Version: {status['available_version']} ✅")

    if status['failed_attempts'] > 0:
        print(f"Failed Attempts: {status['failed_attempts']} ❌")

    print(f"Backups Available: {status['backup_count']}")

    if status['next_check']:
        print(f"Next Check: {status['next_check']}")


def handle_backups_list():
    from utils.updater import create_updater_from_config

    config_dict = {k: v for k, v in globals().items() if k.isupper()}
    config_dict["PROJECT_ROOT"] = os.path.dirname(os.path.abspath(__file__))

    updater = create_updater_from_config(config_dict)
    backups = updater.list_backups()

    if not backups:
        print("No backups found.")
        return

    print("Available Backups")
    print("=" * 60)
    print(f"{'Version':<10} {'Date':<20} {'Size':<10} {'Status'}")
    print("-" * 60)

    for backup in backups:
        status = "✅ OK" if backup['exists'] else "❌ Missing"
        timestamp = backup['timestamp']
        try:
            dt = datetime.strptime(timestamp, "%Y%m%d_%H%M%S")
            date_str = dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            date_str = timestamp

        print(f"{backup['version']:<10} {date_str:<20} {backup['size_mb']} MB{'':5} {status}")


def parse_cli_args():
    import argparse

    parser = argparse.ArgumentParser(
        description='DiscoveryLastFM - Music Discovery & Auto-Queue System',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 DiscoveryLastFM.py                 # Run discovery (loved tracks + genre/standard)
  python3 DiscoveryLastFM.py --update        # Check and install updates
  python3 DiscoveryLastFM.py --update-status # Show update status
  python3 DiscoveryLastFM.py --list-backups  # List available backups
  python3 DiscoveryLastFM.py --version       # Show current version
        """
    )

    parser.add_argument('--daemon', action='store_true',
                        help='Run continuously: discover on startup, then on schedule')
    parser.add_argument('--trigger', action='store_true',
                        help='Signal the running daemon to start a discovery run immediately')
    parser.add_argument('--next-run', action='store_true',
                        help='Show when the next scheduled run would be')
    parser.add_argument('--update', action='store_true',
                        help='Check for updates and install if available')
    parser.add_argument('--update-status', action='store_true',
                        help='Show current update status and configuration')
    parser.add_argument('--list-backups', action='store_true',
                        help='List available backup versions')
    parser.add_argument('--version', action='store_true',
                        help='Show current version and exit')
    parser.add_argument('--force-update', action='store_true',
                        help='Force update even after failed attempts')
    parser.add_argument('--cleanup', action='store_true',
                        help='Clean up temporary files and old backups')

    return parser.parse_args()


# ────────────── ENTRY POINT ──────────────
if __name__ == "__main__":
    try:
        args = parse_cli_args()

        if args.version:
            from utils.updater import get_current_version
            print(f"DiscoveryLastFM v{get_current_version()}")
            sys.exit(0)

        if args.trigger:
            TRIGGER_FILE.touch()
            print(f"Trigger file written — the running daemon will start a discovery run shortly.")
            sys.exit(0)

        if args.next_run:
            nxt = next_run_time()
            if nxt:
                print(f"Next scheduled run ({SCHEDULE_MODE}): {nxt.strftime('%Y-%m-%d %H:%M')}")
            else:
                print("Schedule mode is MANUAL — runs only when triggered.")
            sys.exit(0)

        if args.daemon:
            run_daemon()
            sys.exit(0)

        if args.update:
            handle_update_command()
            sys.exit(0)

        if args.update_status:
            handle_update_status()
            sys.exit(0)

        if args.list_backups:
            handle_backups_list()
            sys.exit(0)

        if args.cleanup:
            from utils.updater import create_updater_from_config
            config_dict = {k: v for k, v in globals().items() if k.isupper()}
            config_dict["PROJECT_ROOT"] = os.path.dirname(os.path.abspath(__file__))
            updater = create_updater_from_config(config_dict)
            updater.cleanup_temp_files()
            print("✅ Cleanup completed")
            sys.exit(0)

        # Auto-update check
        if globals().get('AUTO_UPDATE_ENABLED', False):
            try:
                from utils.updater import create_updater_from_config
                config_dict = {k: v for k, v in globals().items() if k.isupper()}
                config_dict["PROJECT_ROOT"] = os.path.dirname(os.path.abspath(__file__))
                updater = create_updater_from_config(config_dict)

                if updater.should_check_for_updates():
                    log.info("Checking for automatic updates...")
                    release_info = updater.check_for_updates()
                    if release_info:
                        log.info(f"Update available: {release_info['version']}. Use --update to install.")
            except Exception as e:
                log.warning(f"Auto-update check failed: {e}")

        validate_configuration()
        run_discovery()

    except KeyboardInterrupt:
        log.warning("Interrupted.")
    except ConfigurationError as e:
        log.error(f"Configuration error: {e}")
        sys.exit(1)
    except Exception as e:
        log.error(f"Fatal error: {e}")
        sys.exit(1)