# Milestone 4A.2 — NBA participation evidence integration

## Scope and completion

This extends the unmodified Phase 4A verified-rest calculator at checkpoint
`e7e79fc84a24c07a7702657e8eb791a3248a9fb2`. It adds durable, append-only evidence,
an offline synthetic-fixture reconciler, read-only repository retrieval, and
persisted-evidence API/browser regressions. It does **not** implement or activate
a live ESPN connector. Existing recorded appearances, minutes, historical research,
offer eligibility, Discover scores, and saved/slip identity remain independent.

No development database or retained provider payload was inspected. Actual live
NBA participation coverage is therefore **unmeasured**, not complete or zero.
The new table has not been installed or populated in development. All demonstrated
coverage is explicitly synthetic and confined to disposable test databases.

## Provider contract audit

The audit used repository code and the original 4A reports, Event/migration,
identity, ranking, and ingestion safety documentation. No live requests were made.
No authorized retained scoreboard/summary/box-score examples were supplied.

| Evidence | Existing repository capability | Missing upstream verification |
| --- | --- | --- |
| ESPN game identity/date | `fetch_player_game_logs.py` reads `eventId`, `events[game_id].gameDate`, opponent display name, `atVs`, and named statistics. | These code assumptions do not establish completed status, actual start/end time, or full schedule coverage. |
| Athlete identity | Roster/game-log pathways use ESPN athlete IDs while matching players. | Persistent exact athlete-to-local UUID mappings were absent; ambiguous names/current rosters cannot prove historical identity. |
| Team identity | `team_directory.py` reads team `id`, display/name/abbreviation and roster athletes. | Durable historical membership intervals and audited odds-provider-to-ESPN correspondence were absent. |
| Actual appearance | Statistical rows may have minutes/statistics. Existing NBA ingestion skips missing/nonpositive minutes. | Zero points is not DNP; missing minutes is not DNP. No audited explicit participation contract exists. |
| Final/postponed/cancelled | Authoritative Events preserve odds-provider identity and scheduled start. | Past scheduled time is not final. No verified scoreboard/summary status mapping or completion chronology is available. |
| DNP/inactive | Not established by existing statistical logs. | Explicit provider classifications, complete roster/box-score inclusion semantics, pagination and omission rules need examples. |
| Coverage | Event and log tables contain retained observations. | Neither is a complete NBA schedule. HTTP 200 or a missing player row cannot establish completeness. |

Accordingly, normalized `status`, `state`, `complete`, `reconciled`, interval and
inventory fields below are an **internal fixture contract**, not alleged ESPN
response fields. No speculative upstream parser, network transport, retry policy,
automatic refresh integration, historical backfill, or Event association was added.

## Durable storage and migration

Additive Alembic revision `20261017_03`, following `20261014_02`, adds one table,
`nba_evidence_records`, rather than duplicating game-log statistics. Six typed
record kinds share one provenance envelope:

| Kind | Identity/context | Normalized payload |
| --- | --- | --- |
| `team` | Namespaced provider team ID | Display name; never historical membership inferred from a current Player field. |
| `athlete` | Namespaced provider athlete ID + exact local Player UUID | Empty payload; the durable crosswalk is explicit. |
| `game` | Provider game ID, equal to record identity | Home/away provider team IDs, scheduled time, nullable actual game/completion times, explicit status. |
| `participation` | Exact local Player UUID + provider game/team IDs | Athlete ID and `appeared`, `dnp`, `inactive`, or `unknown`. No DNP rows enter PlayerGameLog. |
| `membership` | Exact Player UUID + provider team ID | Athlete ID and dated half-open `[starts_at, ends_at)` interval, optionally open-ended. |
| `coverage` | Provider team and optional game ID | Schedule interval/game inventory, or box-score athlete inventory; explicit complete/reconciled booleans. |

Every observation has a UUID, provider (`espn`), sport (`NBA`), kind, provider-local
identity, source, observed time, ingestion time, canonical payload and SHA-256
fingerprint. Input timestamps require explicit offsets, normalize to UTC, and
store as naive UTC consistently with existing models. Response calculations use
Eastern dates. Uniqueness is `(provider, sport, kind, identity, fingerprint)`.
Identical normalized observations replay without insertion; changed observations
append rather than overwrite. Fingerprints include observation time and provenance.
Indexes support namespace/identity, player, team and game lookup. A RESTRICT
foreign key preserves exact local Player identity. There are no new Event links.

ORM update/delete hooks and a PostgreSQL trigger reject observation mutation or
deletion. Namespace, kind, nonempty identity/provenance and fingerprint checks are
enforced. Semantic payload validation is in the shared reconciliation/retrieval
service. Contradictions remain durable; no latest-row-wins reconciliation is used.
In particular a changed game status remains unresolved until separately reviewed
resolution semantics exist; normal status progression is not silently trusted.

The frozen migration validates/adopts a compatible `create_all` table, installs
the append-only guard, and refuses partial/incompatible schemas, indexes,
constraints or guards without automatic repair. It does not rewrite existing
records. Automatic downgrade refuses evidence loss. Readiness now requires exact
revision 03 and validates table shape, FK, uniqueness, checks, live/ready indexes,
and the enabled, correctly defined guard. Readiness never migrates or repairs.
Old frozen revisions 01/02 remain unchanged. Historical revision-02 operational
linkage/smoke/rehearsal authorization scopes remain fail-closed; this milestone
does not silently widen them to revision 03. The historical linkage executor now
compares its explicit revision-02 table allowlist rather than accidentally
requiring newly added metadata. Its PostgreSQL fixture explicitly builds revision
02, and an additional regression proves revision 03 is rejected before DML.

**Operational procedure remains unexecuted:** separately review backup/recovery,
target identity and migration SQL; authorize the intended target; upgrade through
revision 03 in a controlled window; run read-only readiness checks. Application
startup `create_all` is not a substitute for the migration/guard. Deploying this
reader against a revision-02 schema is unsupported. No operational migration was
run here.

## Offline reconciliation and safeguards

`scripts/reconcile_nba_evidence.py` accepts only the internal
`proppulse-nba-evidence-fixture-v1` manifest with `fixture_only: true`, `espn`/`NBA`,
explicit matching dates/team IDs, and normalized records. Dry-run is the default,
does not connect to a database, and returns a canonical digest. The command
overrides configured application routing to memory before application imports.

Bounds: 1–14 inclusive Eastern calendar dates, 1–8 team IDs, 1–1000 records,
2 MB CLI input, and request budget **zero**. No live transport is implemented;
there are no network retries. Writing requires all of `--write`,
`--authorize-fixture-write`, the reviewed `--expected-digest`, and an explicit
`--test-database-url`. Only loopback PostgreSQL `proppulse_test_[a-z0-9_]+`
databases without URL routing options are accepted. Ambient libpq `PG*` routing
is cleared before connecting. Shared service writes also allow isolated in-memory
SQLite fixtures, and reject other targets before any SELECT.

The reusable service does not commit; its caller owns the transaction. Validation
precedes insertion; a nested transaction rolls back an entire failed batch while
preserving previously retained evidence. CLI writes commit only after the explicit
fixture authorization gate. Existing exact NBA Player UUIDs, provider team/game
identity, crosswalks, chronology, bounds and context are required. Participation
and box-score records referencing already-retained games must also match the
explicit date/team scope. Identity collisions are reported and appended, not
silently mapped to a preferred player.

Complete schedule claims must reconcile their exact game-ID inventory with all
known games in the interval, including unfinished/postponed/cancelled records.
Complete box-score inventories must include every explicitly stated known
participant. These checks reject inconsistent fixtures, but do **not** prove an
upstream provider returned its entire schedule/roster. That upstream contract is
still missing; synthetic completeness is an explicit fixture assertion only.

## Repository, confidence and API behavior

`nba_evidence_service.load_verified_evidence` supplies the existing calculator's
typed game, participation, membership and schedule evidence. The same wrapper
serves both player research and the focused rest/workload route. Public schemas,
UUID selectors and 400/404/409/422 behavior remain unchanged. Research performs
SELECTs only, has no provider client, and never invokes the reconciler.

Reads currently bound the ESPN/NBA inventory globally to 20,000 observations.
Exceeding that bound returns unknown verified evidence rather than truncating
and claiming completeness. A player/team/time-scoped query plan and measured
production volume are future work. Malformed/future-clock observations are
excluded and exact coverage withheld. Missing identity links, one provider
athlete mapping to multiple players, or multiple athlete IDs for one player are
quarantined. Mutable `Player.team` is never consulted for historical membership.

The preserved calculator applies these definitions:

- Last confirmed appearance requires explicit `appeared` evidence in an explicit
  completed game with valid chronology. It does not require positive points or
  minutes. Gaps are `Eastern_date(reference) - Eastern_date(game)`; full intervening
  rest days are `max(gap - 1, 0)`.
- DNP/inactive requires explicit classification plus complete reconciled box-score
  coverage listing that athlete, observed after finality and no later than the
  participation observation. Otherwise classification becomes unknown.
- A missing player record is uncovered, never DNP. A known `unknown` record is
  counted separately. A confirmed appearance baseline is required for since-
  appearance counts; absent baseline does not establish zero missed games.
- Exact missed games require continuous dated membership, complete reconciled
  schedules through the reference, known participation for every relevant
  completed game, and no conflicts/invalid evidence. Otherwise the exact count
  is null; explicit DNP/inactive counts form a separately named lower bound.
- Team context is the single team established by dated membership at reference.
  Its previous confirmed completed game supplies the team gap/full-rest figures.
  Back-to-back compares consecutive Eastern dates; a negative claim requires
  adequate coverage. Upcoming reference coverage remains uncertain.
- Contradictory game identities/statuses, same-team same-day duplicate game IDs,
  overlapping incompatible memberships, participation states, crosswalks and
  schedule observations suppress supported exact conclusions. Reconciliation does
  not discard the original evidence or select an arbitrary winner.

No audited selected odds Event-to-ESPN game association exists. Team schedule
facts are measured at the selected Event's **reference timestamp**, using dated
membership. The UI now says **“Back-to-back if playing on reference date”** and
explains that conditional meaning; the API adds the same explanatory note.
This does not verify that the selected Event is an ESPN game for that team.
Event names, dates and current team strings are not used to manufacture a link.

Empty evidence keeps verified status unknown, exact totals null and recorded
appearance/minutes research separately functional. Existing lower-bound,
unknown/uncovered, provenance, sample and experimental-fatigue displays remain.
No model was trained or probability, physiological fatigue, injury-risk or betting
edge claim introduced.

## Verification

Final results are recorded below after execution. All fixtures are synthetic;
provider HTTP is blocked. PostgreSQL verification uses only the owned, loopback,
tmpfs-backed cached `postgres:15-alpine` container
`proppulse-test-4a2-20261017`, with random schemas in `proppulse_test_4a2` and a
separate initially empty `proppulse_test_4a2_browser`. No development database,
provider ingestion or backfill is involved.

Focused evidence tests: **49 passed**, including **24 PostgreSQL scenarios** and
one offline CLI subprocess test; zero external HTTP attempts. Coverage includes
empty evidence, actual API population with exact Prop/Event UUIDs, SELECT-only
requests/history independence, replay, partial lower bounds, absent players,
DNP without trusted coverage, chronology, changed statuses, postponed games,
crosswalk collisions, contradictory schedules/membership endpoints, coverage gaps, trades, future-clock
records, explicit scope rejection, dry-run/write digest gates and database-error
rollback. The existing 41 pure verified-calculator cases cover zero-point/missing-
minute participation, inactive/unfinished/cancelled games, Eastern boundaries,
duplicate IDs and the remaining calculator edge cases.

Migration/readiness tests cover revision-02 preservation, create_all adoption,
repeated revision validation, incompatible schema/guard refusal, database/ORM
append-only enforcement, idempotent uniqueness, FK preservation, readiness
failure modes and refused downgrade. Existing research/Event/odds/ranking and
saved/slip regressions remain part of the full suite.

The full regression run exposed two test/compatibility issues, both corrected:
the historical linkage fixture accidentally used head instead of its approved
revision 02, and an existing tied-Discover comparison assumed independent
unordered SQL statements return identical encounter order. The latter regression
now supplies the same explicit fixture candidate order to both adapters; the
independent raw SQL/value/encounter-order parity test remains intact. No production
Discover query, scoring weight or ordering implementation changed.

| Final check | Result |
| --- | --- |
| Full backend, HTTP blocked | **733 passed**, including **214 PostgreSQL scenarios**, no failures/skips, 132.740 s; **zero external HTTP transport attempts**. |
| Focused persisted-evidence service/API/CLI | 49 passed, including 24 PostgreSQL; zero HTTP attempts. |
| Evidence migration/readiness | 15 PostgreSQL tests passed; also included in full regression. |
| Historical revision-02 linkage | 34 PostgreSQL tests passed, including revision-03 refusal. |
| Inventory adapter equivalence | 10 PostgreSQL tests passed after deterministic test fixture correction. |
| Frontend unit / TypeScript | 68 passed / TypeScript passed. |
| Ordinary uncached production build | Failed downloading existing Google Inter with network `EACCES`. |
| Temporary font-mocked production build | Passed, ten pages. Mock not committed; genuine Inter rendering unverified. |
| Mocked Chrome | 26 desktop + 26 mobile = 52 passed, exit 0. |
| Current-code real-backend Chrome | 16 desktop + 16 mobile = 32 passed, exit 0. |
| Real API preservation | All 14 tables / 115 rows retained identical counts and SHA-256 hashes; zero provider HTTP attempts. |
| Python compilation / whitespace | Passed. |

PostgreSQL is **15.18**. The disposable container is loopback-only, tmpfs-backed,
512 MiB / one CPU / 128 PID limited, with no data mounts. API browser verification
uses a database-enforced read-only role and disabled application lifespan. The
final browser run uses a second separate initially empty
`proppulse_test_4a2_browser_final` database and the latest repository implementation.
It confirms persisted appearances, two missed games, conditional back-to-back,
team rest, partial/unknown coverage and exact Prop/Event selection. All three
fixture contexts retain their recorded-history and offer-availability behavior.
All database activity is fixture setup, isolated migration testing, or read-only
research in these disposable targets.

Owned API/Next servers were stopped. After checking its exact ID, name, test
label, tmpfs, absence of data mounts and loopback port, the disposable PostgreSQL
container was removed. Test reports, screenshots, temporary logs,
font mocks, build/cache artifacts, provider payloads and environment files are
excluded from the changed-file manifest. The Google-font build limitation remains
an explicit verification gap, not a release-ready result.

## Changed-file manifest

Reviewed local-checkpoint manifest (22 source, test and documentation files):

- `backend/alembic/versions/20261017_03_nba_evidence.py`
- `backend/app/models.py`
- `backend/app/routers/players.py`
- `backend/app/services/nba_evidence_service.py`
- `backend/app/services/schema_readiness.py`
- `backend/app/services/verified_event_linkage.py`
- `backend/scripts/reconcile_nba_evidence.py`
- `backend/tests/integration_server.py`
- `backend/tests/participation_fixture.py`
- `backend/tests/test_event_migration_postgres.py`
- `backend/tests/test_history_research.py`
- `backend/tests/test_ingestion_postgres.py`
- `backend/tests/test_inventory_read.py`
- `backend/tests/test_nba_evidence_migration_postgres.py`
- `backend/tests/test_nba_evidence_service.py`
- `backend/tests/test_research_selection.py`
- `backend/tests/test_rest_workload_api.py`
- `backend/tests/test_verified_linkage_postgres.py`
- `frontend/e2e-real/integration.spec.cjs`
- `frontend/src/components/RestWorkloadSection.tsx`
- `frontend/tests/rest-workload.test.cjs`
- `docs/milestone-4a2-nba-participation-ingestion.md`

## Remaining requirements and separate authorization

1. Authorize a bounded **read-only provider contract collection**: named public
   ESPN endpoints, explicit NBA dates/teams/game IDs, maximum requests/rate/retry
   budget, and permitted redacted retention location. Include completed,
   unfinished, postponed/cancelled, overtime, zero-point/missing-minute appearance,
   DNP/inactive, partial/paginated and identity/trade examples. This authorization
   is independent of permission to persist or migrate anything.
2. Audit those actual payloads and completion/omission semantics. Implement and
   fixture-test a versioned provider adapter, safe bounded transport/retries,
   historical crosswalk/membership reconciliation, conflict resolution, and
   completeness rules. Do not promote synthetic field names to ESPN contracts.
3. Separately authorize a disposable live-validation target and bounded writes
   after reviewing a dry-run report; retain provenance and compare provider
   inventory/participation independently. Current fixture-only gates intentionally
   do not permit production ingestion. Verify a real Event crosswalk separately
   if selected-game team assertions are desired.
4. Separately authorize any operational migration, controlled ingestion/backfill,
   deployment or refresh scheduling. Review backup/recovery, readiness and the
   historical operational approval scopes first. None is authorized or executed
   by this milestone.

The foundation is locally testable; trustworthy live NBA coverage remains pending
these contracts and operational reviews. Font-mocked rendering is not genuine
Inter verification and does not establish release readiness. The original
implementation stopped uncommitted; the separately authorized local checkpoint
is recorded below. No push, deployment or Phase 4B work is included.

## Final engineering/security review and local checkpoint

The checkpoint starts at `e7e79fc84a24c07a7702657e8eb791a3248a9fb2`.
Git confirmed exactly the 22 files listed above, with no unexpected source changes.
The complete source/test/migration diff and previous provenance, Event identity,
schema/readiness and ingestion-safety reports were reviewed. Independent security
review identified one additional guard defect: direct service callers could
retain inherited libpq routing even though the CLI clears it.

That confirmed defect is corrected in the shared fixture target guard. It rejects
ambient `PG*` settings before connecting; both database-backed dry-run and write
paths use it. Before application SQL, it checks the physical PostgreSQL connection's
DSN host, loopback host address, port, database and explicit user against the
approved URL, and rejects service/options overrides. This also detects SQLAlchemy
`connect_args` routing changes. SQLite URL query options are rejected. Offline
CLI dry-run still makes no database connection. Three new guard tests cover
ambient routing, effective DSN mismatch and unapproved/query-routed targets without
contacting any unapproved endpoint. The focused evidence suite now has **52 tests**,
including the unchanged **24 PostgreSQL** scenarios.

No remaining confirmed review finding exists. The revision-03 guard is a normal
security-invoker PostgreSQL trigger, not a privilege-granting function. Like other
database constraints it cannot defend against a separately authorized database
owner/superuser changing DDL; operational roles and migrations still require
separate review. Revision 02's approved linkage scope is unchanged. No Event link,
Discover weight, statistical game-log, saved/slip identity or public schema changed.

The additional bounded-read check supplies an over-limit synthetic inventory and
confirms empty verified evidence plus an explicit unknown-coverage note, without
database connection or HTTP. Research requests remain SELECT-only. Synthetic
completeness remains an internal fixture assertion, never independently audited
provider completeness.

Fresh checkpoint verification uses PostgreSQL **15.18** in a new owned container
`proppulse-test-4a2-checkpoint`, ID
`aaa2ba11add36918177d25d3fd08aa19a3b913211f771976be95a70080160e39`,
loopback port **51678**, with tmpfs data/no mounts, 512 MiB/one CPU/128 PID limits.
Backend schemas use `proppulse_test_4a2_checkpoint`; the browser fixture uses a
separate initially empty `proppulse_test_4a2_checkpoint_browser`. Application
lifespan is disabled, refresh off, provider keys blank, provider HTTP blocked, and
browser research uses database-enforced read-only access. Development PostgreSQL
and live provider endpoints were not accessed.

Fresh final checkpoint executions:

| Check | Actual result |
| --- | --- |
| Full backend with external HTTP blocked | **736 passed**, including **214 PostgreSQL scenarios**, no failures/skips, 143.800 seconds; **zero HTTP transport attempts**. |
| Evidence service/API/reconciliation/target guards | **52 passed**, including **24 PostgreSQL**, zero HTTP attempts; included in full total. |
| Evidence migration/readiness regressions | **15 PostgreSQL passed**; included in full total. |
| Historical revision-02 linkage | **34 PostgreSQL passed**, including revision-03 refusal before DML; included in full total. |
| Frontend unit / TypeScript | **68 passed** / passed. |
| Mocked Chrome desktop/mobile | **26 + 26 = 52 passed**, exit 0. |
| Real-backend Chrome desktop/mobile | **16 + 16 = 32 passed**, exit 0. |
| Database preservation | All **14 tables / 115 fixture rows** unchanged by count and SHA-256; **zero provider HTTP attempts**. |
| Normal uncached production build | Failed downloading Google Inter with network `EACCES`; unchanged typography. |
| Temporary font-mocked production build | Passed, ten pages; mock/configuration excluded from Git and genuine Inter rendering unverified. |
| Python compilation / Git whitespace / manifest hygiene | Passed; exactly **22** reviewed text files, no generated/provider/environment/database artifacts staged. |

Owned browser/API processes were stopped and the disposable PostgreSQL container
was identity/label/mount/port checked and removed after verification. Browser
screenshots, generated reports and temporary test logs were removed from the
working tree. Only the reviewed manifest is included in the authorized local
commit, `feat: add durable NBA participation evidence and offline reconciliation`.
The ordinary font build remains a documented environment limitation accepted for
this local checkpoint, and no release-readiness claim is made.

Recommended next phase: a separately authorized, bounded read-only ESPN contract
audit, followed by offline adapter design and conflict/completeness validation.
Live validation, operational migration/write access and any deployment remain
separate approvals. No live connector or Phase 4B work begins at this checkpoint.
