# Milestone 4A.6 — bounded real NBA rest demonstration

## Outcome and limits

Started at `4f66881df2f184fbc03d51adf20dba707722795a`. No production
implementation, schema, configuration, ranking, persistence or calculator changed.
The existing adapter → reviewed crosswalk → append-only store → research API →
RestWorkloadSection path is reused. The authorized final local checkpoint is
recorded below; the initial implementation was left uncommitted for review.

**Partial demonstration:** two real January 15, 2021 NBA appearances were collected
under new explicit authorization. At a fixed collection-day diagnostic reference,
the real research page can display their dates, partial coverage, date-only
precision and derived gaps. This is a narrow historical sample, **not either
player's current latest appearance or measured recovery**.

The requested January 2021 historical-reference rest demonstration remains
unfulfilled. Existing finality rules reject date-only observations collected after
the selected reference when no actual completion timestamp is known. The actual
October 2026 observation time is preserved; no timestamp was backdated and no
completion instant invented. Selecting the January reference correctly displays
Unknown. Synthetic offline rehearsal independently exercises the 3/2-day example.

L5/L10 averages, season minutes and minutes trends remain unavailable for these
demo players. The evidence store holds appearances, not statistical game-log
windows. No PlayerGameLog rows were fabricated or copied to fill the screen.

## Identity review and source collection

No development PostgreSQL was inspected. Existing synthetic fixtures used random
local UUIDs, so dedicated disposable identities were explicitly assigned. The
installed `nba_api==1.11.4` bundled static player directory independently confirms
each exact person ID/name; the reviewed mapping is not a name-based development
match. Its per-association provenance is bound into the append dry-run digest.

| Display identity | NBA person ID | Exact real-demo Player UUID | Supported game |
| --- | --- | --- | --- |
| LeBron James | 2544 | `4a600000-0000-4000-8000-000000000001` | `0022000187`, Jan 15, 2021; LAL/NOP |
| Jaylen Brown | 1627759 | `4a600000-0000-4000-8000-000000000002` | `0022000180`, Jan 15, 2021; BOS/ORL |

Both use season **2020-21 Regular Season**, bounded inclusive date range
**2021-01-15 through 2021-01-15**. Display names explicitly append
“Jan 15 2021 coverage; fixture reference”; team/market/Event labels identify
fixture reference clocks and unknown current membership.

The repository contained synthetic dictionaries and the prior probe's sanitized
success/row-count report, but no suitable retained real response. The prior
three-request budget was exhausted. The user separately authorized exactly these
three new requests during this milestone:

| Order | URL | Exact parameters | Result |
| --- | --- | --- | --- |
| 1 | `https://stats.nba.com/stats/playergamelog` | PlayerID=2544, Season=2020-21, SeasonType=Regular Season, DateFrom=01/15/2021, DateTo=01/15/2021, LeagueID empty | Success; 1 row |
| 2 | same PlayerGameLog URL | Same parameters, PlayerID=1627759 | Success; 1 row |
| 3 | `https://stats.nba.com/stats/leaguegamelog` | Counter=0, Direction=ASC, LeagueID=00, PlayerOrTeam=T, Season=2020-21, SeasonType=Regular Season, Sorter=DATE, same date bounds | Success; 14 team rows |

Each GET had a ten-second timeout, no retries or redirect following, and at least
two seconds after the prior attempt finished. The existing `nba_api` endpoints
used a bounded requests Session. No Live, ESPN, odds or paid-provider requests
occurred. **Request count: 3; this new authorization is now exhausted.**

No raw responses were written. Only ten normalized records were retained in an
ignored local artifact: four team identities, two paired completed-result games,
two athlete crosswalks and two appeared observations. Team reconciliation was
required by the existing PlayerGameLog adapter; the LeagueGameLog response was
filtered locally for Boston/Los Angeles games, including their opponents. Both
normalizers reported no issues. Normalized collection time is
`2026-10-18T20:58:08.542417+00:00` (4:58:08 p.m. Eastern).

Actual source fields consumed: Player_ID, Game_ID, GAME_DATE, MATCHUP and positive
MIN for appearance; TEAM_ID, GAME_ID, GAME_DATE, reciprocal MATCHUP, complementary
WL and consistent PTS for paired team results. Person IDs normalize to canonical
decimal strings and game IDs to ten digits. Statistics/score values are not
retained by this evidence adapter. W/L reconciliation does not assert schedule
completeness. Missing rows never become DNP or inactive.

Ignored normalized artifact: `backend/data/odds_runs/4a6/normalized.json`, SHA-256
`6e52e36b146de738d427a08c76e76ca010709305717e230bcefa15507638b2a8`.
It is deliberately excluded from Git and is not a raw provider fixture. The
temporary collector is also ignored and must not be rerun without new permission.

## Reference clocks, selection and calculations

Fixture Events have provider `synthetic_fixture_4a6_real_reference`, synthetic
provider IDs and labels. They are reference clocks only; no NBA game ID is linked
to an odds Event. Props have no PropBook offers, null prices and are inactive.
They remain researchable by exact UUID but cannot appear as actionable inventory.
The real application route is `/player/{Player UUID}?prop_id={Prop UUID}`.

| Player | Diagnostic Event / Prop suffixes | Historical Event / Prop suffixes |
| --- | --- | --- |
| James | `000000000001` | `000000000011` |
| Brown | `000000000002` | `000000000012` |

Event UUID prefix: `4a600010-0000-4000-8000-`; Prop UUID prefix:
`4a600020-0000-4000-8000-`. All selections remain distinct and immutable.

| Context | Reference UTC / Eastern | Date gap / full intervening days |
| --- | --- | --- |
| Actual-source diagnostic | Oct 18, 2026 21:00 UTC / Oct 18 17:00 Eastern | 2102 / 2101, partial coverage |
| Actual-source historical selection | Jan 19, 2021 00:00 UTC / Jan 18 19:00 Eastern | Unknown: final observation collected after reference |
| Separate synthetic rehearsal | Same January 2021 reference; invented pre-reference observation | 3 / 2; synthetic only |

January 15 games anchor at `2021-01-15T05:00:00+00:00`, Eastern midnight.
`time_precision=eastern_date`; actual start and completion times are unavailable;
`completed_at` remains null. Arithmetic independently uses calendar dates:
`date(2026,10,18) - date(2021,1,15) = 2102`; full intervening days = 2101.
Offseasons are included as calendar time; the result does not assert no intervening
appearance. The UI shows the 2021 appearance, 2026 reference and coverage warning.

Team rest, team back-to-back, exact missed totals, current/historical membership,
schedule completeness and DNP/inactive classification remain Unknown. Zero DNP
observation counters do not mean zero actual missed games. Positive minutes only
establish the retained appearance, not recovery, workload trends or an absence.

## Disposable database and replay

Owned container `proppulse-test-4a6`, ID
`774313d878afa93f7d2dfb7b934a5f2e652314257087e986dd771f8a03f9e1b9`,
label `proppulse.milestone=4a6`, cached `postgres:15-alpine`, loopback
`127.0.0.1:52466`, tmpfs-only PostgreSQL data, no mounts, 512 MiB memory,
one CPU and 128 PID limit. Trust authentication was confined to this temporary
loopback test container; no application credential was used.

Random test schemas used `proppulse_test_4a6`. The first browser database was
`proppulse_test_4a6_browser`; the corrected real-only dataset used
`proppulse_test_4a6_real_browser`. Existing migrations were pinned through
`20261018_04` only. No operational migration or development backup was accessed.

The browser harness overrides settings before app imports, disables refresh,
blanks provider keys, disables lifespan and uses a PostgreSQL-enforced read-only
API role. HTTP transports are blocked server-side and browser requests restricted
to the two local origins. The loader guards the test target before artifact I/O,
validates exact directory/crosswalk associations and actual observation times,
uses the existing dry-run digest gate and never commits on the caller's behalf.
Identical replay adds no evidence. Research requests are SELECT-only.

Replay requires a newly owned empty loopback `proppulse_test_*` database and the
explicit `PROPPULSE_TEST_POSTGRES_URL`. Supply the ignored normalized artifact
using `PROPPULSE_NBA_DEMO_NORMALIZED_FILE` to `tests/integration_server.py`;
otherwise the server uses synthetic rehearsal only. Replay makes zero provider
requests. Never point this harness at development or run the collector implicitly.

The first browser attempt mixed invented same-team/date NBA games with actual
observations; the calculator correctly quarantined these conflicts. The harness
now excludes synthetic NBA rehearsal records when actual observations are loaded.
Independent synthetic tests remain in isolated databases. Historical/inactive
fixture markets are absent from the live game feed; navigation uses their exact
research route rather than inventing an actionable offer.

## Verification and artifacts

Synthetic unit fixtures simulate source shape and metadata; they are not retained
NBA payloads. Real-source browser assertions use the authorized normalized artifact.

| Check | Actual execution result |
| --- | --- |
| Full backend `tests/run_no_provider_http.py` | 875 passed in 157.526 s, 249 PostgreSQL scenarios, no failures/skips; zero HTTP attempts. This run preceded the last two additive helper scenarios; those were then included in the focused run below. |
| Final focused `test_nba_rest_demo.py` | 22 passed, including 11 PostgreSQL scenarios; no skips; zero HTTP attempts. Covers real-source-shaped synthetic normalization, directory/reviewed crosswalk, conflicts, both reference clocks, append replay, no statistical rows, read-only API, exact UUIDs and independent minutes preservation. |
| Frontend `npm test` | 69 passed, no failures/skips, including populated NBA rendering, history, saved/slip identity and unavailable prices. |
| `npx tsc --noEmit` | Passed, exit 0. |
| Production `npm run build` | Passed, ten routes, ordinary build without setting a font mock; independent cold-cache font retrieval not assessed. |
| Existing real-backend browser regression checks | 32 passed (16 desktop + 16 mobile), covering Discover/feed, exact Event/Prop selection, odds changes, saved/slip persistence and minutes. The exploratory combined runs still failed the new demo navigation assertions described below. |
| Final collected-real-observation browser checks | 4 passed, exit 0 (2 desktop + 2 mobile), no skips in this focused run. Includes real populated UI, both historical Unknown selections, reload, source/precision labels, independent Eastern arithmetic and screenshots. |
| Final separate synthetic browser rehearsal | 4 passed, exit 0 (2 desktop + 2 mobile), no skips in this focused run; explicitly synthetic 3/2-day example. |
| PostgreSQL version/revision | 15.18 / `20261018_04`, queried only in disposable browser DB. |
| Python compilation | `compileall -q` for app, scripts, tests and Alembic passed; scripts not executed. |
| Whitespace | Git tracked diff check passed; new files separately checked for trailing whitespace. |

There were **40 successful browser scenarios across the separate final/regression
executions**, not a claim that the final combined 40-test command passed. The
first exploratory combined run failed eight new demo checks because invented and
actual game identities conflicted. After isolating them, subsequent combined runs
passed the 32 existing checks but failed four actual-source navigation checks;
the synthetic checks were intentionally skipped in actual-source mode. Fixture
Props correctly have no live feed links or alternate inactive-game selector
options. After correcting the tests to navigate exact research URLs, the two
focused final browser commands each passed all four scenarios. Assertions and
production eligibility rules were not relaxed.

The actual-source browser database preserved **all 15 tables / 136 rows** by
counts and SHA-256. The separate synthetic database preserved **15 tables / 132
rows**. Both reported zero provider HTTP attempts. These include Alembic's version
table, existing statistical history, user saved props and slip choices. Read-only
role enforcement and SQL observation checks complement the fingerprint checks;
this is real PostgreSQL/API/browser verification, not static rendering alone.

Generated actual-source desktop/mobile screenshots for both players are kept
locally under ignored `backend/data/odds_runs/4a6/screenshots/`, including
`desktop-real-bounded-nba-rest-2544.png` and
`desktop-real-bounded-nba-rest-1627759.png`. The James desktop screenshot was
visually inspected: fixture labels, Jan 15 appearance, 2026 reference, source
disclosure, partial coverage, Unknown team/missed fields and unavailable minutes
are visible. Screenshots and normalized artifacts are not staged.

Windows Playwright's existing managed-server teardown stall required stopping
only the identified owned Next PID after all assertions; both focused runners
then exited 0. Owned fixture Python processes were similarly identified and
stopped. After verifying exact container ID, label, loopback port, tmpfs and lack
of mounts, the owned container was removed. All four disposable databases and
their temporary storage were removed with it. Ports 8000, 3199 and 52466 were
checked for remaining listeners. No development container or data was touched.

No separate ESLint command was run: the package has no lint script/configured
workflow. No paid/ESPN integration, production ingestion, current coverage,
operational migration, deployment or cold-cache font verification is claimed.

## Changed files and remaining work

- `backend/tests/integration_server.py`: pinned disposable migrations, separate
  fixture modes and stable fingerprints including the Alembic version table.
- `backend/tests/nba_rest_demo_fixture.py`: isolated synthetic historical rehearsal.
- `backend/tests/nba_real_rest_demo.py`: explicit test-only normalized observation
  loader and dedicated actual-source research identities.
- `backend/tests/test_nba_rest_demo.py`: focused identity, arithmetic, timing,
  idempotence, read-only and independent statistical-minutes regressions.
- `frontend/e2e-real/nba-rest-demo.spec.cjs`: exact research selection, provenance,
  Unknown states, historical timing guard and desktop/mobile screenshots.
- This milestone report.

For normal application use, separately review operational migration/ingestion
authorization and exact development UUID crosswalks. This loader remains test-only.
Obtain adequate independently supported historical finality to populate a January
2021 reference without falsifying observation/completion times. Any retrospective
research mode would require separate contract/calculation review; none was added.
Populate minutes via the existing statistical history pipeline under its own
authorization. Team rest and missed totals additionally need dated membership,
schedule coverage and verified participation classification. Further provider
requests require new permission. No deployment or push was performed. The final
local commit is separately authorized and described below.

The pre-existing untracked Phase 4A.4 report was not edited or staged; SHA-256
`369d01900c5e69681fadc2438c214643136490b4f7b2703868920c4845e171b3`.

## Final engineering review and authorized local checkpoint

October 18, 2026. HEAD before this checkpoint remained
`4f66881df2f184fbc03d51adf20dba707722795a`. The user authorized exactly the six
Phase 4A.6 files listed above for one local commit titled
`test: demonstrate real NBA rest research end to end`. No calculator, public API,
database model, Discover/ranking logic or production provider configuration changed.
The complete six-file content and applicable instructions were reviewed, including
an independent read-only review. No new provider request was made and the collector
was not executed. The normalized artifact still matches its recorded SHA-256;
its request outcomes, identities and timestamps agree with the original authorized
execution. Raw responses were deliberately not retained and cannot be re-audited.

One confirmed safety issue was corrected in the test harness: initial admin schema
inspection/DDL formerly preceded the evidence service's effective connection
validation. `integration_target` now rejects ambient `PG*` settings before app
imports or engine creation, and the shared `_test_target` inspects the physical
libpq connection before schema inspection, `create_all` or migration. A focused
regression verifies that PGHOSTADDR, PGSERVICE, PGOPTIONS and PGDATABASE are rejected
before any connection. No operational connection or migration was attempted.

Browser verification now requires exactly one two-player fixture mode in its
manifest; a missing or mixed manifest fails rather than silently skipping all demo
checks. It also asserts the real-source metadata flag and the selected reference's
visible “Collection-day diagnostic; old coverage only” label. Original date,
provenance, Unknown-state, nonactionable-price and preservation assertions remain.

The combined-run investigation found fixture isolation and test navigation
assumptions, not an application defect. Invented and real same-team/date NBA games
must not coexist because the existing conflict rules correctly quarantine them.
Inactive fixture markets intentionally have neither live game-feed links nor
other inactive reference options in the research selector. Tests use exact
research URLs for each preserved selection. With those corrections, the combined
command is supported **within one fixture mode**, with the other mode explicitly
skipped. Running all eight NBA demo cases in one database is intentionally
unsupported; the other four cases run against a separate empty database.

### Reproducible offline browser commands

Use a newly owned PostgreSQL 15 instance bound only to loopback with tmpfs and no
development mounts. Create three distinct empty databases: a regression database
and separate real/synthetic browser databases. Do not reuse a populated browser
database; the harness refuses it. The final verification used port 52467 and
`proppulse_test_4a6_final`, `proppulse_test_4a6_final_real` and
`proppulse_test_4a6_final_synthetic`.

In a backend PowerShell terminal, start real mode (the artifact already exists
locally and is ignored; these commands never collect data):

```powershell
$env:PROPPULSE_TEST_POSTGRES_URL='postgresql://postgres@127.0.0.1:52467/proppulse_test_4a6_final_real'
$env:PROPPULSE_NBA_DEMO_NORMALIZED_FILE=(Resolve-Path data/odds_runs/4a6/normalized.json).Path
.\venv\Scripts\python.exe tests/integration_server.py
```

After `npm run build` finishes, in a frontend PowerShell terminal run:

```powershell
# Combined existing regressions plus real demonstration; synthetic cases skip.
npx playwright test --config playwright.integration.config.cjs
# Optional focused actual-observation verification, using the same read-only API.
npx playwright test --config playwright.integration.config.cjs nba-rest-demo.spec.cjs --grep 'collected real NBA observations'
```

Stop only the owned fixture API, then start synthetic mode in the backend terminal
against its separate empty database:

```powershell
$env:PROPPULSE_TEST_POSTGRES_URL='postgresql://postgres@127.0.0.1:52467/proppulse_test_4a6_final_synthetic'
Remove-Item Env:PROPPULSE_NBA_DEMO_NORMALIZED_FILE -ErrorAction SilentlyContinue
.\venv\Scripts\python.exe tests/integration_server.py
```

In the frontend terminal run:

```powershell
npx playwright test --config playwright.integration.config.cjs nba-rest-demo.spec.cjs --grep 'synthetic NBA-shaped'
```

Each browser command manages its own Next server. On this Windows environment,
Playwright teardown can stall after every assertion finishes. Identify the owned
Next listener at port 3199 and verify its process command/ownership before stopping
that exact PID; do not stop unrelated processes. Do the same for the owned API at
8000 after preservation checks, then verify the exact disposable container identity,
label, mounts and loopback port before removing it. Never reuse these commands
against development or rerun the collector to make a test pass.

### Fresh final verification

Earlier counts above describe the implementation-stage runs. These are fresh
executions against the final reviewed source:

| Command/check | Fresh final result |
| --- | --- |
| Backend `tests/run_no_provider_http.py test_nba_rest_demo.py` | **24 passed**, including **12 PostgreSQL scenarios**, 5.768 seconds, no skips/failures; zero external HTTP attempts. |
| Backend `tests/run_no_provider_http.py` | **881 passed**, including **252 PostgreSQL scenarios**, 151.661 seconds, no skips/failures; zero external HTTP attempts. Includes the later helper cases and new routing regression. |
| Frontend `npm test` | **69 passed**, no failures/skips. |
| Frontend `npx tsc --noEmit` | Passed, exit 0. |
| Ordinary `npm run build` | Passed, exit 0, ten routes; no font mock supplied. |
| Combined browser command, real mode | **36 passed / 4 intentionally skipped**, exit 0: 32 existing real-backend scenarios plus four real-source demo scenarios; only the other source mode skipped. |
| Focused actual-source browser command | **4 passed**, exit 0, no skips. |
| Separate synthetic browser command | **4 passed**, exit 0, no skips. |
| Python compilation | Passed for app, scripts, tests and Alembic; no scripts executed. |
| Git whitespace and staged manifest | Passed; exactly the six reviewed Phase 4A.6 text files. No artifacts, screenshots, logs, database files, build outputs or Phase 4A.4 report staged. |

The focused real checks repeat the same four cases from the combined command;
they are not four additional distinct scenarios. Neither the two fixture modes
nor separate commands are presented as a single all-40-passing execution.
The final browser API preserved **15 tables / 136 rows** in real mode and
**15 tables / 132 rows** in synthetic mode, with matching before/after SHA-256
fingerprints and **zero provider HTTP attempts** in both. Fresh actual-source
screenshots and preservation summaries are local ignored outputs under
`backend/data/odds_runs/4a6-final/`.

Final verification used cached PostgreSQL **15.18** in owned container
`proppulse-test-4a6-final`, ID
`2307cb0980e1f5b99b4f16259437d85fa4ddb08791744fa4ee4e862d35134e7a`,
label `proppulse.milestone=4a6-final`, loopback `127.0.0.1:52467`, tmpfs-only data,
no mounts, 512 MiB memory, one CPU and 128 PID limit. The existing migrations were
verified at `20261018_04` inside the disposable real browser database only.
After checking exact ID/label/storage/port and the owned API/Next command lines,
those processes and that container were removed. All three final disposable
databases disappeared with the temporary container. Ports 8000, 3199 and 52467
had no remaining listeners. No unrelated process, development database/container
or backup was accessed.

Final review is satisfactory for the authorized local test/documentation checkpoint.
It demonstrates historical NBA.com observations end to end, **not live current
player coverage**, and does not remove the January-reference finality or statistical
minutes limitations above. The Phase 4A.4 report and normalized artifact retained
their original hashes and remain outside the commit. No push or deployment follows.
