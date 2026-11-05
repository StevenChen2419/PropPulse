# Phase 5D — real NBA statistics in existing research

October 19, 2026. Starting HEAD verified as
`c3bad302fa60513d2c9dd9d7f15d07de9fb0d96d`. Parent/root instructions and
Phase 5A, 5B, 5C, 4A.5 and 4A.6 reports were reviewed. The two pre-existing
untracked reports remain unchanged. The implementation checkpoint left changes
uncommitted; the separately authorized final review/local commit is recorded below.

## Result and scope

**Actual NBA.com statistics reached the existing research UI for three players.**
The authorized PlayerGameLog dictionaries passed through the existing Phase 5B
normalizer and importer into PlayerGameLog, then the existing season-summary
calculator, research endpoint and Next.js page. No statistical calculation,
production importer, model, schema or provider polling behavior was rewritten.

The scope is **2025–26 NBA Regular Season**, requested October 1, 2025 through
June 30, 2026. This is historical performance, not current live form. Separate
2026–27 requests were not authorized or executed; that season's eligible-game
availability was not assessed. Seasons are never combined.

| NBA person ID | Reviewed name | Dedicated disposable Player UUID | Returned / imported rows | Recorded date range |
| --- | --- | --- | --- | --- |
| 2544 | LeBron James | `5d000000-0000-4000-8000-000000000001` | 60 / 60 | 2025-11-18–2026-04-12 |
| 1627759 | Jaylen Brown | `5d000000-0000-4000-8000-000000000002` | 71 / 71 | 2025-10-22–2026-04-10 |
| 203999 | Nikola Jokić | `5d000000-0000-4000-8000-000000000003` | 65 / 65 | 2025-10-23–2026-04-12 |

Exact names/IDs were checked against the installed NBA static directory. These
UUIDs were assigned specifically for this disposable demonstration; no development
Player identity was looked up or inferred from a name. All 196 rows normalized
and established recorded appearances. Missing coverage is not a DNP assertion.

## Authorized requests actually executed

The user explicitly approved the four-request manifest in this chat before any
request. Exactly four GETs executed once, in this order; all returned HTTP 200.
The authorization is exhausted. Do not rerun collection without new approval.

Common parameters: `Season=2025-26`, `SeasonType=Regular Season`, `LeagueID=00`,
`DateFrom=10/01/2025`, `DateTo=06/30/2026`.

| Order | Exact endpoint | Additional parameters | UTC attempt start / finish | Returned result set |
| --- | --- | --- | --- | --- |
| 1 | `https://stats.nba.com/stats/playergamelog` | `PlayerID=2544` | 18:45:22.116 / 18:45:23.005 | PlayerGameLog, 60 rows |
| 2 | `https://stats.nba.com/stats/playergamelog` | `PlayerID=1627759` | 18:45:25.006 / 18:45:25.593 | PlayerGameLog, 71 rows |
| 3 | `https://stats.nba.com/stats/playergamelog` | `PlayerID=203999` | 18:45:27.598 / 18:45:28.220 | PlayerGameLog, 65 rows |
| 4 | `https://stats.nba.com/stats/leaguegamelog` | `PlayerOrTeam=T`, `Counter=0`, `Direction=ASC`, `Sorter=DATE`; no TeamID filter | 18:45:30.225 / 18:45:31.453 | LeagueGameLog, 2,460 team rows |

Every request used a ten-second timeout, zero retries, no redirect following,
and at least two seconds after the preceding completed request. No proxy,
authentication, alternate route, bypass, Live BoxScore, ESPN or paid-provider call
was used. The one-shot local collector rejected proxy configuration and an
existing execution artifact. It is ignored, not a new application collector.
The original response dictionaries and actual receipt timestamps remain only in
ignored `backend/data/odds_runs/5d/authorized_responses.json`.

## Independent source / database / API / UI comparison

The test-only source oracle reads original table headers/rows, parses dates and
numeric values independently, orders distinct actual game IDs, selects the newest
five/ten appearances and computes sum/count per metric. It does not call the
production normalizer, number helper, window function or summary calculator to
obtain expected averages. Its local manifest retains each selected game ID/date
and numeric sample. PostgreSQL tests compare stored values and original IDs to
those samples, then compare research JSON to the independent expected values.
Browser tests compare the displayed values and valid denominators to the same
source oracle. API averages retain two-decimal precision; UI uses one decimal.

| Player | Window / valid values for every metric | PTS | REB | AST | MIN | Covered window dates |
| --- | --- | --- | --- | --- | --- | --- |
| James | L5 / 5 of 5 | 23.0 | 6.6 | 9.2 | 29.2 | Apr 2–12, 2026 |
| James | L10 / 10 of 10 | 19.9 | 7.2 | 9.1 | 32.0 | Mar 23–Apr 12, 2026 |
| Brown | L5 / 5 of 5 | 30.6 | 4.8 | 3.6 | 34.8 | Apr 1–10, 2026 |
| Brown | L10 / 10 of 10 | 30.4 | 6.1 | 5.0 | 36.1 | Mar 18–Apr 10, 2026 |
| Jokić | L5 / 5 of 5 | 25.4 | 12.6 | 9.8 | 33.8 | Apr 1–12, 2026 |
| Jokić | L10 / 10 of 10 | 25.3 | 14.5 | 11.9 | 35.2 | Mar 22–Apr 12, 2026 |

For example, James's latest five source PTS values are 18, 28, 26, 30 and 13:
115 / 5 = 23.0. Their NBA game IDs are `0022501198`, `0022501185`,
`0022501170`, `0022501140`, `0022501116`. Genuine zeros are retained.
Synthetic unit cases separately exercise missing values, valid denominators,
identity rejection, ESPN preservation and rollback; they are not real results.

| Player | Latest recorded appearance | Diagnostic reference Eastern date | Calendar gap / full intervening days |
| --- | --- | --- | --- |
| James | 2026-04-12 | 2026-10-19 | 190 / 189 |
| Brown | 2026-04-10 | 2026-10-19 | 192 / 191 |
| Jokić | 2026-04-12 | 2026-10-19 | 190 / 189 |

References are explicitly synthetic collection-day Events, one minute after the
latest player response observation. They are not actual NBA scheduled games.
Eastern dates are stored using the existing midnight calendar anchor and metadata;
no actual game start or completion timestamp is invented. Actual observation and
ingestion timestamps remain distinct. These large gaps include offseason time and
do not establish no intervening appearances, rest, missed games or recovery.

## Team and opponent coverage

Fixture participants derive from each player's latest exact normalized team/opponent
IDs: James LAL `1610612747` / UTA `1610612762`; Brown BOS `1610612738` /
NOP `1610612740`; Jokić DEN `1610612743` / SAS `1610612759`. They are historical
recorded participants used to choose a research reference, not current rosters.
No NBA game ID was associated with an odds Event.

League results are paired by exact game ID, reciprocal participants, W/L and
scores through the existing normalizer. Five groups were withheld as unsupported
or conflicting: `0022500147`, `0022500578`, `0022500602`, `0022501229`,
`0022501230`. HTTP 200 is not treated as complete coverage. The loader validates
the 2025–26 regular-season game-ID prefix and appends only the final 14-date
interval where both teams belong to the six reviewed reference participants.

Six real completed games were appended: `0022501112`, `0022501130`,
`0022501153`, `0022501174`, `0022501197`, `0022501198`. Deduplication reduces
497 input evidence records to 12 inserts (six teams and six games), with 485
duplicates and zero conflicts. No membership, schedule completeness or
participation evidence was rebuilt. `completed_at` stays null. Latest **stored**
results for the reference teams are LAL Apr 12 (`0022501198`), BOS Apr 10
(`0022501174`) and DEN Apr 12 (`0022501197`); this deliberately partial append
does not establish their actual latest team games. PostgreSQL tests independently
reconcile stored participants to the two original LeagueGameLog rows per game ID.

**The real-sample UI correctly withholds selected team, team rest, back-to-back
and opponent splits.** The latest player appearances are much older than Phase
5C's strict 14-day team-identity requirement. A historical April Event would also
precede October's actual observation, violating as-known-then eligibility.
Neither guard was weakened. The visible explanation says recent reviewed context
is missing or older than 14 days. No negative B2B conclusion is invented.
Historical opponent rows can exist without satisfying selected-Event team context;
no opponent averages are claimed as displayed for these three players.

## Minimal changes and browser behavior

The public API already supported season/competition, but the page dropped them.
The page and API client now forward explicit `season` and `competition` query
parameters, retain them across exact Prop navigation and reload, and cancel/hide
stale requests on scope changes. Older scopes display Historical Performance and
“Historical season statistics; not current live form.” No new season selector,
service, migration or dependency was added. `layout.tsx` remains a server component.

Research URLs use `/player/{dedicated UUID}?prop_id={dedicated Prop UUID}&season=2025-26&competition=Regular%20Season`.
Event UUID prefix is `5d000010`; Prop UUID prefix is `5d000020`; suffixes match
the Player UUID. Props are inactive, null-priced and have no PropBook rows. The
required numeric line is a clearly labeled reference value 0, not a sportsbook
offer. The existing “Verified Event” text means an exact persisted Event link;
the accompanying fixture/reference labels do not assert an actual NBA fixture.

Desktop 1440px and mobile 390px checks passed for all three players, including
numeric values, source, scope, sample counts, dates/gaps in API, exact Prop/Event,
unavailable team explanation, reload, no external traffic and no horizontal
overflow. Six ignored screenshots were captured; James desktop/mobile were
visually inspected. Existing line charts remain governed by their unchanged ESPN
source policy; NBA-only imports correctly show no eligible chart results. The
legacy chart can still label its independent default 2027 season beneath the
explicit 2025–26 summary. This is a known UI limitation, not mixed statistics.
Existing chart, odds, saved/slip and navigation regressions passed.

## Verification and database safety

Owned container `proppulse-test-5d`, ID
`8e2fa9aabe95af2f24b19e1eadd5d3651dca488ec974f6d67660cf9feb4e642c`, label
`proppulse.phase=5d`, cached `postgres:15-alpine`, PostgreSQL **15.18**,
loopback-only `127.0.0.1:52470`, tmpfs data, no mounts, 512 MiB / one CPU /
128 PID limits. Databases `proppulse_test_5d` (isolated regression schemas) and
`proppulse_test_5d_browser` (initially empty browser fixture) only. Existing
migrations through **20261018_04** ran inside disposable storage only.

The existing browser harness disables refresh and application lifespan, blanks
provider keys, blocks external HTTP and uses a PostgreSQL-enforced read-only API
role. All **15 tables / 368 rows** retain identical before/after counts and SHA-256
fingerprints; zero provider HTTP attempts occurred during research. Independent
regression fixtures remain explicitly invented and use separate Player identities;
no invented statistical rows belong to the three real-data sample players.

| Check | Actual result |
| --- | --- |
| Existing statistics focused backend | 12 passed, including 3 PostgreSQL cases; zero HTTP attempts |
| New real-data focused backend | 9 passed, including 2 actual-artifact PostgreSQL cases; zero HTTP attempts |
| Full blocked-provider backend | 928 passed in 154.835 s, no failures/skips; 257 PostgreSQL scenarios discovered; zero HTTP attempts |
| Frontend `npm test` | 85 passed, no failures/skips |
| `npx tsc --noEmit` | Passed, exit 0 |
| Ordinary `npm run build` | Passed, exit 0, ten routes; no font mock |
| Combined real-backend Playwright | 44 passed / 8 intentional alternate-demo-mode skips, exit 0, 36.4 s; includes six real-statistics desktop/mobile cases |
| Python `compileall -q app scripts tests alembic` | Passed, exit 0; operational scripts not executed |

The full backend run preceded the final two opt-in actual-artifact test additions;
both were then included in the focused nine-test successful run. The initial
frontend suite exposed one static test fixture using the old state shape; that
fixture was updated without relaxing assertions. The exploratory six-case browser
run failed a new test's wording assumption (“Unknown” versus the UI's explicit
14-day explanation); the final combined run checks the actual API explanation.
No separate ESLint workflow exists. No live providers were used for verification.

## Changed files and normal-use requirements

- `backend/tests/nba_real_statistics_demo.py`: bounded offline disposable loader and independent source oracle.
- `backend/tests/test_nba_real_statistics_demo.py`: unit, actual-source PostgreSQL, exact-ID, preservation and atomicity checks.
- `backend/tests/integration_server.py`: opt-in actual statistical artifact mode.
- `frontend/src/lib/api.ts`: explicit research scope serialization.
- `frontend/src/app/player/[id]/page.tsx`: historical scope forwarding and preservation.
- `frontend/src/components/PlayerSeasonSummary.tsx`: historical label.
- `frontend/tests/research-navigation.test.cjs`, `research-history.test.cjs`, `season-summary.test.cjs`: scope and rendering regressions.
- `frontend/e2e-real/nba-real-statistics.spec.cjs`: actual source/API/UI checks.
- `frontend/e2e-real/nba-rest-demo.spec.cjs`: recognize separate real-statistics fixture mode.
- This report.

Raw payloads, collector, manifests and preservation evidence stay ignored under
`backend/data/odds_runs/5d/`; screenshots remain under ignored `frontend/test-results/`.
No development PostgreSQL, operational migration/backfill, odds ingestion,
Discover ranking, authentication, persistence implementation, polling, ML,
deployment, commit or push was touched. Normal application use still requires
separately reviewed exact development UUID crosswalks, authorized operational
import/migration scope, and provider coverage adequate for the intended season.
Fresh eligible player-team evidence is required before real selected-team/rest/
opponent panels can populate. Reusing these disposable identities operationally
or falsifying observation times is not an acceptable substitute.

Preserved report SHA-256 values:

- Phase 5A: `2efcc90e58203aba9ac81980d3cf143b561296943faa9fbb23acd05f38231f96`.
- Phase 4A.4: `369d01900c5e69681fadc2438c214643136490b4f7b2703868920c4845e171b3`.

Final tracked Git whitespace checks and new-file trailing-whitespace checks passed.
After exact process command, container ID/label/loopback/tmpfs/no-mount checks,
owned API PID 39832 was stopped and the owned container removed. Both disposable
databases and temporary storage disappeared with it. No listeners remained on
8000, 3199 or 52470. No unrelated process/container was stopped.

Final Git status: eight tracked files modified, four new Phase 5D files untracked
(loader, tests, browser checks and this report), plus the two preserved untracked
reports. Nothing staged, committed or pushed. HEAD remains the starting checkpoint.

## Final review and authorized local commit

October 19, 2026. The user authorized one local commit of exactly the 12 Phase 5D
files listed above, named `test: verify real NBA statistics in player research`.
HEAD and the full tracked diff/new-file contents were reviewed before corrections;
independent backend, frontend and final read-only review were also completed.
There were **zero additional provider requests**. The original four-request
authorization remains exhausted. The original ignored artifact's SHA-256 remained
`7e19720415833449f64f55f5bbb4cd21166f00fe26e01da0571b3358f0fe0666`.

Three confirmed review issues were corrected inside the same file manifest:

- A selected historical NBA summary beside legacy charts' independent default
  season could be misleading. A short notice now names the summary scope and
  explains that the line-based charts/splits below use separate ESPN history and
  their own displayed scope. No chart calculation or source rule was changed.
  Player-only research does not show the notice because no selected chart exists.
- The independent source oracle rejected `YYYY-MM-DDT00:00:00`, a date shape
  already accepted by the production normalizer. It now accepts that shape while
  keeping the Eastern calendar date; no actual start/completion time is inferred.
- The optional actual-artifact multiplayer rollback test assumed at least two
  returned players. It now explicitly skips when a valid artifact contains only
  one player. A separate invented-data multiplayer rollback test always runs.

Four additional ordinary offline regressions cover the supported date shape,
zero versus invalid/missing per-metric values, rejecting pending unrelated session
changes before artifact reads, and later-player rollback without any real artifact.
Frontend regression and browser assertions cover the scope notice, exact selection,
visible last appearance/calendar gap, competition on reload, player-only research
and no horizontal overflow. All three original 60/71/65 real samples and the
source/database/API/UI averages in this report remain validated unchanged.

### Artifact-independent reproduction

No raw file or NBA.com access is needed for normal backend/frontend tests. The
only two actual-artifact PostgreSQL cases require both explicit opt-in variables;
they skip with a clear message otherwise. Browser real-statistics cases similarly
skip based on the ordinary server's absent actual-source manifest. A missing file
with the opt-in variable explicitly set is an error, not fabricated success.
The loader calls the existing physical target guard before artifact I/O or SQL;
the browser harness requires an empty loopback `proppulse_test_*` target and
rejects ambient libpq overrides before connecting. No test-tool target restriction
was weakened. A clone without the ignored artifact can run the ordinary suite.

Use a newly owned disposable PostgreSQL 15 instance, no development mounts, and
distinct empty `proppulse_test_*` databases. In a backend PowerShell terminal:

```powershell
$env:PROPPULSE_TEST_POSTGRES_URL='postgresql://postgres@127.0.0.1:52471/proppulse_test_5d_final'
Remove-Item Env:PROPPULSE_NBA_STATISTICS_DEMO_FILE -ErrorAction SilentlyContinue
Remove-Item Env:PROPPULSE_NBA_DEMO_NORMALIZED_FILE -ErrorAction SilentlyContinue
.\venv\Scripts\python.exe tests/run_no_provider_http.py
# Use a separate initially empty database for the ordinary browser fixture:
$env:PROPPULSE_TEST_POSTGRES_URL='postgresql://postgres@127.0.0.1:52471/proppulse_test_5d_final_offline'
.\venv\Scripts\python.exe tests/integration_server.py
```

In frontend, run `npm test`, `npx tsc --noEmit`, `npm run build`, then
`npx playwright test --config playwright.integration.config.cjs` while that API
runs. Do not rebuild `.next` while serving browser checks. The API disables
lifespan/refresh, blocks provider HTTP and enforces read-only PostgreSQL access.

For optional **offline replay only**, first stop the owned ordinary fixture API.
Use a different empty browser database and set
`PROPPULSE_NBA_STATISTICS_DEMO_FILE` to the already-authorized ignored
`backend/data/odds_runs/5d/authorized_responses.json` (absolute path). Start the
same integration server and run the same browser command. To run focused actual
database/source comparisons, use the regression database and
`tests/run_no_provider_http.py test_nba_real_statistics_demo.py` with that variable
set. These commands have no collection path. Do not execute the ignored collector.
If the artifact is absent, use ordinary mode; new collection requires separate
user authorization. No artifact is downloaded automatically.

### Fresh final verification

| Check | Final executed result |
| --- | --- |
| Full blocked-provider backend, actual artifact opt-in absent | 934 tests: **932 passed / 2 intentional actual-artifact skips**, 158.148 s, 259 PostgreSQL cases discovered; zero HTTP attempts |
| Focused real-statistics without artifact opt-in | 13 tests: **11 passed / 2 intentional skips**; zero HTTP attempts |
| Focused real-statistics, original three-player artifact | **13 passed**, including both actual-artifact PostgreSQL cases, 4.800 s; zero HTTP attempts |
| Same focused suite, ignored one-player subset | **12 passed / 1 explicit multiplayer-only skip**, 2.525 s; zero HTTP attempts |
| Frontend unit suite | **86 passed**, no failures/skips |
| TypeScript | `npx tsc --noEmit` passed, exit 0 |
| Ordinary production build | Passed, exit 0, ten routes; no font mock |
| Ordinary desktop/mobile browser mode, no actual artifact supplied | **42 passed / 10 intentional real-artifact skips**, exit 0, 36.9 s |
| Actual-source desktop/mobile browser mode | **44 passed / 8 intentional other-demo-mode skips**, exit 0, 36.5 s; all six three-player checks passed |
| Python compilation | `compileall -q app scripts tests alembic` passed |
| Python dependencies | `pip check`: no broken requirements |
| Frontend dependencies | `npm ls --depth=0` exit 0; required direct versions satisfied, existing extraneous optional `@img/sharp-wasm32` unchanged |

The final full backend run used no real artifact and preceded only the optional
multiplayer skip correction, which was then verified in the two final focused
runs. No failure occurred in this review checkpoint's executed suites. No
provider calls were made; ingestion-looking full-suite messages are mocked tests.
No separate ESLint workflow is configured. Cold-cache font acquisition and real
2026–27 provider availability were not assessed. The full suite was not repeated
after documentation-only updates or the focused optional-test skip correction.

Final verification used owned container `proppulse-test-5d-final`, ID
`688d0bc676b8fdbf2b2a89ae522d3c6f63326f309afa72bd2788d2b80e2c0bb0`, label
`proppulse.phase=5d-final`, PostgreSQL **15.18**, loopback **127.0.0.1:52471**,
tmpfs-only data, no mounts, 512 MiB / one CPU / 128 PID limits. Databases were
`proppulse_test_5d_final`, `_final_offline` and `_final_real`; existing migrations
were verified through **20261018_04** in disposable storage only. Ordinary browser
data preserved **15 tables / 167 rows**; actual-source browser data preserved
**15 tables / 368 rows**, each with unchanged counts/SHA-256 and zero provider
attempts. Exact 196-row imports/replays remained 60/71/65 inserted and unchanged.

Ignored final evidence is under `backend/data/odds_runs/5d-final/`; screenshots
remain in ignored `frontend/test-results/`. A new James mobile screenshot was
visually inspected, including the distinct legacy-chart scope notice. Both
browser modes exited normally. After exact command/identity/storage checks,
owned offline API PID 924 and actual API PID 31988 were stopped, and the verified
container was removed. Its three databases and temporary storage were removed;
no listeners remained on 8000, 3199 or 52471. Development PostgreSQL and unrelated
services were never accessed or stopped.

The staged manifest is limited to the 12 reviewed Phase 5D text files. The two
protected reports retain their original hashes and stay untracked/unstaged.
Raw responses, collector, screenshots, databases, logs, build outputs and credentials
are excluded. No calculations, source-selection rules, identity semantics,
evidence ledger, models/migrations, rankings, odds freshness, authentication or
saved/slip/watchlist behavior changed. No dependency was added or updated.
The authorized local commit is the final action; no push, deployment, operational
import or automatic refresh follows. Regular 2026–27 use still needs newly
authorized provider scope, exact development UUID review, authorized operational
schema/import work and fresh team context; this milestone does not enable it.
