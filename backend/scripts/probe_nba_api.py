"""Explicit three-GET connectivity probe. No DB imports or response retention.

IDs: nba_api 1.11.4 BoxScore.expected_data (0022000180/BOS),
PlayerGameLog documentation (2544), and bundled static team directory (BOS).
Run once with --execute only under a separately authorized request budget.
"""
import argparse
import json
import time
from urllib.parse import urlsplit

import requests
from nba_api.library.http import NBAHTTP
from nba_api.live.nba.endpoints.boxscore import BoxScore
from nba_api.stats.endpoints.playergamelog import PlayerGameLog
from nba_api.stats.endpoints.leaguegamelog import LeagueGameLog


class ProbeSession(requests.Session):
    def __init__(self):
        super().__init__()
        self.attempts = 0
        self.last_finished = None
        # Preserve normal environment routing; never configure proxy bypasses.

    def get(self, url, **kwargs):
        routes = {
            ("cdn.nba.com", "/static/json/liveData/boxscore/boxscore_0022000180.json"),
            ("stats.nba.com", "/stats/playergamelog"),
            ("stats.nba.com", "/stats/leaguegamelog"),
        }
        parsed = urlsplit(url)
        if parsed.scheme != "https" or (parsed.hostname, parsed.path) not in routes or self.attempts >= 3:
            raise ValueError("Probe route or request budget rejected")
        if self.last_finished is not None:
            time.sleep(max(2 - (time.monotonic() - self.last_finished), 0))
        self.attempts += 1
        self.cookies.clear()
        try:
            response = super().get(url, **{**kwargs, "timeout": 10, "allow_redirects": False})
            response.raise_for_status()
            if response.is_redirect:
                raise ValueError("Redirect rejected")
            return response
        finally:
            self.cookies.clear()
            self.last_finished = time.monotonic()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print("Dry run: 3 GETs, 10-second timeout, no retries/redirects, >=2 seconds between attempts.")
        return
    with ProbeSession() as session:
        NBAHTTP.set_session(session)
        calls = [
            ("live_boxscore", lambda: BoxScore("0022000180", timeout=10)),
            ("playergamelog", lambda: PlayerGameLog(2544, season="2020-21", date_from_nullable="01/15/2021",
                                                   date_to_nullable="01/15/2021", timeout=10)),
            ("leaguegamelog", lambda: LeagueGameLog(season="2020-21", player_or_team_abbreviation="T",
                                                   date_from_nullable="01/15/2021", date_to_nullable="01/15/2021", timeout=10)),
        ]
        for name, call in calls:
            started = time.monotonic()
            try:
                data = call().nba_response.get_dict()
                summary = {"endpoint": name, "outcome": "ok"}
                if name == "live_boxscore":
                    game = data["game"]
                    players = [p for side in ("homeTeam", "awayTeam") for p in game[side]["players"]]
                    summary.update(game_id=game["gameId"], game_status=game["gameStatus"],
                        game_status_text=game["gameStatusText"], game_fields=sorted(game),
                        player_fields=sorted(set().union(*(set(p) for p in players))),
                        played_values=sorted({str(p.get("played")) for p in players}),
                        statuses=sorted({str(p.get("status")) for p in players}),
                        reasons=sorted({str(p.get("notPlayingReason")) for p in players}),
                        # Public classification descriptions only; no whole player objects.
                        descriptions=sorted({str(p.get("notPlayingDescription")) for p in players}),
                        statistic_fields=sorted(set().union(*(set(p.get("statistics", {})) for p in players))),
                        player_count=len(players))
                else:
                    summary["result_sets"] = [{"name": s["name"], "headers": s["headers"],
                                               "rows": len(s["rowSet"])} for s in data["resultSets"]]
                print(json.dumps({**summary, "elapsed_seconds": round(time.monotonic() - started, 2)}))
            except Exception as exc:
                print(json.dumps({"endpoint": name, "outcome": type(exc).__name__,
                                  "http_status": exc.response.status_code if isinstance(exc, requests.HTTPError) and exc.response is not None else None,
                                  "elapsed_seconds": round(time.monotonic() - started, 2)}))
        print(json.dumps({"attempts": session.attempts, "raw_responses_retained": False}))
        NBAHTTP.set_session(None)


if __name__ == "__main__":
    main()
