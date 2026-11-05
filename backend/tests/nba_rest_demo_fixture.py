"""Milestone 4A.6 OFFLINE rehearsal: synthetic results, real public identities.

No retained NBA response is used. These dates, games, minutes and scores are
synthetic test inputs, NEVER historical claims. No statistical game logs or live
offers are inserted. The caller owns the transaction and disposable DB lifecycle.
"""
from datetime import datetime, timezone

from nba_api.stats.static import players
from sqlalchemy import null

from app.models import Event, Player, Prop
from app.services.nba_api_provider import normalize_player_games, normalize_team_games, verified_crosswalk
from app.services.nba_evidence_service import _test_target, append_normalized_evidence

UTC = timezone.utc
OBSERVED = datetime(2021, 1, 18, 12, tzinfo=UTC)
REFERENCE = datetime(2021, 1, 19, 0, tzinfo=UTC)  # Eastern January 18
NOW = datetime(2021, 1, 19, 12, tzinfo=UTC)
MANIFEST = (
    dict(nba_player_id="2544", name="LeBron James", player_id="4a600001-0000-4000-8000-000000002544",
         event_id="4a600002-0000-4000-8000-000000002544", prop_id="4a600003-0000-4000-8000-000000002544",
         team_id="1610612747", opponent_id="1610612746", abbreviation="LAL", opponent="LAC", game_id="0099900001"),
    dict(nba_player_id="1627759", name="Jaylen Brown", player_id="4a600001-0000-4000-8000-000001627759",
         event_id="4a600002-0000-4000-8000-000001627759", prop_id="4a600003-0000-4000-8000-000001627759",
         team_id="1610612738", opponent_id="1610612753", abbreviation="BOS", opponent="ORL", game_id="0099900002"),
)
SEASON = "2020-21"
GAME_DATE = "2021-01-15"


def reviewed_crosswalk():
    entries = []
    for item in MANIFEST:
        identity = players.find_player_by_id(int(item["nba_player_id"]))
        if identity is None or identity["full_name"] != item["name"]:
            raise ValueError("Bundled NBA identity does not match the reviewed public identity")
        entries.append(dict(nba_player_id=item["nba_player_id"], player_id=item["player_id"], verified=True,
            provenance=f"nba_api bundled static directory: {item['nba_player_id']} = {item['name']}; "
                       f"dedicated disposable 4A.6 fixture UUID {item['player_id']} created explicitly for this identity; "
                       "synthetic game results, no retained NBA response"))
    return verified_crosswalk(entries)


def result_set(name, rows):
    return {"resultSets": [dict(name=name, headers=list(rows[0]), rowSet=[list(row.values()) for row in rows])]}


def synthetic_payloads(item):
    """NBA-source-shaped dictionaries; ALL game/result fields are invented."""
    team_rows = [dict(TEAM_ID=int(item["team_id"]), GAME_ID=item["game_id"], GAME_DATE=GAME_DATE,
                      MATCHUP=f"{item['abbreviation']} vs. {item['opponent']}", WL="W", PTS=100),
                 dict(TEAM_ID=int(item["opponent_id"]), GAME_ID=item["game_id"], GAME_DATE=GAME_DATE,
                      MATCHUP=f"{item['opponent']} @ {item['abbreviation']}", WL="L", PTS=90)]
    player_rows = [dict(Player_ID=int(item["nba_player_id"]), Game_ID=item["game_id"], GAME_DATE=GAME_DATE,
                        MATCHUP=f"{item['abbreviation']} vs. {item['opponent']}", MIN=25, PTS=10)]
    return result_set("LeagueGameLog", team_rows), result_set("PlayerGameLog", player_rows)


def normalized_fixture(crosswalk):
    records = []
    for item in MANIFEST:
        team_payload, player_payload = synthetic_payloads(item)
        games = normalize_team_games(team_payload, observed_at=OBSERVED)
        appearances = normalize_player_games(player_payload, observed_at=OBSERVED,
                                              crosswalk=crosswalk, game_records=games["records"])
        if games["issues"] or appearances["issues"]:
            raise ValueError("Synthetic demonstration failed existing provider normalization")
        records.extend(games["records"] + appearances["records"])
    return records


def seed(db):
    """Add only owned test identities and offline evidence; never commit here."""
    _test_target(db)  # Before any writes, including Player/Event/Prop.
    crosswalk = reviewed_crosswalk()
    for item in MANIFEST:
        player = db.get(Player, item["player_id"])
        if player is None:
            db.add(Player(id=item["player_id"], name=item["name"], team="SYNTHETIC 4A.6 historical fixture",
                          team_abbr="FIX", sport="NBA"))
        elif player.name != item["name"] or player.team != "SYNTHETIC 4A.6 historical fixture":
            raise ValueError("Fixture UUID collision; existing player will not be mutated")
        event = db.get(Event, item["event_id"])
        if event is None:
            db.add(Event(id=item["event_id"], provider="synthetic_fixture_4a6",
                         provider_event_id=f"synthetic-historical-{item['nba_player_id']}",
                         sport_key="basketball_nba", home_team="SYNTHETIC January 18 2021 home",
                         away_team="SYNTHETIC historical opponent", scheduled_start_at=REFERENCE))
        elif event.provider != "synthetic_fixture_4a6":
            raise ValueError("Fixture Event UUID collision")
        db.flush()
        prop = db.get(Prop, item["prop_id"])
        if prop is None:
            db.add(Prop(id=item["prop_id"], player_id=item["player_id"], event_id=item["event_id"],
                        prop_type="points", line=20.5, sportsbook="SYNTHETIC historical fixture; no offer",
                        over_odds=null(), under_odds=null(), is_active=False, game_time=REFERENCE,
                        opponent="SYNTHETIC January 18 2021 reference"))
        elif str(prop.player_id) != item["player_id"] or str(prop.event_id) != item["event_id"]:
            raise ValueError("Fixture Prop UUID collision")
    db.flush()
    scope = dict(provider="nba_com", crosswalk=crosswalk, sport="NBA", start_date=GAME_DATE,
                 end_date="2021-01-18", team_ids=sorted({i[k] for i in MANIFEST for k in ("team_id", "opponent_id")}), now=NOW)
    records = normalized_fixture(crosswalk)
    dry = append_normalized_evidence(db, records, **scope)
    return append_normalized_evidence(db, records, **scope, write=True, expected_digest=dry["digest"])


def seed_demo(db):
    """Browser harness metadata; the harness commits and labels its fixture page."""
    seed(db)
    return [dict(item, reference_at=REFERENCE.isoformat(), game_date=GAME_DATE,
                 season=SEASON, synthetic=True, real_response_obtained=False,
                 label="SYNTHETIC historical 4A.6 rehearsal; no real NBA response") for item in MANIFEST]
