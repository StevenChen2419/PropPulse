"""Explicit opt-in loader for the authorized 4A.6 normalized observation artifact.

No transport, raw payloads, statistical logs, offers, current membership, or
provider-to-odds Event associations. Fixture Events supply reference clocks only.
The caller must own the disposable database and commit/rollback its transaction.
"""
from datetime import datetime, timezone
import json
from pathlib import Path

from nba_api.stats.static import players
from sqlalchemy import null

from app.models import Event, Player, Prop
from app.services.nba_api_provider import verified_crosswalk
from app.services.nba_evidence_service import _test_target, append_normalized_evidence

UTC = timezone.utc
HISTORICAL_REFERENCE = datetime(2021, 1, 19, 0, tzinfo=UTC)
COLLECTION_REFERENCE = datetime(2026, 10, 18, 21, tzinfo=UTC)
IDENTITIES = (
    ("2544", "LeBron James", "4a600000-0000-4000-8000-000000000001"),
    ("1627759", "Jaylen Brown", "4a600000-0000-4000-8000-000000000002"),
)


def _same(row, expected):
    for key, value in expected.items():
        actual = getattr(row, key)
        if isinstance(value, datetime) and actual.tzinfo is None:
            actual = actual.replace(tzinfo=UTC)
        if isinstance(value, datetime) and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        if actual != value:
            raise ValueError("Dedicated real-demo UUID collision; existing records will not be mutated")


def seed_real_demo(db, path):
    _test_target(db)  # Guard before artifact I/O or application-table SQL.
    artifact_path = Path(path).resolve(strict=True)
    if not artifact_path.is_file() or artifact_path.stat().st_size > 100_000:
        raise ValueError("Explicit bounded normalized artifact required")
    artifact = json.loads(artifact_path.read_text(encoding="utf-8-sig"))
    if (artifact.get("actual_source") is not True or artifact.get("raw_retained") is not False
            or artifact.get("requests") != 3 or artifact.get("issues") != []):
        raise ValueError("Authorized successful real observation metadata required")
    observed = datetime.fromisoformat(artifact["observed_at"].replace("Z", "+00:00"))
    now = datetime.now(UTC)
    if observed.tzinfo is None or not HISTORICAL_REFERENCE < observed <= COLLECTION_REFERENCE or observed > now:
        raise ValueError("Actual collection timestamp cannot be backdated or in the future")
    crosswalk = verified_crosswalk(artifact["identities"])
    if dict(crosswalk) != {nba: local for nba, _, local in IDENTITIES}:
        raise ValueError("Artifact must use the exact reviewed dedicated identities")
    for nba, name, _ in IDENTITIES:
        identity = players.find_player_by_id(int(nba))
        if identity is None or identity["full_name"] != name:
            raise ValueError("Reviewed NBA static directory identity conflict")
    records = artifact["records"]
    if not isinstance(records, list) or len(records) != 10:
        raise ValueError("Bounded authorized normalized records required")
    if any(datetime.fromisoformat(row["observed_at"].replace("Z", "+00:00")) != observed for row in records):
        raise ValueError("Observation timestamps must preserve actual collection time")
    if any(row["kind"] not in {"team", "game", "athlete", "participation"} for row in records):
        raise ValueError("This collection does not establish membership or schedule completeness")
    teams = sorted({row["identity"] for row in records if row["kind"] == "team"})
    scope = dict(provider="nba_com", crosswalk=crosswalk, sport="NBA", start_date="2021-01-15",
                 end_date="2021-01-15", team_ids=teams, now=now)
    # Existing service validates normalized provenance, identities, games and dates
    # before any new demo identity is inserted.
    dry = append_normalized_evidence(db, records, **scope)
    result = []
    with db.begin_nested():
        for index, (nba, name, local) in enumerate(IDENTITIES, 1):
            display = f"{name} — Jan 15 2021 coverage; fixture reference"
            player_values = dict(name=display, team="FIXTURE reference; current membership unknown", team_abbr="FIX", sport="NBA")
            player = db.get(Player, local)
            if player is None:
                db.add(Player(id=local, **player_values))
            else:
                _same(player, player_values)
            selections = {}
            for historical, reference in ((False, COLLECTION_REFERENCE), (True, HISTORICAL_REFERENCE)):
                number = index + (10 if historical else 0)
                event_id = f"4a600010-0000-4000-8000-{number:012d}"
                prop_id = f"4a600020-0000-4000-8000-{number:012d}"
                label = "Historical withheld" if historical else "Collection-day diagnostic; old coverage only"
                event_values = dict(provider="synthetic_fixture_4a6_real_reference", sport_key="basketball_nba",
                    provider_event_id=f"reference-{number}", home_team=f"FIXTURE {label}",
                    away_team="FIXTURE no actual NBA Event association", scheduled_start_at=reference)
                event = db.get(Event, event_id)
                if event is None:
                    db.add(Event(id=event_id, **event_values))
                else:
                    _same(event, event_values)
                db.flush()
                prop_values = dict(player_id=local, event_id=event_id, prop_type="points", line=20.5,
                    sportsbook="FIXTURE no sportsbook offer", over_odds=None, under_odds=None,
                    is_active=False, game_time=reference.replace(tzinfo=None),
                    opponent=f"FIXTURE {label}; Jan 15 2021 evidence only")
                prop = db.get(Prop, prop_id)
                if prop is None:
                    db.add(Prop(id=prop_id, **{**prop_values, "over_odds": null(), "under_odds": null()}))
                else:
                    _same(prop, prop_values)
                selections["historical_prop_id" if historical else "prop_id"] = prop_id
                selections["historical_event_id" if historical else "event_id"] = event_id
            result.append(dict(player_id=local, name=display, nba_player_id=nba,
                reference_at=COLLECTION_REFERENCE.isoformat(), historical_reference_at=HISTORICAL_REFERENCE.isoformat(),
                game_date="2021-01-15", observed_at=observed.isoformat(), actual_source=True,
                label="Real Jan 15 2021 observation; synthetic reference; not current latest appearance", **selections))
        db.flush()
        append_normalized_evidence(db, records, **scope, write=True, expected_digest=dry["digest"])
    return result
