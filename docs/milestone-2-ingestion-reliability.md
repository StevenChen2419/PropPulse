# Milestone 2: Safe Odds Ingestion and Provider Data Integrity

Follow-up: [PostgreSQL verification](milestone-2-postgresql-verification.md).
The implementation-stage test results and PostgreSQL limitations below are historical;
see the follow-up for actual PostgreSQL execution and current readiness.

## Scope and starting checkpoint

Implemented against clean `master` at `b9bca124863ab4c7ba9e001a32caee6fa020fae4`,
with repository instructions at `c5ab1e428bb71f2848f235bf57a6c5a2dcc6a34b`.
Parent and application AGENTS instructions were read. No commits, pushes, local
application database access, provider ingestion, service startup, migration execution
against the application database, or paid provider calls were performed.

## Original risks and architecture

Before: The Odds API sports/event discovery and per-event odds were parsed into
player/market groups. Existing players were matched by normalized name, with roster
correction and minimal player creation. Props retained their IDs, but fresh offers
could be deleted across an entire sport after superficially successful responses.
Even a partial run deleted all books on touched props. Expired rows were deleted,
and snapshots could be restored using local capture time as apparent observation.
All sports shared one final database commit. Prices received default local write
timestamps. Automatic workers held a scheduler advisory lock that manual scripts
bypassed. Failures before the final status write left an older successful result.

After: discovery -> bounded provider client -> event-scoped validated parsing and
coverage diagnostics -> normalized player/event matching -> stable-key offer upsert
-> independent sport transaction -> price-change snapshots -> run-specific atomic
status plus latest-owner status -> existing response-time offer eligibility -> frontend.
History ingestion remains separate; its provider matching, analytics and timestamp
semantics were inspected and are outside this odds milestone. No frontend redesign,
new market/sport, model change, queue, Redis caching, or dependency was introduced.

## Reconciliation policy and examples

Only positively observed and validated offers are inserted/updated. Neither HTTP
200, an empty list, an omitted event, an omitted market, nor a missing bookmaker
is a withdrawal. No whole-sport/touched-prop offer deletion remains. No snapshot
restoration can invent a provider observation. Stored expired offers are retained;
the shared policy makes them non-actionable. Synthetic props remain excluded.

- Event A returns valid offers and Event B fails: A's offers can commit; B's offers
  remain stored and keep their original observation clock. Run reports partial.
- A returns empty bookmakers, empty outcomes or missing markets: previous offers
  survive; coverage records ambiguity. Empty or mismatched event identity is rejected.
- One book is observed and another omitted: only the observed book changes. An
  incomplete Over/Under pair is rejected, preserving both prior sides and timestamp.
  The existing anytime-touchdown Yes/No single-side behavior is retained.
- Duplicate normalized player identity, conflicting outcomes, malformed data, or
  ambiguous alternate lines are skipped and reported; no deletion follows.
- Parser exceptions are contained to that event, preserving earlier parsed events.
- Roster mismatch skips offers without deleting existing prices or selections.

The event-odds API supplies no explicit trustworthy withdrawal marker used by this
application. There is therefore no invented confirmed-empty/tombstone pathway.
Omissions cannot be distinguished reliably from withdrawal here; preserved prices
age naturally through the six-hour policy. This limitation also means a complete
HTTP success is called observed coverage, never proof of a full sportsbook inventory.

## Transaction boundaries and idempotency

All prepared odds updates for one sport commit together. Integrity/flush/commit
errors roll back that sport, clear uncommitted success counters, record an error
category, and allow later sports to proceed using a fresh session. This keeps the
existing sport reconciler simple; a database failure in one event also rolls back
other events of that same sport, but never previously committed independent sports.
The error category retains the exception class without SQL parameters/secrets.

Current offers are updated in place by prop and stable bookmaker identity, preserving
IDs and existing uniqueness rules. Equivalent repeated data does not add current
offer rows. Snapshots are appended only when line/side prices change; existing
snapshots are never deleted. `captured_at` remains local price-change capture time,
not provider observation. The reduced snapshot cadence avoids duplicate unchanged
history without changing captured_at's meaning. Saved props and slip identities
are never deleted or rewritten by odds reconciliation.

## Provider observation, ingestion, and freshness

`PropBook.provider_observed_at` stores validated market `last_update` in UTC.
Provider ISO inputs must include a timezone; offsets normalize to naive UTC for
consistency with current database columns. Missing, malformed, naive, and future
observations are unknown. No future allowance or ingestion-time substitution is
used. Event times also normalize actual offsets to UTC instead of merely stripping
them. API timestamps include UTC offsets.

`ingested_at` records local processing time. `updated_at` remains a legacy local
write timestamp. Reingesting old observations updates ingestion time but cannot
reset freshness. Older/missing observations cannot overwrite a known current
observation. New timestamp-less offers may be stored for diagnostics but remain
unavailable. Legacy rows remain stored and unavailable until a real observation
arrives; their old local timestamps are not promoted to provider observations.

The shared policy and SQL prefilter use provider observation: Live through 30
minutes, Last known after 30 minutes through six hours inclusive, then Expired.
Games are unavailable at their start time. Exact sportsbook/line/side identity,
valid prices and the existing 0.001 same-line tolerance remain mandatory.
`refreshed_at` remains the compatibility field for the observation, with explicit
`provider_observed_at` and `ingested_at` also exposed in availability contracts.
Existing frontend expiry clocks use the corrected observation/expiry values.
Persisted run availability also uses the shared policy, separately from write counts.

Provider references checked during implementation:
[market observation and event-odds response fields](https://the-odds-api.com/liveapi/guides/v4/#get-event-odds),
[bookmaker keys](https://the-odds-api.com/sports-odds-data/bookmaker-apis.html).
The parser intentionally uses market last_update, not a deprecated bookmaker timestamp.

## Sportsbook identity and legacy compatibility

New offers match `provider_bookmaker_key`. `provider_title` retains the latest
readable provider title. The existing `sportsbook` selection label is preserved
on updates, so a provider title change does not invalidate or remap a saved exact
selection. An explicit alias map resolves legacy titles only where the provider
key is known. Conflicting aliases/duplicate keys or label collisions fail closed;
no unknown legacy row is guessed or deleted. Unsupported legacy data without an
observation remains unavailable. No automatic bulk bookmaker identity backfill occurs.

The schema still supports one current line per prop/bookmaker. Multiple conflicting
lines for the same incoming identity are skipped rather than selected arbitrarily.
Multi-line schema redesign and remediation of existing ambiguous duplicate records
are deferred; operators must inspect such records rather than silently deduplicate.
A changed line can make an old slip selection unavailable; its stored choice remains
removable and is never silently switched.

## Demo protections

Seed, refresh_demo_data, and update_line_movement require explicit process opt-in
`PROPPULSE_DEMO_MODE=true` plus a bound PostgreSQL database exactly `proppulse_demo`.
Refresh helpers independently check every prop for explicit `demo:` identity, demo
sport source and Demo book, and refuse any provider event/last-seen, offers, snapshots,
provider history, uncertain schema, pending writes or unverified fatigue associations.
Seed refuses nonempty datasets instead of deleting them. Line movement makes no
provider requests and writes no live ingestion status. README normal startup no
longer invokes synthetic refresh or requires seed. Other experimental ML tooling
is not part of live ingestion and was not executed or expanded.

## Advisory locks and status lifecycle

Both manual and automatic odds invoke the same script-owned PostgreSQL session
advisory lock, `734901227`, before HTTP or reconciliation. A dedicated connection
stays pinned across provider work and independent sport commits. Explicit unlock
runs on success/exception; unlock failure invalidates the connection. Process death
releases its PostgreSQL session lock when the socket closes. Non-PostgreSQL odds
execution fails closed. The automatic scheduler uses separate lock `734901226`
to coordinate workers; it never passes ownership across a subprocess connection.

Each run has UUID, started/finished UTC times, outcome and safe diagnostic metadata.
States: started, completed, partial, failed, skipped_locked, quota_stopped.
Per-sport coverage and failures are distinct from current offer availability.
Counters include event attempts/processing/failure, offers written/preserved, and
snapshot writes; rolled-back writes are not successes. The automatic parent reads
the exact child's run file, avoiding an older latest result.

`backend/data/odds_runs/<uuid>.json` records individual attempts. Only the lock owner
updates latest `odds_ingestion_status.json`; a contender records skipped_locked in
its own file without clobbering the active run. JSON writes use unique temporary
files and atomic replacement. Scheduler state uses the same atomic writer.
A forcibly terminated manual process can leave started without finished_at, which
must be interpreted as incomplete, never a successful refresh. Retention/pruning
of per-run status artifacts is deferred; generated files are ignored by Git.

## Provider budgets and retries

`ODDS_MAX_REQUESTS_PER_RUN=100` caps all Odds API HTTP attempts, including discovery
and retries. `ODDS_MAX_CREDITS_PER_RUN=500` reserves the maximum requested
market/region cost before each odds request. Reliable x-requests-last headers adjust
accounting; missing costs consume the conservative reservation. Remaining quota
stays unknown until reported, then is conservatively decremented between reliable
headers. `ODDS_MIN_REMAINING_CREDITS=50` preserves a reserve. Budget exhaustion
prevents another HTTP attempt and yields quota_stopped with a specific reason.

Only 502/503/504 and explicit frequency-limit 429 are retried, at most three total
attempts, bounded exponential backoff honoring numeric or HTTP-date Retry-After. Long requested
waits, exhausted 429 retries and quota stops halt the whole run, including later
sports. Other failures are not retried. Network exceptions do not retry because
request consumption may be uncertain. Roster requests are public, separate from
the metered Odds API budget. No additional data-fetch caching was introduced.

## Migration requirements and safe procedure

Files: `backend/alembic.ini`, `backend/alembic/env.py`, and revision
`backend/alembic/versions/20261014_01_offer_provenance.py` (revision `20261014_01`).
Adds nullable String provider_bookmaker_key/provider_title and DateTime
provider_observed_at/ingested_at only. Backfills ingested_at from existing updated_at;
provider fields remain unknown. Existing offers/history/selections are retained.
Empty databases can initialize the current model schema; missing prop_books in a
nonempty partial database is refused. No new uniqueness constraint or Event table.

1. Stop automatic/manual ingestion and backend workers, and take a database backup.
2. Review the revision and intended DATABASE_URL privately. Do not display credentials.
3. From backend run `.\venv\Scripts\python.exe -m alembic upgrade head`.
4. Check `.\venv\Scripts\python.exe -m alembic current` and restart only afterward.
5. Any future provider refresh is an explicit operational action with metered costs.

These commands were documented, not run against the local application database.
`create_all` is not a replacement for this upgrade. Existing rows with malformed
legacy schemas require explicit operator inspection/remediation, not silent deletion.
The rollback strategy is application rollback while retaining nullable columns/data.
Automatic destructive downgrade refuses to discard provenance; removing columns
requires a separately reviewed backup/removal migration. See `backend/alembic/README.md`.
Alembic was already installed; no dependencies were added. Offline SQL generation
is intentionally unsupported because safe adoption inspects the actual schema.

## Verification results

| Directory | Exact command | Result |
| --- | --- | --- |
| backend | `.\venv\Scripts\python.exe -m unittest discover -s tests -p test_milestone2_ingestion.py` | 37 passed |
| backend | `.\venv\Scripts\python.exe -m unittest discover -s tests -p test_demo_guard.py` | 13 passed |
| backend | `.\venv\Scripts\python.exe -m unittest discover -s tests -p test_ingestion_migration.py` | 5 passed |
| backend | `.\venv\Scripts\python.exe -m unittest discover -s tests` | 160 discovered, 156 passed, 4 PostgreSQL skips |
| frontend | `npm test` | 32 passed |
| frontend | `npx tsc --noEmit` | Passed |
| frontend | `npm run build` | Passed, production routes generated |
| root | `backend\venv\Scripts\python.exe -m compileall -q backend/app backend/scripts` | Passed |
| root | `git -c safe.directory=<repository-root> diff --check` | Passed |

The requested compile command named backend/.venv, but this repository has backend/venv;
the existing interpreter was used. Git read-only checks required sandbox elevation
with command-local trust; no global trust configuration was changed. Existing UTC
DeprecationWarnings remain; Git may warn about LF-to-CRLF normalization. Lint was
not run separately because no ESLint configuration exists. Test fixture observations
were migrated to the new provider field without weakening original boundary assertions.
The old test expecting whole-sport replacement was inverted to enforce preservation.

Regression coverage uses mocked HTTP clients and selected-table in-memory SQLite
fixtures, plus existing isolated tests. It exercises price/snapshot/selection
preservation, parser failure, independent rollback, repeat ingestion, timestamps,
identity, budget/retry enforcement, lock lifecycle and status-file contention.
Optional PostgreSQL tests require explicit `PROPPULSE_TEST_POSTGRES_URL` pointing
to a database named proppulse_test_*, and create only UUID test schemas. The variable
was absent for verification: four tests skipped before creating an engine/connection.
SQLite and lock mocks are not proof of PostgreSQL runtime semantics.

## Remaining limitations and next milestone

Implemented and locally verified: safe upserts/omission preservation, timestamp
policy, deterministic identity handling, demo guard, lifecycle/budget behavior,
additive migration logic on isolated fixtures, frontend tests/type/build.

Implemented but not runtime-verified: PostgreSQL advisory locking, actual PostgreSQL
DDL/rollback and process termination behavior. No browser interaction/E2E testing
or live provider execution was performed. No local application database was touched.
Provider omission cannot establish withdrawal, and six-hour Last known eligibility
does not guarantee the sportsbook still accepts a price. One transaction per sport
can roll back other events in that sport after one DB failure. Snapshot captures do
not establish provider historical observation times. Run files need future retention.
Manual history ingestion retains its existing separate lifecycle/coordination design.

Recommend next milestone: run the opt-in PostgreSQL integration suite on a disposable
database, add browser E2E coverage for expiry/unavailable retained selections and
reconnection, then plan stable event/alternate-line schema identity with operator
remediation for ambiguous legacy records. Do not begin that work as part of this change.


## File inventory

- Ingestion: `backend/scripts/fetch_odds.py`, `backend/scripts/refresh_demo_data.py`,
  `backend/scripts/update_line_movement.py`, `backend/seed.py`.
- Services/contracts/config: `backend/app/services/odds_parser.py`,
  `backend/app/services/bookmaker_identity.py`, `backend/app/services/ingestion_control.py`,
  `backend/app/services/demo_guard.py`, `backend/app/services/offer_service.py`,
  `backend/app/services/live_refresh_service.py`, `backend/app/schemas.py`,
  `backend/app/config.py`, `.env.example`, `.gitignore`.
- Database/migrations: `backend/app/models.py`, `backend/alembic.ini`,
  `backend/alembic/env.py`, `backend/alembic/script.py.mako`,
  `backend/alembic/versions/20261014_01_offer_provenance.py`, `backend/alembic/README.md`.
- Frontend: `frontend/src/lib/types.ts` (optional provenance metadata only).
- Tests added: `backend/tests/test_milestone2_ingestion.py`, `backend/tests/test_demo_guard.py`,
  `backend/tests/test_ingestion_migration.py`, `backend/tests/test_ingestion_postgres.py`.
- Existing tests updated: `backend/tests/test_live_ingestion.py`,
  `backend/tests/test_odds_ingestion_reliability.py`, `backend/tests/test_offer_availability.py`,
  `backend/tests/test_parlay_service.py`, `backend/tests/test_props_ordering.py`,
  `backend/tests/test_slip_sides.py`.
- Documentation: `README.md`, `docs/milestone-2-ingestion-reliability.md`.
