import requests
from datetime import datetime, timedelta

from services.football_api import BASE_URL, make_request


# =========================
# LAST MATCHES FETCH
# =========================

def get_last_matches(team_name, limit=5):

    url = f"{BASE_URL}/teams"

    data = make_request(url)

    if not data:
        return []

    # fallback search team id
    team_id = None

    for t in data.get("teams", []):
        if t["name"] == team_name:
            team_id = t["id"]
            break

    if not team_id:
        return []

    matches_url = f"{BASE_URL}/teams/{team_id}/matches?status=FINISHED&limit=20"

    matches_data = make_request(matches_url)

    if not matches_data:
        return []

    matches = matches_data.get("matches", [])

    # sort by date desc
    matches = sorted(
        matches,
        key=lambda x: x["utcDate"],
        reverse=True
    )

    return matches[:limit]