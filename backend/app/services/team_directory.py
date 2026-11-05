import unicodedata

import httpx

MLB_API_BASE = "https://statsapi.mlb.com/api/v1"
ESPN_WNBA_TEAMS_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/teams"
TeamDirectory = dict[str, dict | list[dict]]


def normalize_player_name(name: str) -> str:
    if not isinstance(name, str):
        return ""
    value = unicodedata.normalize("NFKD", name or "")
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.lower().replace(".", "").replace("-", " ").strip()
    for suffix in (" jr", " sr", " ii", " iii", " iv"):
        if value.endswith(suffix):
            value = value[: -len(suffix)]
    return " ".join(value.split())


def add_roster_candidate(directory, name, team, provider_id=None):
    """Keep collisions visible instead of last-write-wins roster identity."""
    key = normalize_player_name(name)
    if not key:
        return
    candidate = {**team, "provider_player_id": str(provider_id) if provider_id is not None else None}
    old = directory.get(key)
    if old is None:
        directory[key] = candidate
        return
    candidates = old if isinstance(old, list) else [old]
    if provider_id is None or candidate not in candidates:
        directory[key] = [*candidates, candidate]


def load_mlb_team_directory(client: httpx.Client, season: int) -> TeamDirectory:
    teams_response = client.get(
        f"{MLB_API_BASE}/teams",
        params={"sportId": 1, "season": season},
    )
    teams_response.raise_for_status()
    teams_by_id = {
        team["id"]: {
            "team": team["name"],
            "team_abbr": team.get("abbreviation") or team["name"][:4].upper(),
        }
        for team in teams_response.json().get("teams", [])
    }

    players_response = client.get(
        f"{MLB_API_BASE}/sports/1/players",
        params={"season": season, "hydrate": "currentTeam"},
    )
    players_response.raise_for_status()
    directory = {}
    for player in players_response.json().get("people", []):
        team_id = (player.get("currentTeam") or {}).get("id")
        team = teams_by_id.get(team_id)
        if team:
            add_roster_candidate(directory, player.get("fullName", ""), team, player.get("id"))
    return directory


def load_espn_team_directory(client: httpx.Client, season: int, sport: str) -> TeamDirectory:
    league = {"NBA": "basketball/nba", "WNBA": "basketball/wnba", "NFL": "football/nfl", "NHL": "hockey/nhl"}[sport]
    teams_url = f"https://site.api.espn.com/apis/site/v2/sports/{league}/teams"
    directory = {}
    # ESPN rejects the custom User-Agent used by the game-log client, so roster
    # discovery intentionally uses a clean client.
    with httpx.Client(timeout=30) as roster_client:
        teams_response = roster_client.get(teams_url)
        teams_response.raise_for_status()
        wrapped_teams = (
            teams_response.json()
            .get("sports", [{}])[0]
            .get("leagues", [{}])[0]
            .get("teams", [])
        )

        for wrapped_team in wrapped_teams:
            team = wrapped_team.get("team") or {}
            team_id = team.get("id")
            if not team_id:
                continue
            roster_response = roster_client.get(
                f"{teams_url}/{team_id}/roster"
            )
            roster_response.raise_for_status()
            team_info = {
                "team": team.get("displayName") or team.get("name") or "UNK",
                "team_abbr": team.get("abbreviation") or "UNK",
            }
            athletes = roster_response.json().get("athletes", [])
            flattened = []
            for entry in athletes:
                flattened.extend(entry.get("items", [entry]))
            for athlete in flattened:
                name = athlete.get("displayName") or athlete.get("fullName") or ""
                if name:
                    add_roster_candidate(directory, name, team_info, athlete.get("id"))
    return directory


def load_wnba_team_directory(client: httpx.Client, season: int) -> TeamDirectory:
    return load_espn_team_directory(client, season, "WNBA")


def load_team_directory(
    client: httpx.Client,
    sport: str,
    season: int,
) -> TeamDirectory:
    if sport == "MLB":
        return load_mlb_team_directory(client, season)
    if sport in {"NBA", "WNBA", "NFL", "NHL"}:
        return load_espn_team_directory(client, season, sport)
    return {}
