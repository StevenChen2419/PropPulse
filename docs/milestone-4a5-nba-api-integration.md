# Milestone 4A.5 — NBA API rest and participation integration

## Scope and starting state

Started at the requested HEAD `163a17041071b6b4ef858bccd7d304f990865bca`.
Parent/application AGENTS instructions, Phase 4A rest/workload and verified
participation reports, 4A.2 ingestion, 4A.3 contract audit, and the uncommitted
4A.4 collection/security plan were reviewed. The existing untracked 4A.4 report
is preserved. The initial implementation remained uncommitted; the separately
authorized final review and local checkpoint are recorded below. No deployment
or push is performed.

This adds an offline NBA.com adapter to the existing six-kind evidence store,
verified calculator, player research endpoints, and RestWorkloadSection. It does
not replace or change ESPN game-log ingestion, Discover ranking, saved/slip
state, odds selection, or the server-component layout. Normal research requests
remain database reads; they cannot fetch NBA.com or initiate ingestion.

**Operational status:** NBA Stats connectivity succeeded, but no development
database was accessed, migrated, mapped, or populated. Application metrics will
remain unknown where retained evidence is unavailable. The demonstrated
end-to-end integration uses mocked provider dictionaries and disposable stores;
it is not a claim that real player research is already populated.

## Library and compatibility

Installed and pinned `nba_api==1.11.4` in the existing Python 3.12 virtual
environment. Its requirements are NumPy >=1.26, pandas >=2.2, and requests
>=2.32.3,<3. Existing NumPy 2.4.6 and pandas 2.2.2 were retained. Installation
added requests 2.34.2, urllib3 2.8.0 and charset_normalizer 3.5.2. `pip check`
passes. No application setting or environment file was changed.

Installed endpoint source and upstream documentation were inspected:

- [PlayerGameLog](https://github.com/swar/nba_api/blob/master/docs/nba_api/stats/endpoints/playergamelog.md)
- [LeagueGameLog](https://github.com/swar/nba_api/blob/master/docs/nba_api/stats/endpoints/leaguegamelog.md)
- [Live BoxScore](https://github.com/swar/nba_api/blob/master/docs/nba_api/live/endpoints/boxscore.md)

The library normally requests during endpoint construction. Only the explicitly
invoked probe uses those constructors. The provider adapter is transport-free
and consumes JSON dictionaries, including `nba_response.get_dict()` outputs.
It uses the bundled static NBA team directory without a network request.

## Exactly three authorized public NBA.com GETs

Executed `backend/scripts/probe_nba_api.py --execute` once on 2026-10-18.
No API credentials, authentication, paid provider, development database, proxy
override, alternate route, scraping workaround, retry, redirect following,
pagination or response-URL following was used. Each GET had a 10-second timeout;
at least two seconds elapsed after the previous attempt finished. No raw
response was saved. Only sanitized outcomes, header names and row counts were
printed. Subsequent verification uses mocks and blocked external transports.

The probe source is intentionally not a research-request dependency. Its default
is a dry run. **The request authorization is exhausted; do not rerun --execute
without new authorization.**

| Order / endpoint | Explicit scope | Actual result |
| --- | --- | --- |
| Live BoxScore | `https://cdn.nba.com/static/json/liveData/boxscore/boxscore_0022000180.json` | `HTTPError`, 0.34 s. Status code was not included in the original summary; no success, timeout or specific blocking code is inferred. |
| PlayerGameLog | `https://stats.nba.com/stats/playergamelog`, PlayerID=2544, Season=2020-21, SeasonType=Regular Season, DateFrom=01/15/2021, DateTo=01/15/2021, LeagueID empty | Success, 2.92 s including spacing; one PlayerGameLog row. |
| LeagueGameLog | `https://stats.nba.com/stats/leaguegamelog`, PlayerOrTeam=T, LeagueID=00, Season=2020-21, SeasonType=Regular Season, same date interval, Counter=0, Direction=ASC, Sorter=DATE | Success, 2.72 s including spacing; 14 team rows. This is league-wide team-level data, not a fabricated server-side TeamID filter. |

Game `0022000180`, Boston `1610612738`, and athlete Jaylen Brown `1627759`
are documented in the installed BoxScore example. LeBron James `2544` is the
upstream PlayerGameLog example and bundled player-directory entry. These sources
establish NBA identities, not a mapping to any development Player UUID.

Actual Stats response headers confirmed include Player_ID, Game_ID, GAME_DATE,
MIN, PTS and MATCHUP for PlayerGameLog, and TEAM_ID, TEAM_ABBREVIATION,
TEAM_NAME, GAME_ID, GAME_DATE, MATCHUP, WL, MIN and PTS for LeagueGameLog.
Both also included the documented shooting, rebounding, assist, steal, block,
turnover, foul and video columns. The probe validated result-set shape/row
counts, not every value, historical completeness, or every parsing branch.

**No actual Live response fields or participation enum semantics were validated.**
The installed library documents `personId`, `played`, `status`,
`notPlayingReason`, `notPlayingDescription`, `statistics` and final-game fields.
That is source/documentation inspection, not independent live verification.

## Adapter behavior and evidence limits

`nba_api_provider.py` normalizes numeric NBA person/team IDs and zero-padded
ten-digit game IDs. It requires aware observation timestamps and parses explicit
NBA dates. It never guesses an ESPN identity or odds Event association.

LeagueGameLog games require two distinct known NBA teams, the same game/date,
reciprocal `vs.` / `@` MATCHUP sides, complementary W/L results and consistent
non-tied scores. Incomplete, duplicated or conflicting pairs are withheld. W/L
is treated as a completed-result observation, rather than inferring completion
from age, minutes or a scheduled timestamp. Operational review should confirm
this policy against additional actual results before enabling ingestion.
Optional team scope filters league-wide responses locally.

Stats logs provide a calendar date without a start/completion instant. Their
`game_at` and `scheduled_at` use Eastern midnight strictly as a date anchor,
with `time_precision="eastern_date"`. They do not assert an actual midnight
tip-off. `completed_at` stays null. Current/future Eastern dates cannot establish
date-only finality. Historical finality remains withheld when the observation
arrived after the selected reference. API and UI expose the date precision.

PlayerGameLog records support positive-minute appearances only when the exact
NBA athlete/local UUID crosswalk, game, date and team sides reconcile. Zero
points do not prevent an appearance. Missing/zero/malformed minutes in Stats
remain unresolved; Live candidate parsing cannot independently establish an
operational appearance until its contract is actually validated. Missing rows never become DNP.

A private, explicitly unvalidated synthetic Live candidate parser tests integer
gameStatus=3 and exact
gameStatusText=Final before classifying participation. A recognized final entry
with string played="1", status=ACTIVE and no nonplaying reason/description
supports appearance even with zero points or missing minutes. played="0" alone
does not mean DNP. INACTIVE supports inactive; ACTIVE plus explicit DNP reason
supports DNP only without contradictory statistics or positive/malformed
`minutes` / `minutesCalculated`. Unknown enums, unfinished games, omitted
athletes, duplicated athletes and conflicting states fail closed. These branches
are mocked-contract support pending actual Live semantic review, not verified
live classifications. Public `normalize_live_boxscore` emits no durable records,
and both append and read paths reject all `nba_api.live.*` evidence. No
complete-box-score flag is manufactured.

The pure calculator can reconcile independently supported date-only and instant
observations for the same NBA game only when provider, participants, Eastern date, status and completion
observations agree; a unique precise start is preferred and both sources remain
in provenance. Unvalidated Live source records cannot enter that path.
Contradictory times/statuses are still excluded. Cross-provider
IDs never join automatically. Overlapping same-player dates from different
providers are quarantined until a reviewed game crosswalk exists.

## Identity, storage and migration

No real local Player crosswalk was supplied or inferred. No name-only, team/name,
ESPN-ID or current-roster matching is introduced. `verified_crosswalk` accepts
explicit reviewed NBA person ID → exact local UUID assertions with provenance;
it rejects duplicate keys, many-to-one mappings, missing review and invalid UUIDs.
It returns an immutable `ReviewedPlayerCrosswalk`; the append boundary requires
that reviewed type, and the dry-run digest binds the per-association provenance.
The caller must also preserve review provenance separately; the existing athlete
payload remains the six-kind empty crosswalk payload.

Tests use documented NBA identities Brown 1627759 and James 2544, associated only
with synthetic disposable local UUIDs. The fixtures do not claim any development
player identity. Local Player, Prop and Event UUIDs are preserved exactly.

The existing table's provider CHECK was ESPN-only. Additive revision
`20261018_04` permits `espn` and `nba_com` without rewriting observations, player
FKs, indexes or append-only guards. Revision03's creation contract stays frozen;
its validator can explicitly adopt the newer namespace for `create_all`
compatibility. Readiness now requires revision04 and checks the expanded contract.
**The migration was applied only inside disposable tests. An unmigrated real
database will fail the new readiness prerequisite until separately approved
operational migration.** Downgrade remains deliberately refused.

`append_normalized_evidence` accepts supported NBA Stats records with an explicit
reviewed canonical crosswalk, bounded date/team scope and a matching reviewed
dry-run digest. LeagueGameLog supplies only team/game records; PlayerGameLog
supplies only athlete/appeared records. NBA membership, coverage, DNP/inactive
and unvalidated sources are rejected on append and quarantined on read. It
uses the existing target guard: only named loopback `proppulse_test_*`
PostgreSQL or in-memory SQLite. It appends idempotently, does not commit, and
cannot target development. The original ESPN fixture reconciler remains intact.
There is no operational append command, backfill, refresh worker or polling hook.

Stored provider namespaces and crosswalks load independently. NBA game/team IDs
are prefixed `nba_com:` inside the shared calculator while original durable
provider IDs and sources are retained. Stats records cannot establish
nonappearance, and simulated Live classifications cannot supply verified
operational evidence or missed-game lower bounds. Malformed evidence and conflicting
crosswalks are excluded rather than silently reassigned.

## Calculations and frontend

The existing verified calculator remains the single calculation system:

- Appearance gap = selected reference Eastern date minus the latest supported
  recorded appearance Eastern date. Full rest days = max(gap - 1, 0).
- Previous team game comes from completed provider games for a team supported by
  dated membership at reference time. A latest appearance/current team string
  does not create such an interval, particularly after a trade.
- Team rest uses that previous game's date; a known prior-day completed team
  game proves conditional back-to-back. A negative claim requires complete
  schedule evidence.
- Confirmed missed games count explicit DNP/inactive only. Exact totals require
  continuous dated membership, reconciled schedules and known participation
  throughout the interval. Otherwise show a supported lower bound or unknown.

The new adapters emit **no membership or schedule-coverage assertions**. With
Stats data and a reviewed identity, last recorded appearance/gap/full rest days
can populate as partial coverage. Team rest/B2B additionally require independently
reviewed dated membership. Team context and missed counts remain unknown through the current supported
NBA adapter. Any future broader support requires actual contract validation and
reviewed evidence setup; no override or operational enable flag is supplied.

RestWorkloadSection retains Confirmed / Partial coverage / Unknown labels,
separate player/team metrics and provenance. Date-only game observations have a
visible precision note. Missing evidence never creates a displayed zero. No
claim is made about physiological fatigue, recovery or betting predictions.

## Initial implementation verification

Disposable PostgreSQL uses cached `postgres:15-alpine`, owned container
`proppulse-test-4a5`, ID
`571bee906249231fbb5af3c805e0d5d86af9a0fedd9768de0453754174daabfb`,
loopback 52345, tmpfs data, no mounts, 512 MiB / one CPU / 128 PID limits.
Backend tests use random schemas in `proppulse_test_4a5`; browser tests use a
separate initially empty `proppulse_test_4a5_browser`. Provider HTTP is blocked,
refresh is off and real application lifespan is disabled for browser checks.

Focused mocked provider tests cover final/unfinished games, explicit appearance,
zero points, missing minutes, DNP/inactive, absent/duplicated athletes, unknown
enums, conflicting counting statistics/both duration fields, ID/date parsing,
missing/ambiguous crosswalks, incomplete/conflicting team results, trades,
team/player rest differences, prior-day B2B, mixed-provider conflicts, compatible
Stats/Live observations, read-only research and exact Prop/Event UUIDs.

| Initial implementation check | Actual result |
| --- | --- |
| Full backend with disposable PostgreSQL and external transports blocked | **842 passed**, 145.656 seconds, no skips/failures; **zero external HTTP attempts**. |
| Final focused NBA provider/probe suite | **28 passed**, including six PostgreSQL scenarios; covers the additional three mocked probe guards added after full-suite discovery and the final malformed-statistics guard regression. |
| NBA storage namespace suite | **18 passed**, nine SQLite and nine PostgreSQL scenarios. Included in full suite. |
| Existing evidence / evidence migration / Event migration / ingestion PostgreSQL suites | **52 / 17 / 15 / 11 passed**; included in full suite. |
| Frontend unit tests / TypeScript | **69 passed** / passed. |
| Production build | Passed, ten routes, without font mock configuration. The historical Google Inter fetch limitation did not reproduce in this environment; independent cold-cache font downloading was not tested. |
| Real API + PostgreSQL Chrome desktop/mobile | **32 passed**, exit 0; existing persistence/rest/selection workflows. |
| Latest NBA.com fixture browser regression | **1 passed**, exit 0, after the date-precision UI changes. Earlier six focused mocked browser scenarios also passed. |
| Browser database preservation | **14 tables / 115 synthetic fixture rows** unchanged by count and SHA-256; **zero provider HTTP attempts**. |
| Python compilation / dependency check | Passed (`compileall`, `pip check`). |
| Git whitespace | Passed; final artifact manifest checked separately. |

The first full run found a new test depending on unordered DB game order. The
fixture now explicitly selects the appearance's game; the successful full run
above includes the correction. An initial isolated SQLite fixture setup also
attempted to create PostgreSQL ARRAY user columns; it was corrected to use the
same bounded table subset as the existing API fixtures. Neither issue changed
application behavior or accessed development data.

Windows Playwright managed-server teardown stalled after successful assertions.
The exact runner-emitted owned Next server PID was checked before terminating
that process tree, allowing the 32-test runner to finish with exit 0. This was
local test-process cleanup, not an application change. Generated test output and
logs are excluded from delivery. No lint command was run (there is no configured
ESLint workflow); no stress benchmark or operational ingestion was run.

## Remaining review/setup

1. Review the code, date-only completed-result policy and additive migration.
2. Supply independently verified local Player UUID crosswalks and preserve their
   review provenance; no real local mappings have been assigned here.
3. Separately authorize operational migration and a narrowly scoped, reviewed
   ingestion path. Current append support intentionally permits disposable
   targets only. Do not relax that guard incidentally.
4. If DNP/inactive or broader team metrics are needed, separately authorize a new
   bounded Live validation and establish dated membership/schedule evidence.
   This milestone's three-request budget is exhausted.
5. Keep live transport outside normal research requests unless that behavior is
   explicitly reviewed and approved. No automatic polling/backfill is enabled.


## Changed-file manifest and cleanup

- Adapter/dependency/probe: `backend/app/services/nba_api_provider.py`,
  `backend/requirements.txt`, `backend/scripts/probe_nba_api.py`.
- Shared integration/contracts: `backend/app/services/nba_evidence_service.py`,
  `backend/app/services/rest_workload_service.py`, `backend/app/models.py`,
  `backend/app/schemas.py`, `backend/app/services/schema_readiness.py`.
- Migration: `backend/alembic/versions/20261018_04_nba_com_namespace.py` and
  the narrowly extended revision03 adoption validator.
- Backend regression files: `test_nba_api_provider.py`,
  `test_nba_com_evidence_storage.py`, `test_nba_evidence_migration_postgres.py`,
  `test_event_migration_postgres.py`, `test_ingestion_postgres.py` in
  `backend/tests/`.
- Frontend: `frontend/src/components/RestWorkloadSection.tsx`,
  `frontend/src/lib/types.ts`, `frontend/tests/fixtures/rest-workload.cjs`,
  `frontend/tests/rest-workload.test.cjs`, `frontend/e2e/navigation.spec.cjs`.
- This report. The pre-existing untracked 4A.4 report is preserved separately.

Owned API and Next test processes were stopped. After exact ID/label, tmpfs,
no-mount and loopback-port verification, the disposable container was removed.
The temporary backend verification log was removed. No environment files,
provider payloads, database files, font mocks or generated build artifacts are
included in the source change manifest. No operational migration, development
DB access, backfill, live ESPN/Odds call, deployment, commit or push occurred.


## Final engineering/security review and authorized local checkpoint

This review starts at unchanged HEAD
`163a17041071b6b4ef858bccd7d304f990865bca`. The user explicitly authorizes one
local commit, `feat: integrate NBA API game logs with rest research`, after final
review and verification. Phase 4A.4 documentation remains outside the manifest;
its SHA-256 is `369D01900C5E69681FADC2438C214643136490B4F7B2703868920C4845E171B3`.
No new provider authorization is granted or consumed. The successful Stats and
failed Live results above remain historical observations, not freshly repeated
requests. No real development Player UUID association has been established.

Confirmed review defects and corrections:

- Simulated Live classifications could previously be appended/read as verified
  evidence through a source-label exception. The public Live adapter now emits
  zero durable records; its private candidate parser is explicitly unvalidated.
  Append and load reject/quarantine Live evidence of all six kinds, and the pure
  calculator rejects `nba_api.live.*` observations. No source-label bypass,
  coverage assertion or approval flag can promote these candidates.
- Arbitrary NBA Stats source/kind combinations could assert unsupported DNP,
  membership or complete coverage. The append/read allowlist now accepts only
  LeagueGameLog team/game and PlayerGameLog athlete/appeared contracts. Missing
  records, partial result pairs and unsupported metrics remain unknown.
- Plain dictionary crosswalks bypassed the review wrapper and review provenance
  was not bound to the append digest. Appends now require the immutable reviewed
  mapping and bind its per-association provenance into the digest. Changing
  review provenance invalidates prior write authorization. Exact UUIDs remain
  unchanged; no automatic identity discovery was introduced.
- Date precision previously accepted a label without validating its anchor.
  Date-only records now require prior Eastern midnight, identical scheduled/date
  anchors and no completion instant. Supported Stats games require that exact
  representation. Arbitrary precise start times from Stats are rejected.
- The NBA UI fixture previously showed team B2B despite only Stats provenance.
  It now mirrors supported evidence: appearance available, team context, previous
  team game, B2B and missed counts unknown. Existing complete ESPN fixtures and
  application behavior are preserved.

Independent read-only review found no remaining confirmed defect after these
corrections. Current source and the full changed-file manifest confirm no ESPN
ingestion, odds logic, ranking, saved/slip store, Event-linking or layout change.
Research regressions enforce SELECT-only use and zero provider HTTP.

Revision04 changes only the provider namespace CHECK. Fresh tests verify
revision03-to04 evidence/FK/guard preservation, repeated migration replay without
constraint/guard replacement, and refusal of missing guards or incompatible
namespace checks without repair/revision advancement. **Deploying this application
against an unmigrated revision03 database fails readiness with schema_revision.**
No migration or connection to development PostgreSQL occurred.

Final verification uses fresh owned container `proppulse-test-4a5-final`, ID
`ba28c125571fa3348ad2c76fdd9c1e68e6cce77f4906504ef7edbff97c20934b`,
loopback 52346, cached PostgreSQL 15 Alpine, tmpfs/no mounts, 512 MiB, one CPU,
128 PID limit. Backend random schemas use `proppulse_test_4a5_final`; the separate
initially empty browser DB is `proppulse_test_4a5_final_browser`. External HTTP
transports are blocked, browser sessions database-enforced read-only, refresh
disabled and application lifespan off.

| Fresh final check | Actual result |
| --- | --- |
| Full backend, provider transports blocked | **857 passed**, including **240 PostgreSQL scenarios**, no failures/errors/skips, 147.765 seconds; both HTTP/client transport counters **0**. |
| NBA provider / storage persistence | **33 / 22 passed**; includes **8 / 11 PostgreSQL** scenarios; zero HTTP attempts. Included in full backend run. |
| Evidence namespace migration/readiness | **20 PostgreSQL tests passed**, including three new revision04 regressions. Included in full backend run. |
| Research API and legacy evidence regressions | Passed in full backend run, including SELECT-only research, no provider HTTP, exact Prop/Event UUIDs and existing ESPN fixture contracts. |
| Frontend Node / TypeScript | **69 passed** / passed. |
| Production build | Passed, ten routes, ordinary build with no font mock. Historical Google Inter failure did not reproduce; independent cold-cache font acquisition was not assessed. |
| Final mocked Chrome browser suite | **27 passed**, exit 0, revised Stats-only NBA fixture included. |
| Stable-build real-backend Chrome desktop/mobile | **16 + 16 = 32 passed**, exit 0. |
| Browser database preservation | All **14 tables / 115 fixture rows** unchanged by counts and SHA-256; **0 provider HTTP attempts**. |
| Python compilation / dependency check | Passed (`compileall` for app/scripts/tests/Alembic, `pip check`). |
| Whitespace / approved manifest | Passed; only the 21 reviewed Phase 4A.5 text files are committed. |

One earlier real-browser execution overlapped a frontend production rebuild and
failed a mobile reload (31 passed, one failure). The trace showed HTTP 400 errors
for Next chunk/CSS assets while the build directory changed. After the build
finished, the complete suite was rerun with a stable build and all 32 passed.
No application change or assertion relaxation was used. Windows managed-server
teardown again required terminating only the verified owned Next PID after all
assertions; both final runners completed with exit 0.

No broad stress benchmark or ESLint run was performed; there is no configured
ESLint workflow. Tests used mocked provider dictionaries only. No new NBA.com,
ESPN or Odds request was made. No operational migration/ingestion, backfill,
automatic refresh, deployment, push or next milestone was started.

The final 21-file commit manifest is exactly the Phase 4A.5 manifest above.
The separately preserved Phase 4A.4 report remains untracked, byte-for-byte
unchanged and excluded from staging. Temporary test logs were removed; ignored
browser/build outputs, environment files, caches, database files and raw provider
responses are not committed. Owned API/Next test processes were stopped, and the
fresh disposable PostgreSQL container was removed after verifying its exact ID,
label, tmpfs/no-mount setup and loopback port.

To show real NBA rest data, separately approve operational migration and a
reviewed ingestion path (the current writer still permits only disposable
targets), and supply verified local Player UUID crosswalks with retained review
provenance. Supported Stats results can then provide recorded appearance/gap
research. Team context, rest/B2B and missed-game totals require independently
supported dated membership, schedules and participation contracts. Live
DNP/inactive remains quarantined pending actual source validation under new
explicit authorization. Normal research requests still cannot fetch providers.
