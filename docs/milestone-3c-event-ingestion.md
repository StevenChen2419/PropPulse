# Milestone 3C: Authoritative Event ingestion and verified prop linkage

Implemented October 15, 2026 from clean HEAD
`5283f6f20c2cb37399f48e75262841c1198210c9`. Parent/application AGENTS instructions,
Milestone 2 reliability, Phase 3A matching/history and PostgreSQL reports, Phase 3B
schema report, and the local ignored authorized 3B migration report were reviewed.
No separate local architecture-audit document was found; the earlier reports
record its identity, mutable-team, legacy-fallback, and schedule-conflict findings.
The authorized 3B report supersedes its implementation report's pre-migration
development revision: the supplied development baseline is revision 20261014_02.

## Event identity and provider metadata

`event_persistence.py` supplies `provider_metadata`, `upsert_event`, `resolve_prop`,
and `associate_prop`. The existing Phase 3B validator and link helper remain the
domain guards. The Odds API adapter fixes provider to `the_odds_api`, checks the
requested sport, canonicalizes provider/sport, and preserves the opaque event ID
exactly, including case and punctuation. IDs never derive from teams or dates.
Participants must be known, nonblank, distinct, at most 150 characters, and contain
no control characters. External schedules require explicit timezone offsets;
equivalent offsets normalize to UTC. Existing naive database timestamps mean UTC.

Event discovery and event-odds response metadata must agree after normalization.
Missing metadata or disagreement rejects that event's offer rows. Metadata from a
successful, validated response can be retained even when there are no usable
markets or player matches. No additional provider request is made. Conflicting
observations of the same identity within a sport batch reject that identity
before persistence. Player.team never establishes authoritative participants.

An Event without eligible props does not create an actionable game: existing
legacy game APIs still derive their results from eligible props/offers. Event
presence alone never changes sportsbook availability.

## Persistence, concurrency, and transactions

The unique key remains `(provider, sport_key, provider_event_id)`. PostgreSQL
`INSERT ... ON CONFLICT DO NOTHING`, followed by `SELECT ... FOR UPDATE`, resolves
concurrent identity insertion without an IntegrityError poisoning the sport
transaction. The winner creates the UUID; other writers reuse it. Namespaces
remain distinct for another sport or provider using the same opaque ID.

The service does not commit, open a session, call providers, create tables, or
change revisions. Caller-owned per-sport transactions encompass Event work,
prop associations, offers, and snapshots. Existing pinned dataset advisory locks,
budgets, retries and independent sport sessions are unchanged. Database failures
roll back the whole sport; a later sport can still succeed. Known prop links
cannot be reassigned or cleared through the helper, ORM guards, or existing
PostgreSQL trigger. No new migration or dependency is needed.

## Metadata precedence and schedule corrections

The current provider payload has **no trustworthy event metadata version**.
Bookmaker/market `last_update` is an odds observation, not an Event version.
Event.updated_at is local metadata-write time and is never presented as provider
observation time. A later HTTP response alone does not prove newer metadata.

The conservative policy is:

1. Accept complete provider metadata for a new identity.
2. Reuse exactly agreeing metadata without changing its write time.
3. Reject changed participants, including swapped home/away sides.
4. Reject an unversioned schedule change during ordinary ingestion with
   `unversioned_schedule_conflict`. Preserve current committed metadata and odds.
5. An independently verified, separately authorized correction can call
   `upsert_event(..., expected_start=<old timezone-aware UTC schedule>)`, or supply
   `apply_updates_for_sport(..., schedule_corrections={opaque_id: old_schedule})`
   within its explicit locked sport transaction. The correction's metadata must
   still validate and have identical participants. This argument must come from
   reviewed operator evidence, never provider outcome rows or market timestamps.
6. Under the Event row lock, the stored start must match the expected old start.
   A stale correction fails with `stale_schedule_correction`. Repeating the
   already-applied desired metadata reuses the same Event idempotently.

An accepted correction retains the Event UUID and synchronizes **every linked
Prop.game_time** in the same transaction, including markets omitted by the
response or outside the smoke market. It changes no prices, offer observation or
ingestion times, snapshots, saved props, or slip choices. A metadata-only
correction cannot refresh odds. Normal accompanying offer reconciliation keeps
its usual observation and price-change rules. Game-start eligibility continues
to read the now-synchronized Prop.game_time.

Neither normal CLI ingestion nor the smoke CLI supplies schedule overrides.
This intentionally requires operator review instead of guessing between
unversioned schedules. There is no cancellation inference from omitted events.
The historical MLB three-second discrepancy remains unresolved, with no rounding.

## Prop association and player matching

Phase 3A candidate-aware exact matching, roster collision rejection, unknown-team
rejection, and smoke existing-player restrictions remain in force. A roster can
associate an athlete with the independently validated event; it cannot change
that event's participants. Rejected athletes leave valid Event metadata intact.

Prop resolution is by the accepted player/market and exact provider identity or
known Event UUID. Multiple matches reject with `ambiguous_legacy_identity`.
Existing links must point to that same Event and agree with stored provider/sport
identity. An unlinked legacy prop additionally requires exact stored sport/opaque
ID, an agreeing group schedule, an explicit home/away side, and an opponent
consistent with the authoritative participants. Group schedule/sport inspection
includes omitted markets even in scoped smoke persistence.

The former schedule/opponent and incomplete-row first-match fallbacks are removed.
Plausible same-player/market props lacking provider identity stay unresolved and
block creation of a silent duplicate. Unrelated dated events do not block a new
provider identity. No prop is merged or deleted. New props attach to their Event
inside the same transaction before offers are stored. Existing UUIDs and user
selection fields remain intact. Automatic player-derived self-matchup repair is
no longer invoked during ingestion, because it could rewrite legacy evidence
before validation; the compatibility helper remains available to existing callers.

## Reporting and smoke compatibility

Each sport has a bounded `event_relationships` report; smoke also exposes it at
run level. Counters are Event identities or prop relationships, never offer rows:

| Field | Meaning |
| --- | --- |
| events_parsed | Unique identity observations considered by the persistence batch, plus rejected discovery/odds observations recorded during parsing |
| events_validated | Nonconflicting metadata identities accepted for an upsert attempt |
| database_attempts | Upsert calls, including calls subsequently rejected or failed |
| events_rejected | Invalid/conflicting Event identity observations |
| link_conflicts | Player/market groups whose prop relationship resolution failed |
| legacy_props_unresolved | Distinct unlinked legacy prop UUIDs intentionally blocked during relationship resolution |
| reasons / samples | Reason counts plus at most 30 samples, IDs truncated to 128 characters |
| attempted | Reconciliation results prepared in the pending transaction |
| committed | Those results only after successful commit; zero on rollback |
| rolled_back | Prepared results discarded by rollback; zero on successful commit |
| transaction_outcome | pending, committed, or rolled_back |

Each of the three result dictionaries contains `events_created`, `events_reused`,
`events_updated`, `props_newly_linked`, `existing_links_reused`, `schedule_changes`.
These action categories are exclusive for Event upserts. A database exception
before the service returns has a database_attempt but no invented successful
action result. Direct service callers must finalize reports only after their own
commit/rollback; normal ingestion and smoke do this automatically.

New reason codes include invalid_event_metadata, event_sport_mismatch,
event_discovery_metadata_conflict, conflicting_event_observations,
event_participants_conflict, unversioned_schedule_conflict,
stale_schedule_correction, ambiguous_legacy_identity,
legacy_provider_identity_conflict, known_event_reassignment,
legacy_schedule_or_sport_conflict, legacy_participant_conflict,
unverified_legacy_identity and event_identity_rejected. Existing matching and
offer diagnostics are preserved. Exceptions expose classes or fixed reason codes,
not SQL parameters, credentials, or raw provider payloads.

Smoke still defaults to dry validation, requires explicit `--execute` operational
authorization, and retains one sport/event/market/US region, three total requests,
two maximum paid attempts/credits, no retries, no roster/history calls, and the
same dataset lock. Its schema guard now requires existing revision 20261014_02.
The bounded plan names Event metadata/link writes. No smoke execution occurred.

## Legacy backfill preparation — no executor

`prepare_event_links.py` is a separately invoked **dry-run only** tool. It has no
`--execute` option. An operator must explicitly supply a trusted retained smoke
report and a new `.json` output under `backend/data/odds_runs/verification`.
Evidence/arguments validate before engine creation; the inventory uses PostgreSQL
REPEATABLE READ, READ ONLY, a statement timeout, a row limit and rollback.
The richer reader includes exact prop/player IDs, name, market, line and current
Event FK alongside legacy identity/matchup fields. The old classifier remains
compatible with that added inventory data.

Example for a **separately authorized future read-only preparation**, not executed:

```powershell
# From backend; use the exact reviewed local report and a new protected filename.
.\venv\Scripts\python.exe scripts/prepare_event_links.py `
  --retained-report data/odds_runs/<private-run-id>.json `
  --output data/odds_runs/verification/phase3c-proposed-links.json
```

`build_event_link_manifest` returns exact candidate UUIDs, expected stored fields,
player fingerprints, evidence source and canonical-JSON SHA256, and a manifest
digest. Default candidate limit is ten, hard maximum 100. It considers only the
trusted report's exact identity, rejects schedule/sport/group conflicts, verifies
stored opponent/side, rejects unknown/incomplete evidence and different known
links, and preserves all unrelated/unresolved records. Player teams are change
fingerprints, never authoritative evidence. Output is exclusive-create: no
overwrite. POSIX mode requests owner-only access; Windows uses inherited ACLs,
so the operator must protect that local directory. Git ignore already covers it.

`revalidate_event_link_manifest` rejects changed evidence, candidates, player or
stored identity values. An intervening link to an explicitly supplied same target
Event is idempotently accepted. A future separately authorized executor must lock
and revalidate records inside its write transaction; a digest is neither evidence
authentication nor protection against later concurrent changes. No executor is
implemented, and no development manifest was generated or applied in this phase.

Historical verified retained evidence concerns NBA Boston Celtics at Detroit
Pistons, `26b036ff107f3c658258eaf4a6f26228`, October 20, 2026 19:00 UTC, with ten
candidate props. That is prior evidence, not a fresh inventory or provider check.
The 66 independently unverified groups/3,598 props, 26 conflicting groups/2,135
props, and 321 missing-identity props remain unresolved. No bulk repair is safe.

## Verification and data preservation

Disposable container `proppulse-test-m3c-20261015` used cached postgres:15-alpine,
PostgreSQL **15.18**, loopback port **61782**, database
`proppulse_test_milestone3c`, temporary test-only trust, and tmpfs data with no
named volumes or bind mounts. Development containers stayed stopped. Every test
used an explicit test database name safeguard and a random schema. Existing
revision migration tests ran only in these isolated fixtures; no new Alembic
revision was authored. New Event ingestion PostgreSQL fixtures install the real
existing constraints and link trigger before exercising persistence.

Final verification (full unittest discovery with external HTTP transports blocked):

| Check | Result |
| --- | --- |
| Full backend suite | **340 passed, zero failures/errors/skips**, 24.846 seconds |
| Real PostgreSQL tests included above | **54 passed**, PostgreSQL 15.18 |
| New Event ingestion scenarios | **50 passed**: 24 SQLite and 26 PostgreSQL |
| New manifest/CLI regressions | **26 passed**, mocked CLI database access |
| External HTTP transport attempts in final suite | **0** |
| `python -m compileall -q app scripts tests` from backend | Passed, exit 0 |
| `git --git-dir=.git --work-tree=. diff --check` | Passed, exit 0 |
| Effective LIVE_REFRESH_ENABLED inspection from backend | False |

The full run used unittest discovery through a local ignored wrapper that patches
httpx.HTTPTransport.handle_request and AsyncHTTPTransport.handle_async_request to
fail if invoked, preserving isolated TestClient ASGI API requests. Process lock
fixtures use only the explicit isolated PostgreSQL URL. Suite output from demo,
provider, and migration helpers belongs to mocked/isolated test fixtures.

Coverage includes concurrent identity insertion and schedule CAS, namespace identity,
invalid metadata, exact legacy association, ambiguity/conflict rejection,
schedule propagation to omitted markets, game-start eligibility, price/history
preservation, rollback/counters, independent sports, API regressions, advisory
locks/process death, smoke limits, and manifest stale-record/idempotency rules.
Independent read-only review found a manifest opponent/side validation gap; it
was fixed, four regressions added, and the final review found no remaining
high-confidence actionable issue. Final isolated cleanup verified zero leftover
test schemas and zero advisory locks, then removed only the disposable container.
Development PostgreSQL/backend/Redis remained stopped; existing named volumes
remain present. Docker Desktop itself was left running.

No development connection, write, backfill, provider request, app lifespan,
automatic refresh, new revision, commit, or push occurred. Existing backups were
not opened or modified. No live ingestion or smoke `--execute` was run. The
development baseline remains the supplied/previously verified baseline; this
task does not claim a new development row-count or fingerprint measurement.

No frontend/API response contract changed. Frontend tests/build and browser E2E
are omitted; existing isolated HTTP API regressions run in the backend suite.
Existing datetime deprecation and AnyIO resource warnings are not suppressed.

## Files and deferred work

Implementation: event_persistence.py, event_identity.py, odds_parser.py,
event_backfill.py, event_link_manifest.py, fetch_odds.py, smoke_odds.py,
prepare_event_links.py. Tests: test_event_ingestion.py, test_event_link_manifest.py,
test_live_ingestion.py, test_milestone2_ingestion.py, test_smoke_odds.py,
test_smoke_scope.py. Documentation: this report. No frontend, model-schema,
configuration, dependency, or migration file changed.

Participant corrections, independent verification of unresolved legacy groups,
provider athlete identity persistence, fully versioned schedule metadata,
multi-line schema redesign, Event-based API grouping/frontend routes and research
selection remain deferred. Conservative rejection can reduce coverage and is
intentional until independent evidence exists.

The next operational step requires **separate explicit authorization**: protect a
new manifest location, stop ingestion/refresh, retain and verify the existing
backup without overwriting it, read-only regenerate the ten-candidate retained
NBA manifest, review every candidate and current values, then approve a bounded
one-Event linkage transaction implemented/reviewed for that operation. Acquire
the shared lock, revalidate inside the transaction, abort on any changed evidence,
and compare IDs, offers/timestamps, snapshots and selections before/after. Do not
request providers, correct schedules, process other identities, or enable refresh
implicitly. That procedure has not been executed.

## Final review and authorized local checkpoint

On October 15, 2026, the final review started on `master` at the expected
`5283f6f20c2cb37399f48e75262841c1198210c9`. The working tree contained only the
15 Phase 3C implementation, test, and documentation files listed above. Full
diff and independent read-only review found no confirmed regression requiring
an implementation change. This section records the additional verification;
the earlier no-commit statement describes the initial implementation phase.

The complete backend suite was rerun with disposable PostgreSQL 15.18 in
`proppulse-test-m3c-checkpoint-20261015`, database
`proppulse_test_m3c_checkpoint`, loopback port 64943, tmpfs-only storage, and no
volume/bind mounts. Result: **340 passed, zero failures/errors/skips**, including
**54 real PostgreSQL tests**, in 24.279 seconds. External HTTP transports were
blocked and recorded **zero attempts**. Python compilation and Git whitespace
checks passed; effective automatic refresh remained False. Frontend checks were
omitted because frontend files and API response contracts remain unchanged.

Cleanup confirmed zero leftover test schemas and advisory locks, then removed
only that disposable container. Development containers remained stopped. No
development database connection/write, provider request, manifest preparation,
backfill, backup access, new migration, schema change, or Phase 3D work occurred.
Only the reviewed 15 source/test/documentation files are intended for the
explicitly authorized local commit `feat: integrate authoritative events into
odds ingestion`. No push or prior-history rewrite is authorized or performed.
