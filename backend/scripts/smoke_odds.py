"""Explicit, single-event operational odds smoke test; dry validation by default.

No scheduler, roster/history requests, schema changes, or global status writes.
Execution requires operator authorization before supplying --execute.
"""
import argparse
import os
import sys
from datetime import datetime, timezone
from uuid import uuid4

import httpx
from sqlalchemy import text
from sqlalchemy.engine import make_url

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import fetch_odds as ingestion
from app.config import settings
from app.services.ingestion_control import RequestBudget, atomic_json, odds_ingestion_lock
from app.services.odds_parser import parse_event, parse_utc
from app.services.event_persistence import provider_metadata, finish_event_report


def validate_plan(sport, event_id, market, region="us"):
    if sport not in ingestion.SPORT_CONFIG:
        raise ValueError("unsupported_sport")
    if market not in ingestion.SPORT_CONFIG[sport]["markets"]:
        raise ValueError("unsupported_market")
    if region != "us":
        raise ValueError("unsupported_region")
    if not event_id or not event_id.isalnum() or len(event_id) > 128:
        raise ValueError("invalid_event_id")
    target = make_url(settings.DATABASE_URL)
    if (target.get_backend_name() != "postgresql" or target.host != "localhost"
            or (target.port or 5432) != 5432 or target.database != "proppulse"):
        raise ValueError("unexpected_database_target")
    if settings.ENVIRONMENT != "development" or settings.LIVE_REFRESH_ENABLED:
        raise ValueError("development_refresh_guard")
    if not ingestion.API_KEY:
        raise ValueError("provider_credentials_missing")
    if settings.ODDS_MAX_REQUESTS_PER_RUN < 3 or settings.ODDS_MAX_CREDITS_PER_RUN < 2:
        raise ValueError("configured_budget_too_small")
    return {"sport_key": sport, "event_id": event_id, "market": market, "region": region,
            "database_target": "localhost:5432/proppulse", "alembic_revision": "20261014_02",
            "planned_free_requests": 1, "maximum_metered_attempts": 2,
            "maximum_credits": 2, "automatic_retries": 0,
            "writes": "Matched existing players' selected-event/market props, current offers, price-change snapshots, validated Event metadata and verified prop links"}


def quota(headers, key):
    try:
        value = int(headers.get(key))
        return value if value >= 0 else None
    except (ValueError, TypeError):
        return None


def request(client, path, params, cost, budget, run):
    if not budget.claim(cost):
        raise RuntimeError("request_or_credit_budget")
    if cost:
        run["metered_http_attempts"] += 1
    else:
        run["non_metered_http_attempts"] += 1
    try:
        response = client.get(ingestion.BASE_URL + path,
                              params={**params, "apiKey": ingestion.API_KEY}, timeout=ingestion.TIMEOUT)
    except Exception:
        raise RuntimeError("provider_network_failure") from None
    budget.observe(response.headers, cost, response.status_code)
    reported = quota(response.headers, "x-requests-last")
    run["provider_responses"].append({"http_status": response.status_code,
        "credits_reported": reported, "quota_remaining": quota(response.headers, "x-requests-remaining")})
    if reported is not None:
        run["reported_credits_used"] += reported
    else:
        run["all_cost_headers_present"] = False
    if reported is not None and reported > cost:
        raise RuntimeError("unexpected_provider_cost")
    if response.status_code != 200:
        raise RuntimeError("provider_http_" + str(response.status_code))
    try:
        return response.json(), response.headers
    except Exception:
        raise RuntimeError("provider_invalid_json") from None


def execute(plan, run):
    budget = RequestBudget(max_requests=3, max_credits=2, reserve=settings.ODDS_MIN_REMAINING_CREDITS)
    run_path = os.path.join(ingestion.STATUS_DIR, "odds_runs", run["run_id"] + ".json")
    try:
        with odds_ingestion_lock(ingestion.engine) as acquired:
            if not acquired:
                run["status"] = "skipped_locked"
                return run
            with ingestion.SessionLocal() as db:
                revision = db.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
                if revision != ["20261014_02"]:
                    raise RuntimeError("unexpected_alembic_revision")
            sport, event_id, market = plan["sport_key"], plan["event_id"], plan["market"]
            atomic_json(run_path, run)
            with httpx.Client(follow_redirects=False, transport=httpx.HTTPTransport(retries=0)) as client:
                events, headers = request(client, f"/sports/{sport}/events", {}, 0, budget, run)
                if quota(headers, "x-requests-last") != 0:
                    raise RuntimeError("free_discovery_cost_unverified")
                if not isinstance(events, list):
                    raise RuntimeError("invalid_event_discovery")
                matching = [event for event in events if isinstance(event, dict) and event.get("id") == event_id]
                if len(matching) != 1:
                    raise RuntimeError("selected_event_unavailable")
                event = matching[0]
                start = parse_utc(event.get("commence_time"))
                if (event.get("sport_key") != sport or not start
                        or start <= datetime.now(timezone.utc).replace(tzinfo=None)
                        or not event.get("home_team") or not event.get("away_team")):
                    raise RuntimeError("selected_event_not_upcoming")
                run["event"] = {key: event[key] for key in
                                ("id", "sport_key", "commence_time", "home_team", "away_team")}
                if budget.remaining is None or budget.remaining - 2 < budget.reserve:
                    raise RuntimeError("provider_quota_unverified_or_insufficient")
                markets, _ = request(client, f"/sports/{sport}/events/{event_id}/markets",
                                     {"regions": "us"}, 1, budget, run)
                if (not isinstance(markets, dict) or markets.get("id") != event_id
                        or markets.get("sport_key") != sport):
                    raise RuntimeError("market_discovery_identity_mismatch")
                books = markets.get("bookmakers")
                if not isinstance(books, list):
                    raise RuntimeError("invalid_market_discovery")
                available = any(isinstance(book, dict) and isinstance(book.get("markets"), list)
                                and any(isinstance(item, dict) and item.get("key") == market
                                        for item in book["markets"]) for book in books)
                if not available:
                    run.update(status="market_unavailable", skipped_reason="selected_market_not_observed")
                    return run
                data, _ = request(client, f"/sports/{sport}/events/{event_id}/odds",
                                  {"regions": "us", "markets": market, "oddsFormat": "american"},
                                  1, budget, run)
            if (not isinstance(data, dict) or data.get("id") != event_id or data.get("sport_key") != sport
                    or data.get("home_team") != event["home_team"]
                    or data.get("away_team") != event["away_team"]
                    or parse_utc(data.get("commence_time")) != start):
                raise RuntimeError("odds_response_scope_mismatch")
            for book in data.get("bookmakers", []) or []:
                if isinstance(book, dict):
                    for returned in book.get("markets", []) or []:
                        if isinstance(returned, dict) and returned.get("key") != market:
                            raise RuntimeError("unexpected_market_scope_expansion")
            config = {"label": ingestion.SPORT_CONFIG[sport]["label"],
                      "markets": {market: ingestion.SPORT_CONFIG[sport]["markets"][market]}}
            rows, issues = parse_event(data, event, sport, config, datetime.now(timezone.utc))
            status = ingestion.make_sport_status(sport)
            status.update(active=True, events_found=1, markets_requested=[market],
                          market_requests_made=1, market_requests_succeeded=1,
                          live_prop_outcomes_received=len(rows))
            status["_authoritative_events"] = [provider_metadata(data, sport)]
            run["event_relationships"] = status["event_relationships"]
            run.update(parsed_offers=len(rows), parser_issues=issues)
            with ingestion.SessionLocal() as db:
                try:
                    result = ingestion.apply_updates_for_sport(db, sport, rows, status,
                        scope={"event_id": event_id, "prop_type": config["markets"][market]})
                    run["matching_diagnostics"] = status.get("matching_diagnostics")
                    db.commit()
                    finish_event_report(status["event_relationships"], "committed")
                    if "matching_diagnostics" in status:
                        status["matching_diagnostics"]["transaction_outcome"] = "committed"
                except Exception:
                    db.rollback()
                    finish_event_report(status["event_relationships"], "rolled_back")
                    if "matching_diagnostics" in status:
                        status["matching_diagnostics"]["transaction_outcome"] = "rolled_back"
                    raise
            run.update(sport_result=status, committed_counts=result,
                       matching_diagnostics=status.get("matching_diagnostics"),
                       status="partial" if issues or status["unmatched_outcomes"]
                       or status["event_relationships"]["events_rejected"] else "completed")
            if not result["sportsbook_offers_saved"] and result.get("stale_observation_offers_skipped"):
                run["preserved_only_reason"] = "no_newer_provider_observations"
    except Exception as exc:
        # Exception text may contain SQL parameters or URLs; retain only known guard identifiers.
        reason = str(exc) if type(exc) is RuntimeError and str(exc).replace("_", "").isalnum() else type(exc).__name__
        run.update(status="failed", error_category=reason)
    finally:
        run.update(budget.report(), finished_at=datetime.now(timezone.utc).isoformat())
        atomic_json(run_path, run)
    return run


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sport", required=True, choices=list(ingestion.SPORT_CONFIG))
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--market", required=True)
    parser.add_argument("--region", choices=["us"], default="us")
    parser.add_argument("--execute", action="store_true", help="Run only after explicit paid-request authorization")
    args = parser.parse_args(argv)
    try:
        plan = validate_plan(args.sport, args.event_id, args.market, args.region)
    except Exception as exc:
        print("Smoke preflight failed: " + (str(exc) if type(exc) is ValueError else type(exc).__name__))
        return 1
    import json
    if not args.execute:
        print(json.dumps({"status": "dry_validation", "plan": plan}, indent=2))
        return 0
    run = {"run_id": str(uuid4()), "mode": "controlled_smoke", "status": "started", "scope": plan,
           "started_at": datetime.now(timezone.utc).isoformat(), "metered_http_attempts": 0,
           "non_metered_http_attempts": 0, "reported_credits_used": 0,
           "all_cost_headers_present": True, "provider_responses": []}
    execute(plan, run)
    print(json.dumps(run, indent=2))
    return 1 if run["status"] == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
