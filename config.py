"""Central app configuration — pure constants, no Streamlit imports."""
import pytz

DISPLAY_TZ = pytz.timezone("Europe/Bucharest")
MAX_MATCHES = 25
REFRESH_COOLDOWN_SECONDS = 60

# One league registry, four external ID systems:
#   fd_code   → football-data.org competition code
#   api_id    → api-sports.io (API-Football) league id
#   espn_slug → ESPN site API league slug
#   odds_key  → The Odds API sport key (real bookmaker odds)
LEAGUES = {
    "World Cup 2026":     {"fd_code": "WC",  "api_id": 1,   "espn_slug": "fifa.world", "odds_key": "soccer_fifa_world_cup"},
    "Premier League":     {"fd_code": "PL",  "api_id": 39,  "espn_slug": "eng.1",      "odds_key": "soccer_epl"},
    "La Liga":            {"fd_code": "PD",  "api_id": 140, "espn_slug": "esp.1",      "odds_key": "soccer_spain_la_liga"},
    "Serie A":            {"fd_code": "SA",  "api_id": 135, "espn_slug": "ita.1",      "odds_key": "soccer_italy_serie_a"},
    "Bundesliga":         {"fd_code": "BL1", "api_id": 78,  "espn_slug": "ger.1",      "odds_key": "soccer_germany_bundesliga"},
    "Ligue 1":            {"fd_code": "FL1", "api_id": 61,  "espn_slug": "fra.1",      "odds_key": "soccer_france_ligue_one"},
    "Liga Portugal":      {"fd_code": "PPL", "api_id": 94,  "espn_slug": "por.1",      "odds_key": "soccer_portugal_primeira_liga"},
    "Eredivisie":         {"fd_code": "DED", "api_id": 88,  "espn_slug": "ned.1",      "odds_key": "soccer_netherlands_eredivisie"},
    "Championship":       {"fd_code": "ELC", "api_id": 40,  "espn_slug": "eng.2",      "odds_key": "soccer_efl_champ"},
    "Belgian Pro League": {"fd_code": "BJL", "api_id": 144, "espn_slug": "bel.1",      "odds_key": "soccer_belgium_first_div"},
}

ALL_LEAGUES = list(LEAGUES)
DEFAULT_LEAGUES = ["World Cup 2026", "Premier League", "La Liga"]

# Cup competitions where the API-Football "season" equals the calendar year
# of the fixture (club leagues use the season-start year instead).
CUP_CODES = {"WC"}

# Derived lookups used by the service layer
LEAGUE_CODES = {name: cfg["fd_code"] for name, cfg in LEAGUES.items()}
API_FOOTBALL_IDS = {cfg["fd_code"]: cfg["api_id"] for cfg in LEAGUES.values()}
ESPN_SLUGS = {cfg["fd_code"]: cfg["espn_slug"] for cfg in LEAGUES.values()}
ODDS_KEYS = {cfg["fd_code"]: cfg["odds_key"] for cfg in LEAGUES.values()}

# Cache TTLs (seconds)
TTL_STANDINGS = 3600
TTL_MATCHES = 3600
TTL_LINEUPS = 1800
TTL_INJURIES = 1800
TTL_SCOREBOARD = 86400
TTL_MOTIVATION = 600
TTL_CONTEXT_BATCH = 1800
TTL_ODDS = 1800  # The Odds API: 500 credits/month — cache aggressively

# Parallelism caps per API (free-tier rate limits)
FOOTBALL_DATA_WORKERS = 3   # football-data.org: 10 req/min
ESPN_WORKERS = 10           # ESPN site API: no strict limit
