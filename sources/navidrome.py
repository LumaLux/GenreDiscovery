import hashlib
import logging
import requests

log = logging.getLogger("lfm2hp")


class NavidromeClient:
    """Subsonic-compatible client for Navidrome starred tracks."""

    def __init__(self, endpoint, username, password):
        self.endpoint = endpoint.rstrip("/")
        self.username = username
        self.password = password
        self._session = requests.Session()

    def _auth_params(self):
        salt = "gd2026"
        token = hashlib.md5((self.password + salt).encode()).hexdigest()
        return {
            "u": self.username,
            "t": token,
            "s": salt,
            "v": "1.16.1",
            "c": "DiscoveryLastFM",
            "f": "json",
        }

    def _get(self, method, **params):
        url = f"{self.endpoint}/rest/{method}"
        try:
            resp = self._session.get(url, params={**self._auth_params(), **params}, timeout=15)
            resp.raise_for_status()
            sr = resp.json().get("subsonic-response", {})
            if sr.get("status") != "ok":
                log.warning(f"Navidrome error ({method}): {sr.get('error', {})}")
                return {}
            return sr
        except requests.RequestException as e:
            log.warning(f"Navidrome request failed ({method}): {e}")
            return {}

    def ping(self):
        return bool(self._get("ping"))

    def get_starred_artist_names(self):
        """Returns set of artist names from starred artists AND starred songs."""
        data = self._get("getStarred2")
        starred2 = data.get("starred2", {})
        artists = {a["name"] for a in starred2.get("artist", []) if a.get("name")}
        songs = {s["artist"] for s in starred2.get("song", []) if s.get("artist")}
        return artists | songs

    def get_starred_albums(self):
        """Returns list of dicts with 'title', 'artist', 'musicBrainzId' for starred albums."""
        data = self._get("getStarred2")
        albums = data.get("starred2", {}).get("album", [])
        result = []
        for a in albums:
            mbid = a.get("musicBrainzId", "")
            title = a.get("name", "") or a.get("title", "")
            artist = a.get("artist", "")
            if title and artist:
                result.append({"title": title, "artist": artist, "mbid": mbid})
        return result


def get_all_starred_artist_names(endpoint, users):
    """Fetch starred artists for all entries in NAVIDROME_USERS and return merged set.

    Each entry in users must be a dict with 'username' and 'password' keys.
    """
    all_artists: set[str] = set()
    for user in users:
        client = NavidromeClient(endpoint, user["username"], user["password"])
        if client.ping():
            artists = client.get_starred_artist_names()
            log.info(f"Navidrome [{user['username']}] starred: {len(artists)} artists")
            all_artists |= artists
        else:
            log.warning(f"Navidrome: could not connect for user '{user['username']}' — skipping")
    return all_artists


def get_all_starred_albums(endpoint, users):
    """Fetch starred albums for all entries in NAVIDROME_USERS and return merged list (deduped by mbid/title+artist).

    Each entry in users must be a dict with 'username' and 'password' keys.
    """
    seen: set[str] = set()
    result = []
    for user in users:
        client = NavidromeClient(endpoint, user["username"], user["password"])
        if client.ping():
            albums = client.get_starred_albums()
            log.info(f"Navidrome [{user['username']}] starred albums: {len(albums)}")
            for album in albums:
                key = album["mbid"] or f"{album['artist']}::{album['title']}"
                if key not in seen:
                    seen.add(key)
                    result.append(album)
        else:
            log.warning(f"Navidrome: could not connect for user '{user['username']}' — skipping")
    return result