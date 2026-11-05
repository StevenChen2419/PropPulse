# Phase 5B — practical NBA season statistics

Implemented October 18, 2026 from requested HEAD
`aefff28dc4e65ad5298fd1a687d43141ca33cf47`. The initial implementation checkpoint
left changes uncommitted and unstaged. The authorized final local review/commit
checkpoint is recorded below. Both pre-existing untracked reports are preserved.

## Working research experience

The existing player page now leads with one compact Recent Performance / Rest /
Coverage section. It shows L5/L10 points, rebounds, assists and minutes, valid
values per metric, appearance counts, last recorded appearance, calendar gap,
full intervening days, named season, provider, observed time and recorded date
range. Missing data remains unavailable; a missing scope produces one concise
state. Eastern calendar dates remain date-only. Mobile and desktop screenshots
were inspected; the mobile check also asserts no horizontal page overflow.

Player-only research works without an active Prop. Exact selected Props, Events,
unavailable prices, existing line charts, historical hit-rate definitions, saved
props and slip choices retain their existing behavior. Advanced participation and
workload information is available through a collapsed disclosure. Experimental
fatigue stays secondary.

This demonstrates **invented offline NBA-shaped statistics, not current live NBA
coverage**. No real current-season statistical payload was collected or imported.
The earlier authorized normalized observations lack P/R/A and minutes and were
not used as proof of this feature's statistical coverage.

## Reused path and storage

```text
Already collected PlayerGameLog response dictionary
  + reviewed NBA person ID → exact local Player UUID
  + explicit season / competition / actual observation time
    → nba_api_provider.normalize_player_statistics
    → nba_statistics_service.import_player_statistics
    → existing PlayerGameLog
    → nba_season_summary.build_nba_season_summary
    → existing GET /players/{UUID}/research, additive season_summary
    → existing player page / PlayerSeasonSummary
```

There is no HTTP in this path. The existing `nba_api` installation, static NBA
team directory, reviewed immutable crosswalk, numeric helpers and database model
are reused. ESPN parsing/ingestion, trend_service, chart definitions, Discover
ranking and its source allowlists are unchanged. Legacy history charts therefore
continue to use their existing ESPN eligibility rules, even when the new summary
uses NBA.com. NBA-only imports do not populate those historical line charts;
their existing excluded-source explanation can still appear below the summary.

**No database migration, table, column or dependency was added.** Existing schema
revision `20261018_04` remains the prerequisite. It was applied only in the
disposable test databases; there was no operational migration.

## Statistical normalization

`normalize_player_statistics(payload, observed_at=..., crosswalk=..., season=...,
competition=..., max_records=1000)` validates the existing PlayerGameLog result
set. It accepts explicit `YYYY-YY` seasons and Regular Season / Playoffs. Game ID
competition/year prefixes and provider SEASON_ID, when present, must agree.
Malformed/unknown identities, unknown teams, ambiguous/unreviewed crosswalks,
conflicting duplicates and invalid dates reject the batch. Dates cannot precede
October of the named starting year; the following calendar year remains allowed
for exceptional late finishes, with explicit provider IDs retaining season
authority. Identical duplicate
provider player/game rows collapse to one. Responses are bounded to 1,000 rows.

PTS / REB / AST / MIN / BLK / STL / FG3M map to the existing points / rebounds /
assists / minutes / blocks / steals / threes keys. PRA is derived only when its
three components are valid. Counting statistics require finite nonnegative whole
numbers. Zero is valid. Missing, malformed, fractional counts and invalid minutes
remain null. NBA clock strings require nonnegative integer minutes and seconds
below 60; malformed negative/fractional clock forms do not establish appearance.
Minutes above 100 are null. The shared ESPN parser was not changed.

An appearance requires positive valid minutes or a positive supported counting
statistic. All-zero/missing rows remain stored observations without establishing
an appearance or DNP/inactive status. Per-game MATCHUP supplies supported team /
opponent IDs and side, independent of mutable current Player.team, including
trade-shaped fixtures. Game dates anchor Eastern midnight in UTC storage solely
for compatibility with the existing DateTime column. No actual start/completion
instant is invented; current/future Eastern game dates are rejected.

Numeric fields live directly in `PlayerGameLog.stats`. The documented metadata
structure is `stats['_nba']`:

```json
{
  "season": "2026-27", "competition": "Regular Season",
  "nba_player_id": "1627759", "nba_game_id": "0022600001",
  "team_id": "1610612738", "opponent_id": "1610612753",
  "observed_at": "<actual timezone-aware receipt/observation, normalized UTC>",
  "date_precision": "eastern_date", "game_date": "<YYYY-MM-DD>",
  "reviewed_crosswalk": "<review provenance for this exact association>",
  "appearance": true, "provider": "nba_api.stats.playergamelog"
}
```

The durable source is `nba_com_stats`; external game IDs are
`nba_com:<canonical ten-digit NBA game ID>`. This avoids the existing unique
`(player_id, external_game_id)` key colliding with bare ESPN IDs. Original NBA
identities remain separately recorded. Existing created_at/updated_at retain
ingestion/write timing; neither becomes a game completion timestamp.

## Persistence and source selection

The importer consumes the original dictionary and normalizes before writing. It
requires a clean SQLAlchemy Session and exact existing NBA Player UUIDs, uses a
savepoint for atomic batch writes and flushes without committing. The caller owns
the outer transaction and commit. No deletion or other-table write occurs.
Identical replay reports unchanged records. Qualified-ID source/identity/scope
collisions and older observations reject atomically; previously accepted rows
survive failed imports. The NBA evidence fixture writer is not used.

The summary chooses one provider for the whole player/season/competition scope.
Reviewed accepted NBA metadata selects NBA even if no row qualifies as an
appearance; missing eligible samples never trigger ESPN filling. Otherwise ESPN
retains its existing recorded-appearance eligibility policy. Its fallback label
explicitly says competition is not separated and provider observation is unknown.
ESPN records remain stored. This source choice applies only to the additive
summary, not Discover, old hit-rate calculations or the evidence ledger.

The research endpoint accepts optional `season=YYYY-YY` and
`competition=Regular Season|Playoffs` for the new summary only. Default season
uses the reference's Eastern October-through-September convention; explicit
scope is preferable for unusual historical seasons. No season selector was added
to the frontend. The default competition is Regular Season.

## Windows, rest and limits

Choose the newest distinct eligible recorded appearances within the selected
source/scope, then take at most five / ten slots. Each metric averages only its
valid values in those slots. Missing statistics never pull in older replacement
games. Empty denominator yields null. All counts and partial-data notes are
returned in `season_summary` and rendered in the UI.

NBA rows must precede both evaluation and reference Eastern dates. Their actual
observation must also be no later than both clocks; the historical as-known-then
guard is not relaxed. The reference is the selected linked NBA Event, otherwise
evaluation time; legacy Prop dates do not substitute. Calendar gap is reference
Eastern date minus latest retained appearance date; full intervening days is
`max(gap - 1, 0)`. Upcoming references disclose potentially missing intervening
appearances. Neither gap establishes complete coverage, absence or recovery.

The invented 12-appearance browser fixture has October 4–15 recorded coverage,
October 18 observation, and October 20 Event reference: gap **5**, intervening
days **4**. Player-only evaluation on October 18 gives **3 / 2**.

| Metric | L5 average / valid values | L10 average / valid values |
| --- | --- | --- |
| Points | 4.00 / 4 of 5 | 9.56 / 9 of 10 |
| Rebounds | 1.75 / 4 of 5 | 4.67 / 9 of 10 |
| Assists | 2.80 / 5 of 5 | 5.40 / 10 of 10 |
| Minutes | 32.25 / 4 of 5 | 34.89 / 9 of 10 |

Recorded gaps and aggregate samples remain useful without complete team
schedules. DNP/inactive classification, historical membership reconstruction,
verified missed-game totals, NBA Live parsing, full schedule completeness,
automatic polling, queues, Redis and ML training were deliberately left dormant.
The existing evidence ledger and all its guards remain operational and unchanged.

## Implementation verification

Reused the existing PostgreSQL schema fixture, migrations, blocked-provider test
runner and read-only browser integration server. Owned `postgres:15-alpine`
container `proppulse-test-5b`, ID
`b8d6c040f92f3542f26da532c2f13fb34959c57d4dd1a32f22315523f5377552`, label
`proppulse.milestone=5b`, loopback `127.0.0.1:52468`, tmpfs data, no host mounts,
512 MiB / one CPU / 128 PID limits. Queried version **15.18**, revision
**20261018_04**. Tests used `proppulse_test_5b` random schemas; browser databases
were separate empty `proppulse_test_5b_browser` and `_browser_final`.

The API harness disables refresh/lifespan, blanks provider keys and blocks
external HTTP; the browser API role is PostgreSQL-enforced read-only. Browser
checks restrict requests to the two local origins. Final preservation records
all **15 tables / 147 rows** unchanged by counts and SHA-256, including history,
saved props and slip choices, with **zero provider HTTP attempts**.

| Implementation checkpoint | Result |
| --- | --- |
| Full blocked-provider backend suite | **897 passed**, including **256 PostgreSQL scenarios**, 156.584 seconds, no failures/errors/skips; zero external HTTP attempts. |
| Focused normalization/import | 10 passed, including 3 disposable PostgreSQL persistence tests; no skips. |
| Focused summary / API | 6 passed, including 1 disposable PostgreSQL API test; no skips. |
| Existing NBA adapter suite | 33 passed, including 8 PostgreSQL tests; no skips. |
| Full frontend `npm test` | 76 passed, zero failures/skips. |
| `npx tsc --noEmit` | Passed, exit 0. |
| Normal `npm run build` | Passed, ten routes; no font mock. Cold-cache external font acquisition not independently tested. |
| Combined desktop/mobile Playwright | 38 passed / 4 intentionally skipped, exit 0. Includes 32 existing workflow checks, 4 synthetic evidence cases and 2 new statistics cases. Real-observation-only mode is skipped because no actual-source artifact was supplied. |
| Python compilation | Passed for app, scripts, tests and Alembic; no ingestion script executed. |
| Whitespace | Tracked diff and all nine new implementation/report text files passed. |

The first full backend run found two legacy API mock errors from assuming an
Event attribute; the guarded reference access was fixed and the focused history
suite passed 10/10. The first browser run passed the new summary checks but failed
12 existing advanced-section checks because they did not open the new disclosure.
Tests now click it before asserting the original content; assertions were
retained. The successful final combined result above is a separate complete run.
Independent review also found and corrected malformed minute clocks and
NBA-only empty-scope fallback, with regressions. No lint command was run because
this package has no configured lint workflow. No live provider/cold-cache font,
operational ingestion, current-season coverage or deployment validation is claimed.

Ignored local evidence is under `backend/data/odds_runs/5b/`: research JSON,
preservation fingerprints and inspected desktop/mobile screenshots.

## Actual changed files

- `backend/app/services/nba_api_provider.py`: dedicated statistics normalizer.
- `backend/app/services/nba_statistics_service.py`: narrow atomic importer.
- `backend/app/services/nba_season_summary.py`: provider selection and compact calculations.
- `backend/app/routers/players.py`: additive summary, explicit optional scope, player-only support.
- `backend/tests/nba_statistics_fixture.py`: clearly invented provider-shaped rows.
- `backend/tests/test_nba_statistics_import.py`: normalization and PostgreSQL persistence regressions.
- `backend/tests/test_nba_season_summary.py`: window/source/rest and PostgreSQL API regressions.
- `backend/tests/integration_server.py`: existing harness seeds the statistics fixture through the importer.
- `frontend/src/lib/types.ts`: additive summary types.
- `frontend/src/components/PlayerSeasonSummary.tsx`: compact performance/rest/coverage.
- `frontend/src/app/player/[id]/page.tsx`: summary placement and secondary advanced disclosure.
- `frontend/tests/season-summary.test.cjs`: rendering and denominator states.
- `frontend/tests/research-navigation.test.cjs`: player-only summary regression.
- `frontend/e2e-real/nba-statistics.spec.cjs`: actual offline API/browser statistics checks.
- `frontend/e2e-real/integration.spec.cjs`: opens advanced disclosure for existing assertions.
- `frontend/e2e-real/nba-rest-demo.spec.cjs`: opens advanced disclosure for existing assertions.
- This report.

## Implementation safety and remaining setup

Provider requests: **0 NBA.com, 0 ESPN, 0 Odds API**. Previous request permission
was not reused. No development PostgreSQL connection, operational migration,
backfill, ingestion run, automatic refresh, configuration change, deployment,
commit, staging or push occurred. The supported importer is ready for a separately
reviewed caller; it is not wired to an automatic or operational execution command.

To populate real statistics, separately review the exact local Player UUID ↔ NBA
person crosswalk and season/competition/date/row bounds, obtain bounded provider
request authorization (or supply already-authorized raw statistical responses),
then separately approve the target application import and caller-owned
transaction. Confirm existing revision04 readiness under operational approval.
Never replay the disposable fixtures as real player results. Missing provider
coverage remains unavailable; season/sample/source disclosures must stay visible.

Preserved Phase 5A SHA-256:
`2efcc90e58203aba9ac81980d3cf143b561296943faa9fbb23acd05f38231f96`.
Preserved Phase 4A.4 SHA-256:
`369d01900c5e69681fadc2438c214643136490b4f7b2703868920c4845e171b3`.
Both remain untracked and unstaged. Final status contains eight modified tracked
files and nine new Phase 5B files, plus those two preserved untracked reports;
nothing is staged and HEAD remains the requested checkpoint.

After final preservation checks, the exact owned fixture API process was stopped
and the verified container above was removed. All three disposable databases
disappeared with its tmpfs storage. Ports 8000, 3199 and 52468 had no remaining
listeners. No development container, database or unrelated process was touched.

## Final engineering review and authorized local commit

The user authorized one local commit named
`feat: add practical NBA season statistics to player research`, from unchanged
starting HEAD `aefff28dc4e65ad5298fd1a687d43141ca33cf47`. All 17 Phase 5B files
were reviewed, including independent backend and frontend reviews. No team or
opponent feature work was started.

Two confirmed defects were corrected within the original manifest:

- The normalizer's year-only date check allowed January–September of the named
  starting year into that season. It now rejects dates before October while
  retaining the following calendar year, including a synthetic late October
  2020 fixture explicitly scoped to 2019–20 playoffs. Game ID / SEASON_ID remain
  authoritative; no actual schedule completeness is inferred.
- During same-player Prop navigation, the frontend could display the previous
  selection's season summary while the new request was pending or failed. The
  summary and advanced disclosure now use the existing exact-selection guard.
  Unit and desktop/mobile browser regressions cover pending, failed and recovered
  selections. Player-only summaries remain supported.

Additional regressions explicitly confirm positive P/R/A with missing or zero
minutes establishes an NBA appearance throughout normalization and summary.
Missing minutes contribute no minute sample; an explicit valid zero minute value
does, when positive counting statistics independently establish the appearance.
Zero P/R/A values remain valid. All-zero/missing rows do not assert appearance,
DNP or inactive status. Existing ESPN/chart eligibility remains unchanged.

Review confirmed provider-qualified identity, reviewed crosswalks, atomic failed
import preservation, independent fixed-window denominators, no ESPN/NBA mixing,
accurate observation timestamps, Eastern calendar arithmetic and player-only
research. No models, migrations, odds/freshness, Discover allowlists/ranking,
authentication, evidence-ledger logic or user persistence code changed.

Final verification uses owned disposable PostgreSQL 15 container
`proppulse-test-5b-review`, ID
`8b7227e0028a5500a362a5f56dc37a4185c6d46272a519baa04fed05573184a5`, label
`proppulse.milestone=5b-review`, loopback `127.0.0.1:52469`, tmpfs data, no host
mounts, 512 MiB / one CPU / 128 PID limits. Final backend tests use
`proppulse_test_5b_review_final`; final browser tests use the separate initially
empty `proppulse_test_5b_review_browser_final`. Only disposable migrations through
`20261018_04` are applied. The existing API harness disables lifespan/refresh,
blocks external HTTP and enforces a PostgreSQL read-only API role.

| Fresh final check | Result |
| --- | --- |
| Backend blocked-provider regression suite | **899 passed**, including **256 PostgreSQL scenarios**, 153.242 seconds, no failures/errors/skips; zero external HTTP attempts. |
| Focused import/normalization after final date correction | 12 passed, including 3 PostgreSQL scenarios, no skips, zero HTTP attempts. |
| Focused season summary/API | 6 passed, including 1 PostgreSQL scenario, no skips, zero HTTP attempts. |
| Full frontend unit suite | 78 passed, no failures/skips. |
| TypeScript | Passed, exit 0. |
| Normal production build | Passed, ten routes; no font mock. |
| Desktop/mobile browser regression | **40 passed / 4 intentionally skipped**, exit 0, 31.0 seconds. Includes 32 existing workflows, four synthetic evidence checks and four practical-statistics/navigation checks; actual-source-only cases intentionally skipped. |
| Python compilation | Passed for app, scripts, tests and Alembic after final source correction. |
| Python dependencies | `pip check`: no broken requirements. |
| Frontend dependencies | `npm ls --all --omit=optional`: exit 0, no missing/invalid required dependencies; existing optional-platform gaps and extraneous installed WASM artifacts were not changed. |
| Whitespace / staged manifest | Checked before the local commit; exactly the 17 reviewed files. |

An in-progress backend checkpoint was replaced after the late-season boundary
review. The initial browser attempt passed the existing 38 cases but the new
test's alert selector also matched Next's route announcer; the test now targets
the application error paragraph and recovers through reload. Final results above
refer to separate successful executions, not summed or inferred passes.

The two previously untracked reports retain their hashes above and are excluded
from staging. No fixture artifacts, screenshots, database files, logs or build
outputs are included. Provider requests remain **zero**. No development database
connection, operational import/migration, automatic NBA refresh, push or deployment
is authorized or performed. Current-season real data still requires independently
reviewed exact UUID mappings, authorized statistical responses and separately
approved application import/transaction setup. Offline fixtures prove integration,
not live NBA coverage.

The final browser database reported PostgreSQL **15.18** and revision
**20261018_04**; all **15 tables / 147 rows** matched their baseline counts and
SHA-256 fingerprints, with **zero provider HTTP attempts**. Final ignored
preservation evidence and screenshots are under `backend/data/odds_runs/5b-review/`.
After preservation and exact process/container identity checks, the owned API and
review container were removed, including all disposable review databases. Ports
8000, 3199 and 52469 had no remaining listeners. No development service was touched.
