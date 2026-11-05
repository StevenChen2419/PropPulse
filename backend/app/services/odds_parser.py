"""Validate event-odds responses before any database mutation."""
from datetime import datetime, timezone

from app.services.offer_service import utc, valid_number, valid_odds
from app.services.event_persistence import provider_metadata, EventConflict


def parse_utc(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        # Provider ISO timestamps must carry a timezone; DB naive values mean UTC.
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    except (ValueError, TypeError, OverflowError):
        return None


def observation_time(value, now):
    parsed = parse_utc(value)
    return parsed if parsed and parsed <= utc(now).replace(tzinfo=None) else None


def parse_event(data, event, sport_key, config, now):
    """Omission/empty lists never prove withdrawal. No synthetic tombstones."""
    rows, issues = [], []
    if not isinstance(data, dict) or data.get("id") != event.get("id"):
        return [], ["missing_or_mismatched_event"]
    if data.get("sport_key") != sport_key:
        return [], ["mismatched_sport"]
    try:
        authoritative = provider_metadata(data, sport_key)
        discovered = provider_metadata(event, sport_key)
    except EventConflict as exc:
        return [], [str(exc)]
    if authoritative != discovered:
        return [], ["event_discovery_metadata_conflict"]
    books = data.get("bookmakers")
    if not isinstance(books, list) or not books:
        return [], ["ambiguous_empty_bookmakers"]
    for book in books:
        if not isinstance(book, dict) or not isinstance(book.get("key"), str) or not book["key"].strip():
            issues.append("missing_bookmaker_key")
            continue
        markets = book.get("markets")
        if not isinstance(markets, list) or not markets:
            issues.append("ambiguous_empty_markets")
            continue
        returned = {m.get("key") for m in markets if isinstance(m, dict)}
        if set(config["markets"]) - returned:
            issues.append("omitted_markets")
        for market in markets:
            if not isinstance(market, dict):
                issues.append("malformed_market")
                continue
            prop_type = config["markets"].get(market.get("key"))
            if not prop_type:
                continue
            observed = observation_time(market.get("last_update"), now)
            if observed is None:
                issues.append("missing_or_invalid_observation")
            outcomes = market.get("outcomes")
            if not isinstance(outcomes, list) or not outcomes:
                issues.append("ambiguous_empty_outcomes")
                continue
            grouped, invalid_players = {}, set()
            for outcome in outcomes:
                if not isinstance(outcome, dict):
                    issues.append("malformed_outcome")
                    continue
                name, side = outcome.get("description"), outcome.get("name")
                line = outcome.get("point")
                if prop_type == "anytime_td":
                    line = 0.5
                    side = {"Yes": "Over", "No": "Under"}.get(side)
                if (not isinstance(name, str) or not name.strip() or not valid_number(line)
                        or side not in ("Over", "Under") or not valid_odds(outcome.get("price"))
                        or int(outcome["price"]) != outcome["price"]):
                    issues.append("malformed_outcome")
                    if isinstance(name, str):
                        invalid_players.add(name)
                    continue
                entry = grouped.setdefault((name, line), {})
                field = side.lower() + "_odds"
                if field in entry and entry[field] != outcome["price"]:
                    invalid_players.add(name)
                    issues.append("conflicting_outcome")
                entry[field] = outcome["price"]
            for (name, line), prices in grouped.items():
                if name in invalid_players:
                    continue
                if prop_type != "anytime_td" and len(prices) != 2:
                    issues.append("incomplete_side_pair")
                    continue
                rows.append({"sport": config["label"], "sport_key": sport_key,
                             "event_id": event["id"], "player_name": name,
                             "prop_type": prop_type, "line": line,
                             "over_odds": prices.get("over_odds"), "under_odds": prices.get("under_odds"),
                             "sportsbook": book.get("title") or book["key"],
                             "provider_bookmaker_key": book["key"], "provider_observed_at": observed,
                             "game_time": event.get("commence_time"),
                             "home_team": event.get("home_team"), "away_team": event.get("away_team")})
    return rows, sorted(set(issues))
