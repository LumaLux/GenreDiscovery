# DiscoveryLastFM — GenreDiscovery fork

[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/license-GPLv2-green.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-2.2.0-brightgreen.svg)](CHANGELOG.md)
[![Headphones](https://img.shields.io/badge/service-Headphones-blue.svg)](https://github.com/rembo10/headphones)
[![Lidarr](https://img.shields.io/badge/service-Lidarr-orange.svg)](https://github.com/Lidarr/Lidarr)
[![Docker](https://img.shields.io/badge/docker-lumalux%2Fgenrediscovery-blue.svg)](https://hub.docker.com/r/lumalux/genrediscovery)

🎵 **Modern music discovery tool** that integrates Last.fm, MusicBrainz, Navidrome, and both Headphones & Lidarr to automatically discover and queue new albums based on your listening history.

---

## ✨ What's new in v2.2 (GenreDiscovery fork)

| Feature | Description |
|---|---|
| **Genre-aware discovery** | Artists are grouped by Last.fm genre tags; similar-artist discovery runs per genre instead of per individual artist |
| **Loved / Starred tracks phase** | Runs before discovery — adds all artists from your Last.fm loved tracks and queues the specific albums those tracks appear on |
| **Navidrome integration** | Pulls starred artists and albums from Navidrome/Subsonic and adds them to your music service |
| **Multi-account support** | `LASTFM_USERS` and `NAVIDROME_USERS` accept multiple accounts; data is merged automatically |
| **DRY_RUN mode** | Set `DRY_RUN = True` to see exactly what would be added without touching your music service; output goes to `log/dry_run.log` |
| **Daemon mode** | `--daemon` keeps the script running and re-runs discovery on a configurable schedule (daily / weekly / monthly / manual) |
| **Manual trigger** | `--trigger` signals the running daemon to start a discovery run immediately (useful in Docker) |
| **Lidarr request caching** | Artist list, album MBIDs, and Lidarr album IDs are cached in-memory to eliminate redundant GET requests |
| **MusicBrainz optimisation** | Album type check now uses a single MBZ call instead of two, halving the per-album wait time |
| **Modular source layer** | Last.fm and Navidrome logic extracted to `sources/lastfm.py` and `sources/navidrome.py` |
| **Security** | `config.py` is excluded from git — credentials never reach your repository |

---

## 🎵 Features

### Discovery engine
- **Genre-aware discovery** — groups your top artists by genre tag, then finds similar artists within each genre pool
- **Loved tracks priority phase** — ensures every artist and album from your loved/starred tracks is in your music service
- **Quality filtering** — only queues studio albums; compilations, live albums, EPs, singles, etc. are skipped
- **Duplicate prevention** — persistent cache avoids adding the same album twice
- **Configurable buckets** — define how raw Last.fm tags map to broad genres (metal, electronic, rock, …)

### Integrations
- **Last.fm** — scrobble history, loved tracks, top artists, similar artists, album popularity (multi-account)
- **Navidrome / Subsonic** — starred artists and starred albums (multi-account)
- **Lidarr** — full artist and album management with quality/metadata profiles
- **Headphones** — artist and album management

### Operations
- **DRY_RUN mode** — safe preview of all changes written to `log/dry_run.log`
- **Daemon mode** — runs once on startup, then on a configured schedule; supports manual trigger
- **Auto-update system** — built-in update checker with backup and rollback

---

## 🛠️ How it works

```
Startup
  │
  ├─ Phase 1: Loved / Starred tracks
  │     ├─ Fetch loved tracks from all Last.fm accounts
  │     ├─ Fetch starred artists & albums from Navidrome (optional)
  │     ├─ Add all unique artists to music service
  │     └─ Add the specific albums those tracks appear on
  │
  └─ Phase 2: Discovery
        ├─ Fetch top artists per Last.fm account (merged by playcount)
        ├─ Group artists by genre using Last.fm tags + configurable buckets
        ├─ For each genre: take top N artists, fetch similar artists
        ├─ Deduplicate candidates across genres
        ├─ For each candidate: add artist, then add top studio albums
        └─ MusicBrainz used to filter non-studio releases (1 call/album)
```

---

## 📋 Prerequisites

- **Python 3.8+**
- **Last.fm account** with API key — [Get one here](https://www.last.fm/api/account/create)
- **Lidarr** or **Headphones** installation with API access
- *(Optional)* **Navidrome** installation with Subsonic API enabled

---

## 🚀 Quick start

```bash
git clone https://github.com/your_github_username/GenreDiscovery.git
cd GenreDiscovery
pip install requests
cp config.example.py config.py
# edit config.py with your credentials
python3 DiscoveryLastFM.py
```

### Running as a daemon (recommended)

```bash
# Runs immediately, then every day at 03:00
python3 DiscoveryLastFM.py --daemon
```

### Docker

```dockerfile
CMD ["python3", "DiscoveryLastFM.py", "--daemon"]
```

Trigger a manual run from outside the container:
```bash
docker exec <container> python3 DiscoveryLastFM.py --trigger
```

---

## ⚙️ Configuration

Copy `config.example.py` to `config.py` and fill in your values. `config.py` is excluded from git.

### Last.fm

```python
LASTFM_USERS = ["user1", "user2"]   # one or more accounts
LASTFM_API_KEY = "your_api_key"
```

### Lidarr

```python
MUSIC_SERVICE = "lidarr"
LIDARR_API_KEY = "your_lidarr_api_key"
LIDARR_ENDPOINT = "http://your-lidarr:8686"
LIDARR_ROOT_FOLDER = "/music"
LIDARR_QUALITY_PROFILE_ID = 2    # 1=Any, 2=Lossless, 3=Standard
LIDARR_METADATA_PROFILE_ID = 1   # 1=Standard, 2=None
```

### Navidrome (optional)

```python
NAVIDROME_ENABLED = True
NAVIDROME_ENDPOINT = "http://your-navidrome:4533"
NAVIDROME_USERS = [
    {"username": "alice", "password": "secret"},
    {"username": "bob",   "password": "secret"},
]
```

### Genre discovery

```python
GENRE_DISCOVERY_ENABLED = True
GENRE_SCROBBLE_PERIOD = "6month"   # overall / 7day / 1month / 3month / 6month / 12month
GENRE_TOP_ARTISTS_LIMIT = 200      # how many top artists to fetch
GENRE_TOP_N = 5                    # top artists per genre to find similars for
GENRE_SIMILAR_LIMIT = 10           # similar artists to request per top artist

GENRE_BUCKETS = {                  # map raw Last.fm tags → genre names
    "metal": ["heavy metal", "metal", "death metal", ...],
    "electronic": ["electronic", "techno", "house", ...],
    # set to {} to use raw Last.fm tags directly
}
```

### Loved / Starred tracks

```python
LOVED_TRACKS_ENABLED = True
LOVED_TRACKS_LIMIT = 500
```

### Scheduler (daemon mode)

```python
SCHEDULE_MODE = "daily"    # "daily" | "weekly" | "monthly" | "manual"
SCHEDULE_HOUR = 3          # hour of day to run (0–23)
SCHEDULE_DAY_OF_WEEK = 0   # for weekly: 0=Monday … 6=Sunday
SCHEDULE_DAY_OF_MONTH = 1  # for monthly: day of month (1–28)
```

### System

```python
DRY_RUN = False            # True = preview only, writes log/dry_run.log
VALIDATE_CONFIG_ON_STARTUP = True
```

### All parameters

| Parameter | Default | Description |
|---|---|---|
| `MUSIC_SERVICE` | `"lidarr"` | `"lidarr"` or `"headphones"` |
| `RECENT_MONTHS` | `3` | Months of history for standard mode |
| `MIN_PLAYS` | `20` | Minimum plays to consider an artist |
| `SIMILAR_MATCH_MIN` | `0.43` | Minimum similarity score |
| `MAX_SIMILAR_PER_ART` | `20` | Max similar artists per artist (standard mode) |
| `MAX_POP_ALBUMS` | `5` | Max albums to queue per artist |
| `CACHE_TTL_HOURS` | `48` | Similar-artist cache TTL |
| `REQUEST_LIMIT` | `1/5` | Last.fm requests per second |
| `MBZ_DELAY` | `1.1` | MusicBrainz delay between requests (seconds) |

---

## 🖥️ CLI reference

```bash
# Single run
python3 DiscoveryLastFM.py

# Daemon mode — runs on startup, then on schedule
python3 DiscoveryLastFM.py --daemon

# Trigger an immediate run in a running daemon
python3 DiscoveryLastFM.py --trigger

# Show next scheduled run time
python3 DiscoveryLastFM.py --next-run

# Updates
python3 DiscoveryLastFM.py --update
python3 DiscoveryLastFM.py --update-status
python3 DiscoveryLastFM.py --list-backups
python3 DiscoveryLastFM.py --version
```

---

## 📁 Project structure

```
GenreDiscovery/
├── DiscoveryLastFM.py        # Main orchestrator
├── config.example.py         # Configuration template
├── config.py                 # Your config (git-ignored)
├── sources/                  # API source layer
│   ├── __init__.py
│   ├── lastfm.py             # Last.fm API (multi-account)
│   └── navidrome.py          # Navidrome/Subsonic API (multi-account)
├── services/                 # Music service layer
│   ├── __init__.py
│   ├── base.py
│   ├── exceptions.py
│   ├── factory.py
│   ├── headphones.py
│   └── lidarr.py
├── log/                      # Log directory (git-ignored)
│   ├── discover.log          # Full application log
│   └── dry_run.log           # Clean dry-run report
├── lastfm_similar_cache.json # Cache file (git-ignored)
├── .gitignore
└── README.md
```

---

## 🐛 Troubleshooting

**Nothing is added (DRY_RUN)**
Check that `DRY_RUN = False` in `config.py`, then review `log/dry_run.log` to see what would have been added.

**API key errors**
Ensure all keys are valid and have the correct permissions. Lidarr key is under Settings → General.

**Rate limiting**
The script handles 429 responses automatically. If you see repeated rate-limit warnings, increase `REQUEST_LIMIT` (lower = slower) or `MBZ_DELAY`.

**Lidarr profile IDs**
Check your actual profile IDs in Lidarr under Settings → Quality Profiles and Settings → Metadata Profiles.

**Cache issues**
Delete `lastfm_similar_cache.json` to force a fresh fetch on next run.

**Debug output**
Set `DEBUG_PRINT = True` in `config.py` for verbose API call logging.

---

## 🙏 Acknowledgments

- [Last.fm](https://www.last.fm/) for the music discovery API
- [MusicBrainz](https://musicbrainz.org/) for comprehensive music metadata
- [Navidrome](https://www.navidrome.org/) for the Subsonic-compatible streaming server
- [Lidarr](https://github.com/Lidarr/Lidarr) for modern music library management
- [Headphones](https://github.com/rembo10/headphones) for automated music management
- Original concept and development by [Matteo Rancilio](https://www.linkedin.com/in/matteorancilio/), functionality expanded by [Jasper Folkers](https://www.linkedin.com/in/jasper-folkers-5bb77847/)

---

**Note**: This tool is designed for personal use. Please respect the terms of service of all integrated APIs and services.
