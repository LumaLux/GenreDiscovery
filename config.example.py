# =================================================================
# DiscoveryLastFM v2.2 Configuration Template
# Fork: GenreDiscovery edition
# Copy to config.py and customize with your values
# =================================================================

# === MUSIC SERVICE SELECTION ===
# Choose your music management service
# Options: "headphones", "lidarr"
MUSIC_SERVICE = "lidarr"

# === LAST.FM CONFIGURATION ===
LASTFM_USERS = ["your_lastfm_username"]   # add more accounts: ["user1", "user2"]
LASTFM_API_KEY = "your_lastfm_api_key"

# === HEADPHONES CONFIGURATION ===
# Required if MUSIC_SERVICE = "headphones"
HP_API_KEY = "your_headphones_api_key"
HP_ENDPOINT = "http://your-headphones-server:port"

# Headphones Advanced Options
HP_MAX_RETRIES = 3
HP_RETRY_DELAY = 5
HP_TIMEOUT = 60

# === LIDARR CONFIGURATION ===
# Used if MUSIC_SERVICE = "lidarr"
LIDARR_API_KEY = "your_lidarr_api_key"
LIDARR_ENDPOINT = "http://your-lidarr-server:port"
LIDARR_ROOT_FOLDER = "/music"

# Lidarr Profile Configuration
LIDARR_QUALITY_PROFILE_ID = 2   # ID of quality profile (1=Any, 2=Lossless, 3=Standard)
LIDARR_METADATA_PROFILE_ID = 1  # ID of metadata profile (1=Standard, 2=None)

# Lidarr Behavior Configuration
LIDARR_MONITOR_MODE = "all"     # "all", "future", "missing", "existing", "first", "latest", "none"
LIDARR_SEARCH_ON_ADD = True     # Auto-search when adding artists/albums

# Lidarr Advanced Options
LIDARR_MAX_RETRIES = 3
LIDARR_RETRY_DELAY = 5
LIDARR_TIMEOUT = 60             # Base timeout - specific operations use longer timeouts automatically

# === DISCOVERY PARAMETERS ===
RECENT_MONTHS = 3               # Months of recent plays to analyze (used in standard mode)
MIN_PLAYS = 20                  # Minimum plays to consider an artist (used in standard mode)
SIMILAR_MATCH_MIN = 0.43        # Minimum similarity match threshold
MAX_SIMILAR_PER_ART = 20        # Max similar artists per artist (used in standard mode)
MAX_POP_ALBUMS = 5              # Max popular albums to fetch per artist
CACHE_TTL_HOURS = 48            # Cache time-to-live in hours

# === API RATE LIMITING ===
REQUEST_LIMIT = 1/5             # Last.fm requests per second (5 requests/5 seconds)
MBZ_DELAY = 1.1                 # MusicBrainz delay between requests (seconds)

# === DEBUGGING ===
# DEBUG_PRINT = True             # Enable debug print statements

# === SYSTEM CONFIGURATION ===
VALIDATE_CONFIG_ON_STARTUP = True    # Validate configuration on startup
ENABLE_CACHE_MIGRATION = True        # Auto-migrate cache format if needed
DRY_RUN = False                      # When True, log what would change without touching the music service

# === SCHEDULER ===
# Used when running with --daemon flag.
# SCHEDULE_MODE options:
#   "daily"   — runs every day at SCHEDULE_HOUR
#   "weekly"  — runs every week on SCHEDULE_DAY_OF_WEEK at SCHEDULE_HOUR
#   "monthly" — runs every month on SCHEDULE_DAY_OF_MONTH at SCHEDULE_HOUR
#   "manual"  — only runs when triggered via: python DiscoveryLastFM.py --trigger
SCHEDULE_MODE = "daily"
SCHEDULE_HOUR = 3              # Hour of day to run (0-23, 24h clock)
SCHEDULE_DAY_OF_WEEK = 0      # For weekly: 0=Monday … 6=Sunday
SCHEDULE_DAY_OF_MONTH = 1     # For monthly: day of month (1-28)


# =================================================================
# === GENRE DISCOVERY (NEW in v2.2) ===
# =================================================================

# Enable genre-aware discovery instead of flat artist-based discovery.
# When True, artists are grouped by Last.fm genre tags before finding
# similar artists, so each genre gets its own discovery pool.
# Set to False to revert to original v2.1.x behaviour.
GENRE_DISCOVERY_ENABLED = True

# Time window for top artist fetch from Last.fm
# Options: overall, 7day, 1month, 3month, 6month, 12month
GENRE_SCROBBLE_PERIOD = "6month"

# How many top artists to fetch from Last.fm for genre grouping
GENRE_TOP_ARTISTS_LIMIT = 200

# How many top artists (by playcount) per genre to find similar artists for
GENRE_TOP_N = 5

# How many similar artists to request per top artist (per genre)
GENRE_SIMILAR_LIMIT = 10

# Genre buckets: group Last.fm tags into broader genres.
#
# How it works:
#   For each artist, their top Last.fm tags are fetched.
#   Tags are matched against your bucket definitions (in order).
#   First match wins. If no bucket matches, the raw first tag is used.
#   The fallback for tag.getTopArtists uses the FIRST tag in each bucket.
#
# Set to {} to disable bucketing and use raw Last.fm tags directly.
GENRE_BUCKETS = {
    "metal": [
        "heavy metal", "metal", "death metal", "black metal",
        "thrash metal", "doom metal", "power metal", "symphonic metal",
        "melodic death metal", "metalcore", "progressive metal",
    ],
    "electronic": [
        "electronic", "techno", "house", "ambient", "edm",
        "drum and bass", "dnb", "synthwave", "idm", "trance",
        "dubstep", "electro",
    ],
    "rock": [
        "rock", "alternative rock", "indie rock", "classic rock",
        "hard rock", "alternative", "indie", "grunge", "punk rock",
    ],
    "hip-hop": [
        "hip-hop", "hip hop", "rap", "trap", "boom bap",
        "gangsta rap", "lo-fi hip hop",
    ],
    "jazz": [
        "jazz", "bebop", "fusion", "smooth jazz", "jazz fusion",
        "contemporary jazz",
    ],
    "classical": [
        "classical", "orchestral", "chamber music", "opera",
        "baroque", "contemporary classical",
    ],
    "folk": [
        "folk", "folk rock", "singer-songwriter", "acoustic",
        "americana", "bluegrass", "country folk",
    ],
}


# =================================================================
# === LOVED / STARRED TRACKS (NEW in v2.2) ===
# =================================================================

# Enable priority phase for loved/starred tracks.
# Runs before discovery and ensures all artists from your loved tracks
# are added to the music service.
LOVED_TRACKS_ENABLED = True

# Max loved tracks to fetch from Last.fm (pagination handled automatically)
LOVED_TRACKS_LIMIT = 500


# =================================================================
# === NAVIDROME INTEGRATION (NEW in v2.2, optional) ===
# =================================================================

# Set True to also pull starred artists/tracks from Navidrome.
# Uses the Subsonic-compatible API.
NAVIDROME_ENABLED = False

# Your Navidrome server URL
NAVIDROME_ENDPOINT = "http://your-navidrome:4533"

# One dict per account: {"username": "...", "password": "..."}
# Password is used to generate a Subsonic token — never sent directly.
NAVIDROME_USERS = [
    {"username": "your_username", "password": "your_password"},
]


# =================================================================
# === AUTO-UPDATE CONFIGURATION ===
# =================================================================

AUTO_UPDATE_ENABLED = False          # Enable automatic update checking
UPDATE_CHECK_INTERVAL_HOURS = 24     # How often to check for updates (hours)
BACKUP_RETENTION_DAYS = 7            # How long to keep backup files (days)
ALLOW_PRERELEASE_UPDATES = False     # Allow installation of pre-release versions

# Point this to your fork's GitHub repo so auto-updates pull the right version
GITHUB_REPO_OWNER = "your_github_username"
GITHUB_REPO_NAME = "GenreDiscovery"
# GITHUB_TOKEN = "your_github_token"  # Optional: higher API rate limits
