import logging
import time
import requests

log = logging.getLogger("lfm2hp")

try:
    from config import *
except ImportError:
    LASTFM_API_KEY = ""
    LASTFM_USERS = []

if 'LASTFM_USERS' not in globals():
    LASTFM_USERS = []
if 'REQUEST_LIMIT' not in globals():
    REQUEST_LIMIT = 1/5
if 'DEBUG_PRINT' not in globals():
    DEBUG_PRINT = True


def dprint(msg):
    if DEBUG_PRINT:
        print(f"[DEBUG] {msg}")


def rate_limited(delay):
    def decorator(fn):
        last = 0
        def wrapped(*args, **kwargs):
            nonlocal last
            wait = delay - (time.time() - last)
            if wait > 0:
                dprint(f"sleep {wait:.2f}s ({fn.__name__})")
                time.sleep(wait)
            result = fn(*args, **kwargs)
            last = time.time()
            return result
        return wrapped
    return decorator


@rate_limited(REQUEST_LIMIT)
def lf_request(method, **params):
    """Last.fm API call with robust retry handling."""
    for alt, real in (("from_", "from"), ("to_", "to")):
        if alt in params:
            params[real] = params.pop(alt)

    base = "https://ws.audioscrobbler.com/2.0/"
    params |= {"method": method, "api_key": LASTFM_API_KEY, "format": "json"}

    max_retries = 3
    retry_delay = 2

    for attempt in range(max_retries):
        try:
            dprint(f"LF  → {method} (attempt {attempt+1}/{max_retries})")
            r = requests.get(base, params=params, timeout=15)
            dprint(f"LF  ← {r.status_code}")

            if r.status_code == 429 and attempt < max_retries - 1:
                wait_time = int(r.headers.get('Retry-After', retry_delay * 2))
                log.warning(f"Rate limit hit (Last.fm), waiting {wait_time}s")
                time.sleep(wait_time)
                continue

            if r.status_code != 200:
                if attempt < max_retries - 1:
                    log.warning(f"Last.fm HTTP {r.status_code}, attempt {attempt+1}/{max_retries}")
                    time.sleep(retry_delay * (attempt + 1))
                    continue
                else:
                    log.warning(f"Last.fm HTTP {r.status_code}: {r.text[:200]}")
                    return None

            try:
                return r.json()
            except Exception:
                if attempt < max_retries - 1:
                    log.warning(f"Last.fm invalid JSON, attempt {attempt+1}/{max_retries}")
                    time.sleep(retry_delay)
                    continue
                else:
                    log.warning(f"Last.fm invalid JSON: {r.text[:200]}")
                    return None

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, ConnectionResetError) as e:
            if attempt < max_retries - 1:
                log.warning(f"Last.fm connection error: {e}, attempt {attempt+1}/{max_retries}")
                time.sleep(retry_delay * (attempt + 1))
                continue
            else:
                log.error(f"Last.fm connection failed after {max_retries} attempts: {e}")
                return None
        except Exception as e:
            if attempt < max_retries - 1:
                log.warning(f"Last.fm error: {e}, tentativo {attempt+1}/{max_retries}")
                time.sleep(retry_delay * (attempt + 1))
            else:
                log.error(f"Last.fm error after {max_retries} attempts: {e}")
                return None

    return None


def get_artist_top_tags(artist_name):
    """Fetch top Last.fm tags for an artist. Returns list of lowercase tag strings (up to 10)."""
    js = lf_request("artist.getTopTags", artist=artist_name)
    if not js:
        return []
    tags = js.get("toptags", {}).get("tag", [])
    return [t["name"].lower() for t in tags[:10] if t.get("name")]


def get_top_artists_by_period(period="6month", limit=200):
    """Fetch top artists for all LASTFM_USERS and merge by summing playcounts.
    Returns list of dicts with 'name', 'playcount', 'mbid', sorted by playcount desc."""
    merged: dict[str, dict] = {}
    for username in LASTFM_USERS:
        js = lf_request("user.getTopArtists", user=username, period=period, limit=limit)
        if not js:
            continue
        artists = js.get("topartists", {}).get("artist", [])
        log.info(f"[{username}] Fetched {len(artists)} top artists (period={period})")
        for a in artists:
            name = a.get("name", "")
            if not name:
                continue
            if name in merged:
                merged[name]["playcount"] = str(
                    int(merged[name].get("playcount", 0)) + int(a.get("playcount", 0))
                )
            else:
                merged[name] = dict(a)

    result = sorted(merged.values(), key=lambda a: int(a.get("playcount", 0)), reverse=True)
    log.info(f"Merged top artists: {len(result)} across {len(LASTFM_USERS)} account(s)")
    return result


def get_tag_top_artists(tag, limit=30):
    """Top artists for a Last.fm tag (used as genre fallback).
    Returns list of dicts with 'name' and 'mbid'."""
    js = lf_request("tag.getTopArtists", tag=tag, limit=limit)
    if not js:
        return []
    return js.get("topartists", {}).get("artist", [])


def get_loved_tracks(limit=500):
    """Fetch loved tracks from all LASTFM_USERS.
    Returns deduplicated list of (artist_name, track_name) tuples."""
    loved: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for username in LASTFM_USERS:
        page = 1
        fetched = 0
        while fetched < limit:
            js = lf_request("user.getLovedTracks", user=username, limit=50, page=page)
            if not js:
                break
            tracks = js.get("lovedtracks", {}).get("track", [])
            if not tracks:
                break
            for track in tracks:
                artist_name = track.get("artist", {}).get("name", "")
                track_name = track.get("name", "")
                if artist_name and track_name:
                    key = (artist_name, track_name)
                    if key not in seen:
                        seen.add(key)
                        loved.append(key)
            fetched += len(tracks)
            attr = js.get("lovedtracks", {}).get("@attr", {})
            total_pages = int(attr.get("totalPages", 1))
            if page >= total_pages:
                break
            page += 1
        log.info(f"[{username}] loved tracks: {len(loved)} unique (artist, track) pairs so far")
    return loved