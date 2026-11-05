"""Validate authoritative event metadata; no ingestion, matching, or backfill."""
from datetime import datetime, timezone
import re

from app.services.event_backfill import SPORTS


def identity_value(field, value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")
    if any(ord(char) < 32 for char in value):
        raise ValueError(f"{field} contains control characters")
    if field == "provider_event_id":
        # Provider IDs are opaque: do not lowercase, strip, parse or reconstruct.
        return value
    value = value.strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9_]*", value):
        raise ValueError(f"{field} must be a canonical identifier")
    if field == "sport_key" and value not in SPORTS:
        raise ValueError("Unsupported canonical sport key")
    return value


def team_value(value):
    if not isinstance(value, str):
        raise ValueError("Team must be a nonempty verified name")
    if any(ord(char) < 32 for char in value) or len(value) > 150:
        raise ValueError("Invalid verified team name")
    value = " ".join(value.split())
    if value.casefold() in {"", "unk", "unknown", "tbd", "n/a", "none", "null", "--"}:
        raise ValueError("Team must be a nonempty verified name")
    return value


def event_time(value, *, require_timezone=False):
    """Use the application's naive-UTC storage convention, with explicit offsets
    required at the external metadata boundary. Naive internal datetimes mean UTC.
    """
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("Invalid event timestamp") from None
    if not isinstance(value, datetime) or (require_timezone and value.tzinfo is None):
        raise ValueError("Event timestamp must include a timezone")
    return value if value.tzinfo is None else value.astimezone(timezone.utc).replace(tzinfo=None)


def validate_event_metadata(*, provider, provider_event_id, sport_key, home_team,
                            away_team, scheduled_start_at):
    """For future callers supplying independently verified provider metadata.

    Validation establishes shape/consistency, not provenance. The caller must not
    supply reconstructed teams as authoritative. No Event or relationship is saved.
    """
    home, away = team_value(home_team), team_value(away_team)
    if home.casefold() == away.casefold():
        raise ValueError("Home and away teams must be distinct")
    return {"provider": identity_value("provider", provider),
            "provider_event_id": identity_value("provider_event_id", provider_event_id),
            "sport_key": identity_value("sport_key", sport_key),
            "home_team": home, "away_team": away,
            "scheduled_start_at": event_time(scheduled_start_at, require_timezone=True)}


def link_prop_to_event(prop, event):
    """Explicit future linkage guard. Does not query, flush, commit or backfill.

    Persist/flush a validated Event first. Existing known linkage cannot change or
    be cleared. Legacy provider identity, when present, must agree exactly.
    """
    if event is None or not event.id:
        raise ValueError("A persisted event identity is required")
    current = prop.event_id
    pending = getattr(prop, "event", None)
    if (current is not None and str(current) != str(event.id)) or (
            pending is not None and pending is not event and str(pending.id) != str(event.id)):
        raise ValueError("Known prop event identity cannot be reassigned")
    if prop.odds_event_id and prop.odds_event_id != event.provider_event_id:
        raise ValueError("Legacy provider event identity conflicts with Event")
    if prop.odds_sport_key and prop.odds_sport_key != event.sport_key:
        raise ValueError("Legacy sport identity conflicts with Event")
    prop.event = event
    prop.event_id = event.id
