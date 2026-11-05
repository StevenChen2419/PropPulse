# Phase 8: multi-sport research

Implemented shared research and offline adapters, followed by separately approved
real-data imports and a bounded live odds trial across all five supported sports.
The October 20 operational checkpoint below records verified coverage and limits;
earlier preparation entries remain historical. No new tables, migrations or
dependencies were needed. Existing Player, Prop, Event, PlayerGameLog,
saved/slip storage, NBA.com import, odds parser/persistence and freshness rules remain.

| League | Source | Research metrics |
| --- | --- | --- |
| NBA | Existing NBA.com pipeline, unchanged | PTS, REB, AST, MIN |
| WNBA | wehoop WNBA Stats published player game logs | PTS, REB, AST, 3PM, MIN |
| NHL | NHL Web API player game-log | Skater: goals, assists, points, SOG, TOI; goalie: saves, TOI |
| NFL | nflverse week-level player statistics + completed schedule game | Passing yards/TDs, rushing yards/TDs, receiving yards/receptions/TDs |
| MLB | MLB StatsAPI gameLog + final schedule games | Batter: hits, runs, RBI, total bases, HR; pitcher: strikeouts, outs, earned runs |

The shared `season_summary` selects reviewed recorded appearances for the exact
sport, local UUID, season and competition. L5/L10 choose appearances first and use
independent valid-value denominators. Null remains unavailable; zero remains zero.
Provider-qualified game IDs deduplicate records. Source observations must precede
the research reference. Dates are calendar anchors, never invented start times.
NBA delegates to its existing summary without changing its response.

Recorded player gaps and provider-ID opponent history work without odds. Team
rest, current team membership, back-to-back certification and opponent-to-Odds-Event
linkage remain unavailable for new sources. NFL missing weeks never establish DNP.
MLB pitcher appearances and batter appearances have separate metric denominators;
two-way same-game records combine without duplicating the game. `5.2` IP = 17 outs.
Legacy exact-line charts retain their independently disclosed historical scope;
the season selector applies to the season summary, not those legacy charts.

## Sources, formats and usage

- WNBA: [published schema](https://github.com/sportsdataverse/wehoop-wnba-stats-data/blob/main/docs/datasets/player_game_logs.md)
  and [release](https://github.com/sportsdataverse/sportsdataverse-data/releases/tag/wnba_stats_player_game_logs).
  Lowercase `player_id`, `season_id`, `game_id`, `game_date`, `wl`, `pts`, `reb`,
  `ast`, `fg3m`, `min`. Season ID combines competition digit and calendar year.
  Release listings inspected contain historical assets from 1997 and a 2025 CSV;
  presence does not prove complete 2026 coverage. Team rows have null player IDs;
  both competitions share an asset and must be filtered. Reviewed athlete rows
  only. Optional schedule rows establish team/opponent IDs; matchup text alone
  does not. Credit sportsdataverse/wehoop WNBA Stats; normalized fields and
  calculated averages are transformations. [Repository license](https://github.com/sportsdataverse/wehoop-wnba-stats-data/blob/main/LICENSE.md)
  states CC BY 4.0; retain attribution, license link and change disclosure, and
  review upstream league rights before commercial redistribution.
- NHL: [endpoint reference](https://github.com/Zmalski/NHL-API-Reference#player-information).
  Explicit request athlete/season/game-type plus `gameId`, `gameDate`, `toi`,
  `goals`, `assists`, `points`, `shots`; only goalie records can provide `saves`.
  A missing saves field stays null. Split-year seasons use YYYY-YY locally and
  YYYYYYYY in requests. Availability of a particular historical season is not
  established until its response is validated. [NHL terms](https://www.nhl.com/info/terms-of-service)
  require usage review; the community reference grants no data redistribution rights.
- NFL: [week-level loader](https://nflreadr.nflverse.com/reference/load_player_stats.html)
  and [implementation](https://github.com/nflverse/nflreadr/blob/main/R/load_stats.R).
  `stats_player_week_YYYY.csv` is distinct from reg/post season aggregates.
  Current fields include `player_id` (GSIS), `season`, `season_type`, `week`,
  `game_id`, `team`, `opponent_team`, `passing_yards`, `passing_tds`,
  `rushing_yards`, `rushing_tds`, `receiving_yards`, `receptions`, `receiving_tds`.
  Legacy `recent_team` is accepted. Every selected week must join exactly one
  completed schedule game, including identity agreement when game_id is present.
  Loader supports seasons from 1999; 2025 and 2026 weekly CSV assets were listed.
  Credit nflverse and its contributors under [CC BY 4.0](https://github.com/nflverse/nflverse-data/blob/main/LICENSE.md);
  retain attribution/license and disclose normalization and derived averages.
- MLB: [community endpoint reference](https://github.com/toddrob99/MLB-StatsAPI/wiki/Endpoints)
  over MLB-hosted responses. `stats[].splits[]` must match hitting/pitching group,
  reviewed request athlete, season and final gamePk. `totalBases` is not replaced
  when missing. Historical season availability requires validated artifacts.
  [Wrapper copyright notice](https://github.com/toddrob99/MLB-StatsAPI#copyright-notice)
  points to MLB data terms; wrapper code licensing does not license MLB data.

## Offline statistics command

From `backend`, using the existing Python environment:

```powershell
.\venv\Scripts\python.exe scripts/refresh_sports_statistics.py --sports wnba nhl nfl mlb --season current --dry-run
.\venv\Scripts\python.exe scripts/refresh_sports_statistics.py --sports wnba --season 2025 --mapping data/odds_runs/phase8/mappings.json --artifact data/odds_runs/phase8/wnba.json --players LOCAL_UUID --dry-run
# NBA delegates to the existing command, including its existing approval guards:
.\venv\Scripts\python.exe scripts/refresh_sports_statistics.py --sports nba --nba-args --season 2025-26 --from-date 2026-01-01 --to-date 2026-01-31 --all-verified --dry-run
```

`current` resolves each sport separately. Explicit years apply to calendar-year
leagues; use a separate invocation for an explicit NHL YYYY-YY season. NBA uses
its existing argument contract in a separate invocation.

Mappings are a JSON list: `sport`, `source`, `athlete_id`, exact existing
`player_id` UUID, `verified: true`, `provenance`, `identity_evidence`, and reviewed
`roles` (player; skater/goalie; batter/pitcher, both for a two-way player). Optional team
and position annotations can aid review; names alone never authorize a mapping.
The checked-in example is empty intentionally: reviewed local UUID associations
remain in private, ignored import artifacts. Unmapped athletes are rejected.

An artifact descriptor has `sport`, `source`, `season`, `competition`, timezone-aware
`observed_at`, and `responses`. Each response has `athlete_id`, `role` and either
`payload` or adjacent `payload_file` (JSON or published CSV, at most 50 MiB).
CSV loading filters exact athlete/competition rows and retains the asset digest.
WNBA/NFL payloads are lists of source rows. NHL payloads retain the gameLog object
and exact `request_path`. MLB retains the stats object, exact `request_path` and
`request_params`. NFL additionally requires `summary_level: "week"` and `schedule`
source rows. MLB requires `games` final schedule records. WNBA optionally accepts
`schedule` records. See the explicitly invented `tests/sports_statistics_fixture.py`
for small complete descriptors, including source field names.

Dry-run never opens a DB connection or performs HTTP. It reports normalized and
rejected rows; new/updated/unchanged are unknown without a DB comparison. Optional
`--preview-database --database-target host:port/database` uses PostgreSQL-enforced
read-only comparison. **Not run against development.** After validating real
artifacts, save `approval_scope` to an approval JSON and obtain separate approval
for that scope. `--import-approved approval.json` verifies the artifact/mapping/row
digests, exact target, selected players, sport/season/competition and row ceiling
before writing. Rejected batches cannot execute. No automatic collection for new
sources, no deletes and no local Player creation.
An existing bare-ID MLB row for the same official game blocks import pending
explicit identity review; the importer neither duplicates nor overwrites that
legacy history. The read-only preview detects this before a write approval.

## Unified sportsbook refresh

The configured provider is **The Odds API v4**, using the existing key/client,
market config, RequestBudget, PostgreSQL advisory lock and per-sport persistence.

```powershell
.\venv\Scripts\python.exe scripts/refresh_sports_odds.py --dry-run
.\venv\Scripts\python.exe scripts/refresh_sports_odds.py --coverage data/odds_runs/phase8/coverage.json --max-credits 20 --max-requests 20 --dry-run
# Only after explicit approval of both provider spending and exact DB target:
# repeat the command with --execute-approved <displayed-plan-sha256>
```

Coverage JSON has `database_target: "host:port/database"` and `sports` keyed by
the configured sport keys. Each entry has `access` (`accessible`, `unsupported`,
`unknown`, `no_games`), `markets`, exact retained event objects (`id`, `home_team`,
`away_team`, `commence_time`), retained `evidence`, and `roster_directory` in the
existing team-directory format. Accessible requires evidence and nonempty markets.
No roster HTTP is performed; absent retained roster evidence may prevent matches.
Unknown/unsupported sports do not request player odds. An empty plan does no work.

The plan lists every allowed endpoint/event/market, one US region, zero retries,
upper-bound credits (events × markets), request ceiling and 50-credit reserve.
Execution verifies active sport keys and current Event metadata, and never adds
unapproved events or markets. A changed Event is skipped. Credit reservations and
provider headers stop over-budget requests. Failed/empty sports continue independently;
global quota/rate-limit exhaustion stops safely. Invalid-market 422 responses stop
repeated event requests. Existing identity, exact-line comparison, offers and
snapshots, 30-minute live/6-hour last-known and game-start cutoff rules are reused.

Retained status showed past successful WNBA props; NHL showed HTTP 429 frequency
limiting, **not proof of tier exclusion**. Current entitlement is unverified.
Missing lines, absent markets and denied subscription coverage stay unavailable.
The provider's [market inventory](https://the-odds-api.com/liveapi/guides/v4/#get-event-markets)
is recently observed availability, not comprehensive entitlement certification.

## Historical collection manifest (superseded; not executed)

Superseded by the current-season scope below. Retain the original ignored file
byte-for-byte; its digest grants no authority for current-season collection.

Initial source validation uses historical seasons deliberately. All outputs go
under ignored `backend/data/odds_runs/phase8-collection-01/`, separated by sport.
No retries, crawl, roster-wide expansion, fallback host, import or paid statistics
provider is included. Stop on an absent asset, oversized response or usage denial.
GitHub release-asset CDN redirects only are permitted for the named downloads.

| Source / sport / scope | Exact GET endpoints or assets | Maximum |
| --- | --- | --- |
| wehoop WNBA 2025, both source competitions retained; import Regular Season separately | `https://github.com/sportsdataverse/sportsdataverse-data/releases/download/wnba_stats_player_game_logs/player_game_logs_2025.csv` | 1 download, 5 MiB; `wnba/player_game_logs_2025.csv` |
| NHL 2025-26 Regular Season, source athlete 8478402 | `https://api-web.nhle.com/v1/player/8478402/landing`; `https://api-web.nhle.com/v1/player/8478402/game-log/20252026/2` | 2 requests, 2 MiB each; `nhl/8478402-{landing,gamelog}.json` |
| nflverse NFL 2025 week performances + schedule | `https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2025.csv`; `https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv` | 2 downloads, 20 MiB + 5 MiB; `nfl/{stats_player_week_2025,games}.csv` |
| MLB 2025, athlete 660271, hitting + pitching | `https://statsapi.mlb.com/api/v1/people/660271`; `https://statsapi.mlb.com/api/v1/people/660271/stats?stats=gameLog&group=hitting&season=2025`; same endpoint with `group=pitching`; `https://statsapi.mlb.com/api/v1/schedule?sportId=1&startDate=2025-03-01&endDate=2025-11-15` | 4 requests: 1, 2, 2, 15 MiB; `mlb/{identity,hitting,pitching,schedule}.json` |
| NBA | Reuse retained approved NBA artifacts; no new collection in this manifest | 0 requests |

Statistics total ceiling: **9 logical requests/downloads, 54 MiB**, zero development
writes. WNBA opponent IDs remain unavailable without a separately selected/approved
schedule artifact. Mapping review against exact local UUIDs follows artifact
validation; acquiring these public source IDs does not establish local linkage.
Usage restrictions and attribution are listed above; NHL/MLB rights clearance is
required before any disallowed use or commercial redistribution.

Separate sportsbook discovery scope: `https://api.the-odds-api.com/v4/sports` once,
then `/v4/sports/{key}/events` once for each of `basketball_nba`, `basketball_wnba`,
`icehockey_nhl`, `americanfootball_nfl`, `baseball_mlb`: **6 requests, 0 credits,
6 MiB total**, no retries, no DB writes, credential-free artifacts under `odds/`.
Event IDs are unknown until discovery; paid market/odds probes require a subsequent
exact event plan and credit approval. This manifest grants no spending authority.

Development imports still need separate approval after validating artifacts and
reviewing local Player mappings. That request will name the exact database target,
artifact/mapping digests, UUIDs, game IDs, seasons/competition, row counts and
new/update/unchanged preview. No migration is needed.

## Verification

Offline fixture tests cover adapters, missing metrics, role separation, identity
conflicts, season/competition separation, duplicates, weekly-to-game joins,
averages, artifact loading, quota limits and partial failure. Disposable PostgreSQL
tests cover idempotency, updates, read-only preview, rollback and research/search
without offers. Browser fixtures are visibly invented and block external HTTP.
Executed: full backend checkpoint **994 tests, 2 authorized-real-artifact checks
skipped**, with 268 PostgreSQL scenarios discovered and zero external HTTP
attempts. Subsequent focused checks passed: 26 multi-sport tests (4 disposable
PostgreSQL scenarios) and 44 research-selection tests. Frontend: 90 unit tests,
TypeScript and production build passed; 55 browser tests passed, including 14
desktop/mobile sport/role cases. Windows managed-server teardown timed out on
the first browser run; the successful final run used external-server mode and
explicit server cleanup. No live coverage, development imports or production
deployment was tested or performed.

## Real integration preflight — October 19, 2026

- HEAD confirmed `35db0dfdac51de0a5f8c63ad1d96493d51be9fac`; existing
  uncommitted Phase 8 work preserved. No application code changed in preflight.
- Development `localhost:5432/proppulse` checked with read-only transactions:
  revision `20261018_04`, readiness `ready`. Existing Players: WNBA 94,
  NFL 489, MLB 446, NHL **0**. NHL import cannot proceed without an existing
  verified Player; creating one is outside this import scope.
- No verified new-source mappings. Candidate Clark/Indiana and Mahomes/Kansas
  City rows exist, but source identities remain uncollected. Candidate Ohtani
  row lists NYY and lacks position/jersey evidence; do not certify by name.
  No Player metadata was repaired or replaced.
- Existing logs: 2,894 ESPN WNBA and 27,599 MLB StatsAPI rows. Preserve these;
  exact legacy MLB game overlaps require comparison after collection.
- Exact manifests saved under ignored `backend/data/odds_runs/phase8-collection-01/`:
  `statistics-manifest.json` SHA-256
  `308505b0adbb146e71b46750f5f14ceaa2a554f3f166032a42eea15f19969cf5`;
  `discovery-manifest.json` SHA-256
  `46a78778fd2e1a6003136afe9ed934c62af377684e45e9ab5793fc97cbc3e669`.
  These retain the exact endpoints and ceilings above. Both remain unapproved
  and unexecuted. Original bytes, UTC receipts and source digests are required
  during collection. Local preflight evidence is in the same ignored directory.
- This checkpoint: backend adapter/summary/API selection checks **31 passed,
  5 PostgreSQL-dependent checks skipped** (36 discovered), with external network
  blocked; Windows asyncio internal loopback permitted. Initial blanket socket
  blocking broke the test harness; corrected guard passed. Frontend **90 passed**;
  TypeScript passed. No disposable PostgreSQL database configured, so write tests
  were not run. No frontend source changed; production build and browser rerun
  deferred. Normal desktop/mobile real-data verification awaits approved import.
- Actual collected statistics: none. New/updated/unchanged/rejected import counts
  are **unknown**, not zero. Import status: not executed. Sportsbook availability,
  markets and subscription capability remain unverified; no discovery or spending.
- Previous checkpoint proposed the nine-request/54-MiB historical manifest;
  it is now superseded. Discovery needs
  its separate six-request/6-MiB/zero-credit approval. Development writes require
  subsequent exact artifact/mapping/player/season/row-limit approval. The current
  statistics CLI uses one atomic transaction per invocation, not independent
  per-sport commits; explicit NHL season requires a separate invocation.

## Current-season integration — October 19, 2026

Use 2026 Regular Season for WNBA/NFL/MLB and 2026-27 for NBA/NHL.
`--season current` already resolves these scopes independently; explicit seasons
remain available. No operational adapter changes were justified by offline evidence.
New tests cover current provider identifiers, historical exclusion, both NHL/MLB
roles and actual short L5/L10 samples. They are invented fixtures, not source proof.

Exact replacement: ignored
`backend/data/odds_runs/phase8-current-01/statistics-manifest.json`, SHA-256
`bac9ef76523da699df63a76407196174ff30b242fb21b3d952a54b1a56869f8d`.
**Unapproved, unexecuted: 12 logical requests, 58 MiB maximum**, 30-second
timeout per response, no retries/proxies/fallbacks, no development writes.
Nine source requests retain the 54-MiB cap; three explicit availability checks
add three requests and 4 MiB. This larger ceiling needs explicit approval.

| Sport | Exact proposed source requests | Availability gate / ceiling |
| --- | --- | --- |
| NBA | `https://cdn.nba.com/static/json/staticData/scheduleLeagueV2_1.json` | Calendar only, 1 GET / 2 MiB; verify 2026-27 and completed regular-season games through Oct 19. **No NBA player statistics requests.** Existing manual refresh's Oct 20 opening guard is retained, not independently reverified calendar evidence. |
| WNBA | `https://api.github.com/repos/sportsdataverse/sportsdataverse-data/releases/tags/wnba_stats_player_game_logs`, then `https://github.com/sportsdataverse/sportsdataverse-data/releases/download/wnba_stats_player_game_logs/player_game_logs_2026.csv` | Metadata 1 MiB + CSV 5 MiB. Download only if exact named asset/URL exists within limit; filter `season_id=22026`, final W/L rows. Asset existence/completeness and live schema remain unverified. |
| NHL | `https://api-web.nhle.com/v1/player/8478402/landing`, then `https://api-web.nhle.com/v1/player/8478402/game-log/20262027/2` | 2 MiB each. Profile must establish exact athlete/role and completed current-season regular appearances first. Actual 2026-27 coverage remains unverified; no goalie saves from skater rows. |
| NFL | `https://api.github.com/repos/nflverse/nflverse-data/releases/tags/stats_player`; `https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv`; then `https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2026.csv` | Metadata 1 MiB, schedule 5 MiB, weekly CSV 20 MiB. Exact asset must exist; schedule must establish completed 2026 REG games. Exact scored schedule joins required. Asset availability/schema remain unverified. |
| MLB | `https://statsapi.mlb.com/api/v1/people/660271`; `https://statsapi.mlb.com/api/v1/schedule?sportId=1&startDate=2026-03-01&endDate=2026-10-19&gameTypes=R`; `https://statsapi.mlb.com/api/v1/people/660271/stats?stats=gameLog&group=hitting&season=2026&gameType=R`; same final URL with `group=pitching` | 1, 15, 2, 2 MiB. Profile and final regular-season schedule precede both role logs. Actual coverage and source fields require collected responses. |

Only exact named GitHub release-asset CDN redirects are proposed (at most three
hops); other endpoints must not redirect. Metadata absence skips dependent
downloads. No alternate filename, larger asset, extra athlete or historical
substitute is authorized. Retain original bytes, UTC receipts and SHA-256 hashes.
Full-season files may retain postseason/future rows; normalize only completed
Regular Season appearances through Oct 19. Source usage restrictions above apply.

Read-only development recheck: revision `20261018_04`, readiness `ready`.
Players NBA 21 / WNBA 94 / NFL 489 / MLB 446 / NHL 0. NBA.com history remains
976 logs / 18 players. Existing new-source mapping example remains empty.
NHL ingestion creates Players only from accepted matched sportsbook rows; retained
status has zero matched props/Players and HTTP 429 frequency limiting, not proof
of tier exclusion. A profile-reviewed NHL Player may instead be created separately
using the existing Player model/default UUID, then used for player-only research.
Exact name/team/position and write scope await official profile evidence; no new
Player or UUID was created. No new identity table or service is required.

Ohtani candidate UUID `LOCAL_OHTANI_PLAYER_ID` is the only matching
name row, with NYY team, null position/jersey and sampled bare game IDs
`824645`, `824647`, `823919`. Sampled stats carry no source athlete identity.
Do not certify the local association or overwrite history. Smallest possible
correction, only after independent identity review, is an explicitly approved
team/position update to that same Player; exact legacy game overlaps still block
game-log import pending their own reviewed correction scope. Name uniqueness
alone is insufficient evidence.

This checkpoint: **33 backend tests passed, 5 PostgreSQL-dependent tests skipped**
(38 discovered), plus **8 NBA manual-refresh tests passed**, external network
blocked. Frontend **90 tests**, TypeScript and
production build passed; **14 desktop/mobile browser fixture tests passed** with
external HTTP blocked. Representative NHL desktop/MLB pitcher mobile screenshots
visually inspected. Disposable PostgreSQL writes were not tested (no configured
disposable database); no full backend rerun for test/documentation-only changes.
Real-data research, saved/slip browser operations and actual import counts remain
pending approved data. Application services were not started; only the frontend
fixture server ran and was stopped. No source collection or development mutation.

The separate discovery manifest remains byte-identical:
`46a78778fd2e1a6003136afe9ed934c62af377684e45e9ab5793fc97cbc3e669`,
six requests / 6 MiB / expected zero credits. No authorization or execution was
received in this chat. Next checkpoint requests the replacement statistics scope
and, independently, unchanged discovery. Import/Player creation/identity repair
each still need exact reviewed development-write approval after collection.

## Approved collection results — October 20, 2026

Both approved manifest hashes verified unchanged before execution. Statistics:
**12 logical requests, 14 HTTP transactions including two authorized GitHub CDN
redirects, 10,283,940 response bytes**. NBA calendar returned HTTP 403 Access
Denied (431 bytes); no retry, workaround or NBA player request. The latest human
approval explicitly permitted independent sources to continue after failure,
superseding the older batch-stop wording; all other approved responses were 200.
Original bytes, UTC receipts, statuses, hashes and sanitized redirect chains are
retained in ignored collection storage. No development writes or additional URLs.

| Sport | Actual retained data / validation | Import preview |
| --- | --- | --- |
| NBA | Calendar denied; no current-game availability verified. Existing 976 NBA.com logs preserved. | No new source batch. |
| WNBA | Published 2026 CSV exists: 4,705 rows, including 4,011 regular-season player rows for 221 source athletes. All five metric columns present. Player rows stop **July 22** while regular-season team rows extend to Sept 24: partial player coverage. Clark has 23 recorded games. | **23 new / 0 updated / 0 unchanged / 0 rejected**. No opponent-ID history without schedule evidence. |
| NHL | Official profile confirms Connor McDavid, ID `8478402`, EDM/team 22, C, #97; eight 2026-27 type-2 games through Oct 17 agree with profile totals. Skater fields compatible; no goalie saves claimed. L5 points 2.8 (5 samples), L10 2.88 (8 samples). | Blocked by zero local NHL Players. No invented local UUID or mapping. |
| NFL | Published weekly 2026 CSV exists: 6,417 REG rows, weeks 1–6. Selected rows join exact completed schedule games. Mahomes 5, Henry 6, Minnesota Jefferson 4 appearances. | **15 new / 0 updated / 0 unchanged / 0 rejected**. Missing weeks do not certify DNP. |
| MLB | Official athlete `660271`: 135 hitting + 14 pitching splits normalize into **139 unique games**, including ten combined two-way appearances. All pitching innings agree with source outs. | Entire batch blocked by **104 legacy bare-ID collisions**; 35 other games are only noncolliding candidates, not an executable import. Update/unchanged counts unavailable for this blocked batch. |

Confirmed adapter fix: MLB's postponed schedule alias can have
`abstractGameState=Final` alongside its played makeup game (observed gamePk
`823523`). Completion filtering now excludes postponed/suspended/cancelled/delayed
entries and incompatible explicit state codes before exact game matching. Two
actual completed duplicates still fail closed. No original records modified.

Reviewed ready mappings (unique sport/name plus independent local/source team
agreement and stable source IDs; full evidence in ignored `mappings.json`):

| Player | Exact local UUID | Source athlete | Rows |
| --- | --- | --- | --- |
| Caitlin Clark | `LOCAL_CLARK_PLAYER_ID` | `1642286` | 23 |
| Patrick Mahomes | `LOCAL_MAHOMES_PLAYER_ID` | `00-0033873` | 5 |
| Derrick Henry | `LOCAL_HENRY_PLAYER_ID` | `00-0032764` | 6 |
| Justin Jefferson, MIN | `LOCAL_JEFFERSON_PLAYER_ID` | `00-0036322` | 4 |

NFL contains a second Justin Jefferson source ID `00-0041075` on CLE; it was
excluded using team evidence. Name-only identity would have been ambiguous.
Ohtani's local person association was subsequently verified beyond name: all
104 overlapping official game IDs, dates and five hitting metrics match the same
local UUID `LOCAL_OHTANI_PLAYER_ID`. Official splits identify athlete
660271 on Los Angeles Dodgers/team 119; local NYY metadata remains incorrect.
Proposed metadata-only repair: team Los Angeles Dodgers, abbreviation LAD,
position TWP. No metadata repair or history reconciliation has executed.

Sportsbook discovery: **6 requests / 26,589 bytes / 0 credits charged**, all 200.
Event counts NBA **46**, WNBA **1**, NHL **12**, NFL **14**, MLB **1**; exact IDs,
participants and UTC starts validated and retained. Account headers stayed
**2 used / 498 remaining**, with `x-requests-last=0` on every response. Events
prove event access only; player markets, offers and subscription entitlement
remain unknown. No 429/subscription denial occurred in this discovery. A local
settings-working-directory failure happened before discovery HTTP and was fixed;
no request was duplicated. Do not rerun these completed manifests.

Development reverified read-only: `localhost:5432/proppulse`, revision
`20261018_04`, readiness `ready`. Existing CLI independently confirmed combined
**38 new / 0 updated / 0 unchanged / 0 rejected**, with zero writes/HTTP and an
exact matching approval scope. Source hashes, normalized rows, per-player game
IDs, expected L5/L10 and all approval artifacts remain ignored under
`backend/data/odds_runs/phase8-current-01/`.

Consolidated next-write proposal: `database-change-proposal.json`, SHA-256
`b4c4f435af35931c88fffa84e7b616332ebab9d069b75abd8ce4ee5174ca38a6`.
Separately reviewable operations: (1) 38 WNBA/NFL PlayerGameLog inserts for the
four exact mappings above, 2026 Regular Season, one atomic transaction/full
rollback; (2) one NHL Player creation for reviewed McDavid profile, UUID generated
by existing model only after approval, **no NHL log writes**; (3) Ohtani's single
Player metadata correction above, **no MLB log writes**. NHL's eight-row import
needs its real generated UUID and subsequent exact preview/approval. MLB history
needs a separate exact collision-resolution scope; no duplicate import proposed.
Recheck readiness, digests and preview before approved execution; abort on drift.
No Props/Events/offers/authentication/saved/slip changes are included.

Tests after the fix: **87 passed, 27 skipped** (114 discovered) across adapters,
field parsing, NBA summaries/manual refresh, trends, research selection and
history. External network blocked. Disposable PostgreSQL mutation tests were
not run (no configured test database). Real-artifact normalization, receipt
digest checks and read-only CLI preview passed. No frontend source changed;
frontend/build/browser checks were not repeated after the prior successful
90-test/TypeScript/build/14-fixture-browser checkpoint. Operational real-data
browser verification remains pending approved imports. Code remains uncommitted;
no deployment or push.

## Approved development writes — October 20, 2026

Executed only the three explicitly approved operations from proposal SHA-256
`b4c4f435af35931c88fffa84e7b616332ebab9d069b75abd8ce4ee5174ca38a6`.
Proposal/source/mapping/artifact/record hashes, exact local identities, revision
`20261018_04`, readiness `ready` and the 38-new read-only preview matched before
execution. Each operation used its own transaction, with rollback on failed
checks and before/after content fingerprints for every existing table.

| Approved operation | Actual change | Counts / preservation |
| --- | --- | --- |
| WNBA/NFL logs | Clark 23, Mahomes 5, Henry 6, MIN Jefferson 4; exact reviewed UUIDs above, 2026 Regular Season | **38 inserted, 0 updated/deleted/rejected**, one atomic transaction. Total logs 31,841 → 31,879; Players unchanged at 1,050. Every prior log unchanged. |
| NHL Player | Connor McDavid, Edmonton Oilers / EDM / C / #97 | Exactly one generated UUID: `LOCAL_MCDAVID_PLAYER_ID`. Players 1,050 → 1,051; no equivalent Player immediately before insertion. **Zero NHL log writes.** |
| MLB metadata | UUID `LOCAL_OHTANI_PLAYER_ID`: team Los Angeles Dodgers, abbreviation LAD, position TWP | Exactly those three fields changed; UUID, all other Player fields and all **104 existing Ohtani logs** preserved. **Zero MLB log writes.** |

All unrelated rows/tables, including Events/Props/offers/users/saved/slips, matched
their pre-operation fingerprints. Final verification after API/browser checks
matched the final committed snapshot: 1,051 Players / 31,879 logs. No provider
HTTP, sportsbook spending, migration, commit, push or deployment. A console JSON
datetime-formatting error occurred after the NHL commit was saved; saved results
were verified and only the unexecuted MLB operation resumed. No write repeated.

Production research router verified through an isolated FastAPI app with
PostgreSQL-enforced READ ONLY dependencies; no real application startup or
refresh worker. All four imported summaries matched the approved source-derived
L5/L10 values and denominators exactly. API examples:

| Player / metric | L5 average (samples) | L10 average (samples) |
| --- | --- | --- |
| Clark points | 22.8 (5) | 21.8 (10) |
| Mahomes passing yards | 261.8 (5) | 261.8 (5) |
| Henry rushing yards | 78.0 (5) | 89.0 (6) |
| Jefferson receiving yards | 64.5 (4) | 64.5 (4) |

Previous-season/postseason summaries remained separate and empty for these new
sources. Recorded NFL opponent history matched source-derived expectations;
WNBA opponent IDs remain unavailable. Repeated import preview:
**0 new / 0 updated / 38 unchanged / 0 rejected**. NBA checked historical summary
still has 20 recorded games, current 2026-27 summary unavailable with zero games.
NHL/MLB new-source summaries correctly remain unavailable before their imports;
both Player detail endpoints show approved team metadata.

Four real-data browser checks passed: Clark desktop (including season switching
and reload), Henry mobile, McDavid desktop and Ohtani mobile. The normal frontend
used a temporary read-only local research API; external HTTP and mutation methods
were blocked. Clark/Henry screenshots visually inspected; no horizontal overflow
or page errors. Both temporary servers stopped. Saved/slip mutation interactions
were not exercised. WNBA coverage remains partial through July 22; no claim that
its current-season dataset contains the latest completed player appearances.

Focused regression checkpoint: **56 passed / 27 PostgreSQL-dependent skipped**
(83 discovered). No full-suite rerun or frontend rebuild (no application/frontend
source changes in this write execution). Disposable mutation tests remain skipped
without a configured test DB; authorized development writes were verified directly
with transaction guards, actual records, idempotency and read-only API checks.

Next narrow approval is prepared, **not executed**:
`backend/data/odds_runs/phase8-current-01/nhl-eight-game-proposed-approval.json`,
SHA-256 `95046a8eaf6726d243cf28bde3afcd395caedb339d64d2dc8f47040e74f5a53a`.
Exactly eight `PlayerGameLog` inserts, only generated McDavid UUID above, source
athlete 8478402, 2026-27 Regular Season, `localhost:5432/proppulse`, one atomic
transaction, no updates/deletes/Player changes/HTTP. Existing CLI read-only preview
reports **8 new / 0 updated / 0 unchanged / 0 rejected**; exact mapping, source,
artifact and record hashes are retained with the proposal.

Separate read-only MLB review:
`backend/data/odds_runs/phase8-current-01/mlb-collision-resolution-readonly-review.json`,
SHA-256 `fcd6e50cc0282e40d46551a6230dadcb27f4e16cb73c850669e3b7542868a3c2`.
Lists 104 exact existing row UUIDs with proposed field differences and 35 exact
noncolliding candidates. All five existing hitting metrics match. No reconciliation
executed: current importer still rejects legacy overlaps. Any later repair must
explicitly review provider qualification, research/role metadata, opponent IDs and
calendar-anchor UTC timestamp changes while preserving row UUIDs and existing
metrics; this review is not an executable write approval.

## McDavid eight-game import — October 20, 2026

Executed approved file SHA-256
`95046a8eaf6726d243cf28bde3afcd395caedb339d64d2dc8f47040e74f5a53a`
after exact approval/source/mapping/normalized-record hash checks and a read-only
8-new preview. Database `localhost:5432/proppulse`, revision `20261018_04`, ready.
Only Player `LOCAL_MCDAVID_PLAYER_ID` / athlete `8478402`,
2026-27 Regular Season, eight unique completed games from Sept 29–Oct 17.

**Committed atomically: 8 inserts, 0 updates, 0 deletes, 0 rejected.** Total logs
31,879 → 31,887; Players unchanged at 1,051. Full-table before/after fingerprints
and the original-log fingerprint excluding the eight generated IDs confirmed
all prior NBA/WNBA/NFL/MLB logs, Players, Props, Events, offers, user/saved/slip
data unchanged. Final snapshot also matched after all read-only verification.
Existing CLI post-import preview: **0 new / 0 updated / 8 unchanged / 0 rejected**.

Actual research API is available with source NHL Web API and correct recorded
opponent history. Independently checked averages:

| Metric | L5 (5 valid samples) | L10 (8 valid samples) |
| --- | --- | --- |
| Points | 2.80 | 2.88 |
| Goals | 0.80 | 0.75 |
| Assists | 2.00 | 2.12 |
| Shots on goal | 2.20 | 2.25 |
| Time on ice, minutes | 23.19 | 23.39 |

Previous-season and postseason summaries stay separate and empty. Two actual
desktop/mobile browser checks passed, including all five metric cards, 5/8 sample
counts, season switching and reload persistence; screenshots visually inspected.
The normal frontend used a temporary PostgreSQL READ ONLY API with external HTTP
and mutations blocked. Both temporary servers stopped. No sportsbook-backed Props
exist for this player; player-only research works without inventing offers.

Focused backend tests: **31 passed, 4 disposable-PostgreSQL checks skipped**
(35 discovered). No full suite/frontend rebuild (no application source changes).
Receipts and verification artifacts are ignored under `phase8-current-01/`.
No provider HTTP, credits, additional Players or MLB writes. MLB remains blocked
by the separately reviewed 104 legacy collisions / 35 noncolliding candidates;
no reconciliation/import is authorized. Code and protected reports preserved;
no commit, push or deployment.

## Retained-data coverage expansion — October 20, 2026

Read-only preparation only: revision `20261018_04`, readiness `ready`, **31,887
logs / 1,051 Players**. Final fingerprints match the prior authorized checkpoint
for every table. NBA.com history remains **976 logs / 18 players**; no NBA request
or mutation. No application code/frontend changes or new infrastructure.

MLB's 139 official Ohtani games classify as **94 already accurately represented**,
**10 existing two-way rows missing pitching metrics**, **35 genuinely missing
appearances**, **0 ambiguous conflicts**. All 104 existing rows match official
game IDs, calendar dates and all five hitting metrics for the reviewed UUID and
athlete 660271. The smallest safe proposal is **35 missing-game inserts only**
(31 batting, four pitching), leaving all 104 original row UUIDs, game IDs, dates,
opponents and statistics untouched. No ID migration or historical rewrite is
needed. Ten additive pitching enrichments remain deferred, not authorized.
This resolves duplicate insertion risk while retaining honest partial coverage:
the 104 legacy rows still lack reviewed season metadata; the 35-row new-source
summary would be partial and has **zero valid pitching samples in its latest
5/10 appearances**, not invented zero averages or complete pitching coverage.

Reviewed **28 additional existing Players** from retained 2026 files: **12 WNBA**
and **16 NFL** (four each QB/RB/WR/TE). Selection prioritizes existing provider-event
Props, then corroborated role and deeper recorded samples. Every mapping includes
exact local UUID, stable source athlete ID, unique local name within sport,
independent matching team evidence and role checks where local role exists.
All selected Players have existing provider-event Props; none has a canonical
Event link, so this is not verified live betting coverage. Excluded unresolved
Prop-linked candidates: **7 WNBA / 130 NFL**; none was manufactured into a mapping.
Other screened candidates remain outside this bounded approval.

| Independent proposed operation | New | Updated | Unchanged | Rejected |
| --- | --- | --- | --- | --- |
| WNBA, 12 additional Players | 306 | 0 | 0 | 0 |
| NFL, 16 additional Players | 89 | 0 | 0 | 0 |
| Combined WNBA/NFL atomic import | **395** | **0** | **0** | **0** |
| MLB, missing games only | **35** | **0** | **0** | **0** |

These are actual PostgreSQL-enforced READ ONLY previews through the existing CLI;
approval scopes matched exactly. The 104 excluded MLB legacy rows are preserved,
not counted as new or importer-unchanged rows in the 35-row batch. Selected WNBA
summaries have 5/10 samples; selected NFL summaries have **3–5 L5 / 3–6 L10**
samples. The pending proposals do not establish imported coverage.

Actual usable current-season summaries remain **WNBA 1 / NFL 3 / NHL 1 / MLB 0 /
NBA 0**. All current sport metrics and valid denominators were checked against
stored records. Existing NBA historical coverage remains available. WNBA source
player data still stops July 22; NFL source spans weeks 1–6; missing appearances
do not establish DNP. No new source availability or sportsbook entitlement claims.

NHL next candidates are supported by names/IDs in McDavid's retained official
`currentTeamRoster`: **Leon Draisaitl 8477934**, **Evan Bouchard 8480803**,
**Tristan Jarry 8477465**. Proposed collection is exactly each athlete's
`https://api-web.nhle.com/v1/player/{id}/landing`, then
`https://api-web.nhle.com/v1/player/{id}/game-log/20262027/2` only after profile
verification: **6 GETs / 12 MiB maximum**, 2 MiB each, 30-second timeout, no retries,
redirects, fallback or DB writes. Roles/jerseys must come from those profiles;
no Player creation is ready for approval yet and no local UUID was invented.

One consolidated independently reviewable proposal, ignored under
`backend/data/odds_runs/phase8-expansion-01/consolidated-proposal.json`, SHA-256:
`19fe71e8e654558c784668691a5dcc0dfa9aef2e02d0770ced00f6094788b499`.
It includes exact UUIDs, athlete IDs, game IDs, source/mapping/artifact/record
digests, seasons, row ceilings and independent atomic rollback boundaries.

- WNBA/NFL approval: `wnba-nfl-proposed-approval.json`, SHA-256
  `ae92185017b847e044ee4e960e0cb664da00c5a250813ba809cc97374391b784`.
- MLB missing-only approval: `mlb-missing-proposed-approval.json`, SHA-256
  `4ea9ee0478b2622b05978f47afb7869c22442e7522d160bfcd482afbc2515f3a`.
- NHL collection manifest: `nhl-collection-proposed-manifest.json`, SHA-256
  `4e12bf9a7938a35e7f5cc07f90219da06266d60b728b01e612185ab2adf5494e`.

No proposal executed. Both import operations allow PlayerGameLog inserts only,
zero updates/deletes, 2026 Regular Season, exact `localhost:5432/proppulse` target;
abort on input/identity/preview drift. Collection approval grants no Player or
game-log write authority. Classifications, exclusions, per-player expected L5/L10
and exact selected-game transformations are retained privately beside the scopes.

Focused tests **31 passed / 4 disposable-PostgreSQL skipped** (35 discovered),
external network blocked. Original artifact hashes and both CLI previews passed.
No mutation tests, full-suite/browser/build reruns: no writes or application source
changes. Existing uncommitted work and protected reports preserved; no commit,
push or deployment.

## Real data operational execution — October 20, 2026

This operational checkpoint supersedes the earlier unexecuted-expansion status.
Read-only PostgreSQL inspection confirmed revision `20261018_04`, 31,887 logs,
and no prior execution of the 430-row expansion. The proposal hash matched.
After explicit chat approvals, imported 430 proposed records, then all remaining
reliably mapped existing WNBA/NFL players (3,202 records), and three officially
verified NHL Players with 19 records. Each import used an independent atomic
transaction, exact identities/hashes/counts, zero updates/deletes, and protection
of unrelated tables. Final total: **35,538 logs**, **3,651 added**; zero duplicate
player/game identities or sport mismatches. All 104 legacy Ohtani rows remain.

| Sport | Verified current-season research Players | Statistics through | Actionable book offers / props at verification |
| --- | ---: | --- | ---: |
| NBA | 0 | Historical NBA.com coverage retained | 40 / 8 |
| WNBA | 87 | July 22, 2026 | 83 / 33 |
| NFL | 352 | October 18, 2026; partial weeks 1–6 | 96 / 18 |
| NHL | 4 | October 17, 2026 | 11 / 4 |
| MLB | 1 | September 27, 2026; missing-games-only summary | 79 / 26 |

Last completed statistical import: **October 20, 2:30:49 PM EDT**. Research counts
refer to reviewed season summaries; preserved legacy MLB history covers 372
Players and is not silently certified as complete reviewed season coverage.
NBA.com historical coverage remains 976 records / 18 Players. No new NBA
statistics requests were authorized. Further provider batches require approval.

The approved current-odds trial used **20 credits / 11 GETs**, leaving **478**
provider credits and preserving the **50-credit reserve**. Six separately approved
official NHL GETs succeeded (68,690 bytes); no historical paid odds requested.
The 48-hour discovery filter initially hid the approved NFL/MLB events; fixed
explicit event selection and completed only the two unexecuted approved calls.
Also added explicitly approved market probes without asserting entitlement,
blocked paid calls when remaining quota is unknown, and fixed reviewed NHL
September appearances being assigned to the wrong exact-line history season.

One actual local browser walkthrough confirmed Board sport filters for all five
leagues; real Discover offers; NHL and WNBA L5/L10 with coverage dates; no-offer
A'ja Wilson research; and Saved/slip persistence across reload. The authorized
disposable account retains one saved prop, one draft slip and one selection:
McDavid, FanDuel Under 2.5 shots, +130, distinct from the default 3.5 line.
Missing odds were visibly labeled. Natural expiry transitions were not awaited
or simulated; no real odds were falsified to exercise stale states.

Verification: 28 focused statistics/odds tests passed, four disposable-PostgreSQL
tests skipped; seven trend tests passed; independent real L5/L10 spot checks
passed for Wilson, Williams, McDavid and Ohtani. No full suites, frontend build
or repeated browser suite. Existing source work remains uncommitted; no push or
deployment. Ignored execution receipts and screenshots are under
`backend/data/odds_runs/phase8-expansion-01` and `real-data-remaining`.

Final commit checkpoint: 96 relevant backend tests passed, with 27
PostgreSQL-dependent tests skipped; 90 frontend unit tests passed. TypeScript
(`npx tsc --noEmit`), production build and diff whitespace checks passed.
Backend verification blocked provider HTTP and all non-SQLite connections;
offline CLI dry runs reported zero provider requests and database writes, and
the seven invented browser fixtures matched their adapter generator. No live
ingestion, provider spending or development PostgreSQL writes were performed.
Protected audit/collection reports and private execution artifacts are excluded
from the local Phase 8 commit.
