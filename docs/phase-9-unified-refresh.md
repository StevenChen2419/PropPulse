# Phase 9: unified refresh

Run from `backend`, using the existing virtual environment. CLI only: there is
no established operator-only web capability. No schema or application startup
is needed. Previews use local files only, never HTTP or a database connection.

```powershell
.\venv\Scripts\python.exe scripts/refresh_all_sports.py --sports all --include statistics odds --dry-run
.\venv\Scripts\python.exe scripts/refresh_all_sports.py --sports nba nhl nfl --include statistics --dry-run
.\venv\Scripts\python.exe scripts/refresh_all_sports.py --sports all --include odds --dry-run
```

Without exact inputs these commands report missing/unknown coverage and perform
zero requests, spend zero credits, and write no database rows. JSON plans and
summaries are stored under the existing ignored `backend/data/odds_runs/` tree.
Default mode is always dry-run. Scope paths are relative to the working directory.

## Supported statistics paths

| Sport | Collection | Offline import |
| --- | --- | --- |
| NBA | Existing bounded NBA.com `PlayerGameLog` collector; verified UUID mappings, completed Eastern dates, 2025–26/2026–27 regular seasons. No access-restriction bypass. | Existing offline batch validation and transactional NBA importer. |
| NHL | Reusable version of the Phase 8 bounded NHL Web API collector: profile then exact season game-log request per reviewed athlete; source position verifies skater/goalie role. | Existing sport normalizer/importer. |
| WNBA | Automatic collection unsupported here; obtain published wehoop CSV and schedule descriptor through a separately approved download. | Existing published dataset loader; actual selected-player coverage dates are reported, never assumed full-season. |
| NFL | Automatic collection unsupported here; obtain current nflverse weekly player statistics and completed schedules separately. | Existing weekly source-athlete/week/game join validation. |
| MLB | Automatic collection unsupported here; the broad live history command has no suitable exact-scope approval interface. Obtain StatsAPI artifacts separately. | Existing StatsAPI gameLog/final-schedule pipeline; legacy collisions stop imports, preserving existing games. |

These limitations reflect the current reusable command paths. Retained one-shot
Phase 8 download manifests are historical approvals, not reusable authorization.
See [Phase 8](phase-8-multi-sport.md) for existing artifact/mapping formats.

An exact statistics scope file contains selected sports and their inputs:

```json
{
  "statistics": {
    "wnba": {
      "action": "artifact",
      "season": "2026",
      "mapping": "data/odds_runs/my-inputs/wnba-mappings.json",
      "artifacts": ["data/odds_runs/my-inputs/wnba-artifact.json"],
      "max_rows": 10000
    },
    "nhl": {
      "action": "collect",
      "season": "2026-27",
      "mapping": "data/odds_runs/my-inputs/nhl-reviewed-mappings.json",
      "output": "data/odds_runs/my-collection/nhl-artifact.json",
      "max_rows": 10000
    }
  }
}
```

`players` optionally selects exact existing UUIDs; otherwise the mapping defines
the selection. `competition` defaults to `Regular Season`. NBA scopes also
require `date_from` and `date_to`; artifact mode takes exactly one artifact.
Collection mode produces a fresh artifact without importing it. Re-preview its
bytes with `action: artifact` and obtain separate import approval afterward.
As of October 20, 2026, no prior completed 2026–27 NBA regular-season dates exist.

## Preview, approval, execution

```powershell
.\venv\Scripts\python.exe scripts/refresh_all_sports.py --sports wnba nhl --include statistics odds --scope data/odds_runs/my-inputs/scope.json --coverage data/odds_runs/my-inputs/odds-coverage.json --database-target localhost:5432/proppulse --max-requests 10 --max-credits 8 --quota-reserve 50 --output-dir data/odds_runs/my-refresh --dry-run
```

Review `plan.json`: exact source identities, artifact and mapping hashes, child
import scopes, NBA date range, NHL paths, odds Events/markets, evidence, retained
quota, request ceiling and credit upper bound. Obtain explicit human approval
for its displayed `plan_sha256`, including provider collection, sportsbook
spending and database writes as applicable. Dry-run is not authorization.

Then repeat **the same arguments, including output directory**, replacing
`--dry-run` with `--execute-approved <approved-plan_sha256>`. Input changes,
scope changes and output-directory changes invalidate approval. The coordinator
passes only the exact approved child scopes to existing importers. It does not
collect then approve unseen artifacts. A run has one exclusive execution claim;
after interruption or failure, inspect the summary and make a new preview in a
fresh directory before seeking another approval. There is no automatic retry.

Imports require the exact configured loopback development PostgreSQL target,
live refresh disabled, and no libpq routing overrides. Each statistics sport
uses its existing transaction; independent failures do not prevent other
approved operations. Odds retains the advisory lock and per-sport transactions.
Player creation and identity repairs are prohibited; a necessary player change
rolls back that sport instead of silently expanding the approved writes.

## Sportsbook quota and coverage

Use the existing `refresh_sports_odds.py` coverage format: provider sport keys,
exact retained Events, markets, access state, evidence and optional retained
roster directory. Add a credential-free quota receipt reference:

```json
"quota": {
  "remaining": 100,
  "observed_at": "<actual UTC receipt timestamp>",
  "evidence": "<retained provider quota receipt path/hash>"
}
```

This is an example shape, not current quota confirmation. Missing, future, or
older-than-six-hour quota evidence blocks execution. Retained quota must fund
the exact credit upper bound plus reserve (minimum 50; a higher configured
provider reserve must also be included). Execution confirms live headers using
only the approved requests. Unknown live quota stops further requests, including
paid requests. Missing cost headers report actual consumed credits as `unknown`;
the budget still accounts conservatively. No exploratory discovery is added.

Request ceilings cover statistics plus all odds requests across every selected
sport, including `all`. Odds credit upper bounds are events × markets in one US
region, with retries disabled. The preview lists `/sports`, event verification,
and each approved event-odds request. Unknown/unsupported/no-games access states
are explicit; bounded `probe` access requires its own retained discovery
evidence and explicit approval of those exact requests. Existing event/player
matching, equivalent lines, offer freshness and snapshot protections are reused.

## Results

Example dry-run excerpt with no supplied artifacts/evidence:

```json
{
  "mode": "dry-run",
  "actual_api_requests": 0,
  "database_writes": 0,
  "credits_consumed": 0,
  "confirmed_credits_remaining": "unknown"
}
```

`plan.statistics` reports each sport/source/season and its ready, skipped,
unsupported or failed status. `provider_request_upper_bound`,
`sportsbook_credit_upper_bound`, `odds_execution_blocker` and `plan_sha256`
describe approval requirements. Execution summaries include observation date,
latest represented completed game, represented players, new/updated/unchanged/
rejected log counts when established, processed Events, saved offers, failures,
actual aggregate requests, consumed credits and confirmed remaining quota.
Unavailable counts, player-update counts not exposed by an importer, and
complete-season coverage are `unknown`. A selected-player coverage date is not
a claim about the latest completed league game. Shared odds discovery calls are
counted at run level; per-sport market request counts are reported separately.
Exit status 1 indicates a rejected/failed or partial execution. A preview with
missing inputs is still a valid offline preview.

Verification uses invented fixtures, mocked transports, and isolated SQLite.
No live provider calls, sportsbook spending or development imports were run.
Real execution still needs reviewed mappings/artifacts, fresh event/market and
quota evidence, configured credentials, the approved target, and human approval.

## Feature 2: current NBA readiness

The NBA collector and unified coordinator share opening-day handling:
`2026-27` regular-season plans return `no_games_yet` with zero requests until
prior completed Eastern dates are available. This is a successful empty preview,
not a sport failure. It does not certify the source schedule or game completion.
The current date-only policy intentionally waits until the next Eastern day.
Re-preview then; the newly executable plan has a different digest and needs
explicit approval. Imports remain a separate artifact review and approval.

Read-only development inventory on October 20, 2026 confirmed revision
`20261018_04`, 20 verified NBA mappings, one unresolved mapping (Jalen Brunson),
and 976 NBA.com logs, all in 2025–26. No 2026–27 coverage was established.
The reviewed mapping file is unchanged. Retained provider-linked Props/Events
prioritize these two existing identities for the first bounded collection:

| Player | Local UUID | NBA athlete ID |
| --- | --- | --- |
| Cade Cunningham | LOCAL_CUNNINGHAM_PLAYER_ID | 1630595 |
| Jayson Tatum | LOCAL_TATUM_PLAYER_ID | 1628369 |

The ignored local proposal is `data/odds_runs/phase9-nba-readiness/current-nba-scope.json`.
From `backend`, preview it with:

```powershell
.\venv\Scripts\python.exe scripts/refresh_all_sports.py --sports nba --include statistics --scope data/odds_runs/phase9-nba-readiness/current-nba-scope.json --database-target localhost:5432/proppulse --max-requests 2 --max-credits 0 --output-dir data/odds_runs/phase9-nba-readiness/preview --dry-run
```

It selects `GET https://stats.nba.com/stats/playergamelog`, `Season=2026-27`,
`SeasonType=Regular Season`, `LeagueID=00`, `DateFrom=10/20/2026`,
`DateTo=10/20/2026`, and each reviewed `PlayerID` above. Opening day currently
has zero executable requests; after the date becomes eligible the upper bound
is two requests. Limits are 512,000 decoded response bytes per request and
4,000,000 for the batch, ten-second timeouts, no retries, redirects or proxies.
The output is `data/odds_runs/phase9-nba-readiness/nba-2026-27-2026-10-20.json`.
Collection writes no database rows; a subsequent import is bounded to 1,000 rows
for those existing UUIDs, season and date, preserving historical games.

Imported PlayerGameLog rows require an explicit final W/L result as well as the
correct regular-season game ID, source season, reviewed athlete and prior date.
Empty source results remain empty. New 3PM season-summary metrics reuse the
existing dynamic UI; missing 3PM stays unavailable, with independent L5/L10
denominators. Current/historical selection and separate legacy chart scope are
unchanged. Existing invented fixtures now explicitly include final W/L results.

The retained October 20 NBA CDN schedule request returned HTTP 403. This is not
evidence of the Stats PlayerGameLog endpoint's current availability. Historical
Stats imports succeeded; 2026–27 provider compatibility remains unverified live.
The collector records HTTP access denial accurately, retains the artifact, and
never bypasses access controls or switches providers. No provider requests,
credits, or development data writes were used for this implementation.

## Feature 3: freshness and coverage indicators

Sportsbook prices show their provider observation age independently of statistics.
The existing 30-minute live / six-hour last-known policy and game-start cutoff
remain authoritative. Missing observation times disable prices; ingestion time
and page reload never renew a price. Saved and slip selections remain intact,
while expired or unavailable prices cannot contribute to slip estimates.

Shared, additive `statistics_coverage` metadata accompanies prop and player
directory responses; season summaries expose the same contract as `coverage`.
It reports selected season/competition, source, latest represented game,
source observation when known, recorded appearances and actual L5/L10 samples.
Recorded NFL weeks come from imported records. Metric denominators remain
independent; missing values are never counted as zero.

States are current season with recorded games, partial current-season sample
(fewer than ten appearances or missing metric samples), historical season,
no recorded games, or unavailable source. **Completeness is always unknown**:
ten samples or a recent represented game cannot certify a complete season.
These classifications use existing filtered records and season rules, not
hardcoded coverage dates or ingestion timestamps.

Discover, Game Detail and Saved share the card indicators. Player Research,
Players and Research Slip show the same restrained status, with expandable
coverage details. Historical selections are explicit; a valid empty current
season is preserved. Statistical limitations never invalidate available odds.

Refresh summaries remain local operator artifacts. Successful completion is
not proof of current league coverage; no user API depends on local run files.
No new tables, provider calls or development database writes were needed.

Offline verification: 215 focused backend tests (69 optional PostgreSQL cases
skipped), 95 frontend tests, TypeScript and production build passed. Mocked
browser checks cover all six surfaces at 390px and 1440px, including retained
Under selections and unavailable estimates after price expiry. Live provider
coverage and development PostgreSQL transactions were not exercised.

## Feature 4: Discover search and filters

Discover now browses all eligible stored sportsbook props, including players
without research history. Search/filtering/counts/sorting/pagination run in SQL
before page serialization. No ingestion, schema, authentication or Board changes
are required. Existing `/props/discover` callers without new parameters retain
the historical research-ranking behavior; the updated UI uses `browse=true`.

Shareable UI example:
`/discover?sport=NHL&market=shots_on_goal&sportsbook=FanDuel&search=mcdavid`.
Search debounces for 350ms. Filter/sort changes reset to page 1; refresh and
browser back/forward restore the URL view. Reset Filters returns to `/discover`.

The existing endpoint accepts these browse parameters:

| Parameter | Behavior |
| --- | --- |
| `browse=true` | Browse eligible inventory without requiring ranked history |
| `search` | Up to 120 characters; case-insensitive AND tokens across player, team/abbreviation, sport, market and matchup; common punctuation normalized |
| `sport`, `prop_type` | Canonical sport (e.g. `NHL`) and market (e.g. `shots_on_goal`); UI URL uses `market` |
| `sportsbook` | Supported stored bookmaker title, case-insensitive; eligible exact-line offer required |
| `game_date` | `YYYY-MM-DD`, Eastern calendar day, using authoritative Event time when linked |
| `event_id`, `game_key` | Existing exact Event UUID or unambiguous legacy game scope |
| `availability` | `available` (through 30m), `last_known` (over 30m through 6h), or both when omitted |
| `sort` | `upcoming` (default), `player` A–Z, `market` then ascending line, `over_desc`, `over_asc`, `under_desc`, `under_asc` |
| `limit`, `offset` | 1–50 rows (default 20), offset 0–1,000,000; UI uses 24 rows and one-based `page` |

New filters or `sort` also opt into browse mode. Responses add `limit`, `offset`,
`has_more`, `next_offset` and `filter_options`. Totals are matching Prop counts,
not joined offer counts. Facets reflect actual eligible inventory scoped by sport;
empty results remain valid. Invalid enum/oversized API filters return 400/422.
Malformed UI sport/sort/date/page values fall back to defaults.

Every sort ends with Prop UUID for deterministic ordering under stable data.
Price sorts use the best valid matching Over/Under price on the listed line;
missing sides sort last in both directions. Cards keep their selected sportsbook
and saved/slip identities, so its displayed price can differ from the sorted
best matching offer. Different lines are never equivalent prices. Hit-rate
sorting remains unavailable: existing exact-line calculations run only for the
bounded page, not for an expensive inventory-wide ranking.

Expired, unknown-observation, synthetic, unsupported-book and started-game offers
cannot qualify a result. Neither filters nor reload renew observations. Coverage
indicators remain visible and partial statistics do not invalidate eligible odds.
Offset pages can move when live inventory changes; no snapshot/cursor service was
added. Search uses parameterized substring predicates and existing indexes, with
no new index/migration; broad scans may cost more as inventory grows. The game
picker retains its existing 100-game limit; text/date filters search all matching
inventory. Refreshing Discover reads stored data and makes no provider calls.

Verification uses invented fixtures, SQLite and disposable PostgreSQL isolated
from development data, plus mocked desktop/mobile browser requests. All 20 new
SQL browse checks and 99 frontend tests passed, along with TypeScript and the
production build. The 197-test backend checkpoint passed 196 checks; its old
pre-Feature-3 response oracle was updated to recognize additive coverage and
the remaining check passed on retest. Four browser checks passed, covering combined
filters, full-page search contract, stable paging, debounce, URL reload/back/
forward, empty/reset views, UUID research links and retained saved Under picks.

## Feature 5: verified multi-sport exact-line research

The existing player research response adds `exact_line`, separate from the
unchanged legacy history fields. It reuses reviewed NBA.com season scope and
the shared published/API dataset appearance filters for other sports. No new
tables, provider requests, imports or stored user-selection changes are needed.

| Sport | Canonical market → verified metrics |
| --- | --- |
| NBA / WNBA | `points`, `rebounds`, `assists`, `threes`; `pra` = all three same-game points/rebounds/assists values |
| NHL | `shots_on_goal`, `goals`, `assists`, `points` for skaters; `saves` for goalies |
| NFL | `pass_yds`, `rush_yds`, `reception_yds`, `receptions`, `pass_tds`, `rush_tds`, `receiving_tds`; `rush_reception_yds` requires both inputs |
| MLB | `hits`, `total_bases`, `runs`, `rbis`, `home_runs` for batters; `strikeouts`, `outs_recorded` for pitchers (reviewed two-way games may support both) |

This is calculation support, not a claim that every sportsbook currently offers
these markets. Unknown keys (including unsupported touchdown/blocked-shot/other
markets) remain unavailable; normalized source metrics are never inferred from
market labels. Combinations require every component, with no missing-as-zero rule.

L5/L10 take the newest eligible role-appropriate **appearances**, then report valid
and missing samples independently. Season counts include all eligible recorded
appearances in the selected season and competition. Comparisons use exact decimal
values without rounding: greater = Over, less = Under, equal = Push. Hits, losses
and pushes are separate. The raw rate divides selected-side hits by valid outcomes
(including pushes); the explicitly labeled settled rate excludes pushes. Empty
denominators are unavailable. Neither rate is a future probability or confidence
score. Prior-day completion policy and source-observation cutoffs are preserved;
same-day appearances are conservatively withheld. Source completeness stays unknown.

Research URLs retain `prop_id` and may add `sportsbook`, `offer_line`, `side`,
`season` and `competition`. The API requires both sportsbook/offer_line with an
exact Prop UUID and accepts only an actual stored offer, retained primary line or
matching snapshot. Arbitrary client lines are rejected. Expired offers and moved
snapshot lines remain descriptive research; existing availability policy controls
prices. Discover/card and slip links preserve the chosen book/line/direction.
Research controls never modify saved or slip selections.

The existing chart adds a horizontal selected-line reference, explicit Over/Under/
Push colors and missing-value gaps, with accessible recorded values beside it.
The primary Prop and legacy chart retain independent labels. New exact research
uses reviewed source/competition metadata; unseparated ESPN history is confined
to the legacy view. Current NBA opponent selection reuses established reviewed
Event/team linkage. Other opponent groups use recorded provider-qualified source
IDs, manually selectable when present; no current opponent is inferred from
free-text names. Unknown linkage stays unavailable. Opponent samples use the
same requested metric, line, season and competition as overall research.

Verification: 146 targeted backend checks passed, 30 optional cases skipped;
103 frontend tests, TypeScript, production build and six desktop/mobile browser
checks passed using invented fixtures. Tests cover strict outcomes, short/missing
samples, combinations, all mapped sport/role paths, isolation/lookahead, identity,
stored/snapshot line context and stale pricing. Disposable PostgreSQL checks were
not available because Docker's daemon was stopped; development data was untouched.

Commit checkpoint (October 21, 2026): the existing development PostgreSQL
container started successfully. Eight research API GETs passed against retained
NBA 2025–26, WNBA 2026, NHL 2026–27 and NFL 2026 props, including both directions,
exact outcomes, denominators and expired/started-price safeguards. PostgreSQL
enforced read-only repeatable-read transactions; only SELECT/SHOW statements were
allowed, with no flushes, provider requests or data writes. Revision remained
`20261018_04`. MLB was skipped: the bounded ten-Prop sample had no reviewed-statistics
linkage; this does not establish absent MLB coverage across the full database.

## Feature 6: sportsbook line comparison

The shared offer service adds `comparison` to serialized Props and
`exact_line.comparison` to research. Groups belong to the exact local Prop,
Player, Event and normalized market, with a separate group per numeric line and
Over/Under direction. No cross-Prop identity inference is used. Bookmaker keys,
titles, nullable prices and provider observation times are preserved.

Only **Available** offers (observed within 30 minutes, before game start) compete
for best price or enter slip estimates. **Last known** remains visible for research
through six hours but is now non-actionable; this supersedes the earlier policy
that allowed last-known selections. Re-ingestion never renews observation time.
Expired, started, missing and unsupported prices cannot win. Exact lines use
numeric equality, including selection validation; nearby lines are not substituted.
American odds are compared by decimal payout: +120 beats +105, -105 beats -120,
and +100 equals -100. Ties use stable existing sportsbook priority then name.
Optional price advantage is additional profit per $100 stake versus the next live
price on that same line and direction; it is not a probability or predicted edge.

Discover and Game Detail reuse the compact card comparison; Player Research uses
the same component and server grouping. Alternative lines are labeled separately.
Choosing a row preserves its exact book/line/direction in research links and
reloads exact-line statistics in Research. Old-line hit rates are never carried
over. Client time withdraws stale best labels and prices without promoting a
replacement. Removed offers retain their chosen identity with unavailable prices.
Comparing or changing research does not mutate a slip. Saved Props remains an
existing Prop-level bookmark; the UI now explains that exact sportsbook/line/side
persistence belongs to the research slip. Cross-device saved-offer selections
would require extending the existing bookmark storage and are not implemented.

**Movement limitation:** existing `PropBookSnapshot.captured_at` values were
written from ingestion time (including migrated baselines), not provider
observation time. They establish retained line context, but cannot establish
opening/closing prices or trustworthy sportsbook movement timestamps. Research
therefore reports movement unavailable, and the legacy nullable `line_movement`
research object returns null. The card no longer advertises an unverified
`line_24h_ago` delta. Price movement at the same line and changes to a different
line are not inferred from these snapshots. Historical provider observations
would need explicit storage before an observed movement display can be enabled;
no schema change, migration or provider collection is included here.

Verification: focused backend checks cover grouping, American ordering, exact
identity, source times, retention boundaries, snapshot limitations, API contracts
and slip preservation. Frontend checks cover comparison states, alternative
research context, stale/removed selections and estimates. TypeScript, production
build and desktop/mobile browser checks use invented, intercepted fixtures.
Final checkpoint: 111 backend tests passed, 35 optional PostgreSQL cases skipped;
108 frontend tests, TypeScript, production build and four browser checks passed.
No provider requests or development database writes were made.
Optional PostgreSQL integration cases require an explicit
disposable test URL; SQLite API integration and mocked sessions are used otherwise.

## Feature 7: current research coverage preparation

Read-only PostgreSQL inventory on October 21, 2026 confirmed revision
`20261018_04`, 1,054 local Players and 35,538 logs. Counts below use existing
verified current-season eligibility and metric rules, as of the inventory time;
they do not establish source completeness or historical-event lookahead coverage.
Real stored Props require retained provider evidence and exclude synthetic IDs.
All stored offers were non-actionable at inventory time; no odds refresh was run.

| Sport / season | Local Players | Players with real Props | Usable current research / reviewed mappings | Prop players with compatible metrics | Latest represented game |
| --- | ---: | ---: | ---: | ---: | --- |
| NBA 2026–27 | 21 | 2 | 0 / 20 | 0 | None recorded |
| WNBA 2026 | 94 | 12 | 87 / 87 | 12 | July 22 |
| NHL 2026–27 | 4 | 1 | 4 / 4 | 1 | October 17 |
| NFL 2026 | 489 | 7 | 352 / 352 | 7 | October 18; Weeks 1–6 |
| MLB 2026 | 446 | 13 | 1 / 1 | 0 | September 27 |

The priority gap is 13 retained-prop MLB players: Brice Turang, Chandler Simpson,
Christian Yelich, Cooper Pratt, David Hamilton, Garrett Mitchell, Jackson Chourio,
Jake Bauers, Junior Caminero, Liam Hicks, Sal Frelick, William Contreras and
Yandy Diaz. Their exact existing UUIDs and market contexts are in the private
identity-target file; official athlete IDs must be established before collecting
their game logs. Source/local team conflicts must not become automatic repairs.
NBA priority is Cade Cunningham and Jayson Tatum, followed by the other 18 reviewed
mappings; unresolved Jalen Brunson is excluded. NHL retains four verified mappings,
including goalie Tristan Jarry. Official retained roster IDs support three
additional profile candidates: Zach Hyman (8475786), Ryan Nugent-Hopkins (8476454)
and Frederik Andersen (8475883). Their current team, role and completed appearances
still require profile verification; no local UUIDs or Player records were created.

Private preparation lives under ignored `backend/data/odds_runs/phase9-coverage-07/`:
`inventory.json`, `reviewed-mappings.json`, `collection-proposal.json`,
`import-proposal.json`, coordinator scopes/previews and `verification.json`.
Existing normalizers and the read-only import CLI found **0 new, 0 updated,
3,697 unchanged, 0 rejected** retained observations (WNBA 2,059; NFL 1,576;
NHL 27; MLB 35). No repeat import is useful. An oversized retained NFL envelope
was split into bounded response-preserving artifacts; the 50 MiB importer limit,
source observations, weekly joins and original source digest remain unchanged.

The proposed source batch has **41 logical requests, at most 47 HTTP attempts
including permitted redirects, and 71,845,888 response bytes**. It includes MLB
season-roster identity discovery (1), NHL profiles/game logs for four mapped and
three candidate athletes (14), NFL release/schedule/exact season CSV (3), WNBA
release/exact season CSV (2), and NBA official calendar plus at most 20 reviewed
PlayerGameLog requests (21). The exact file binds endpoints, parameters, identities,
seasons, output paths, evidence digests and dependent-request gates. No retries,
proxies, provider switching, sportsbook requests, credits or database writes are
included. Unchanged release-asset metadata skips downloads. Only the named GitHub
assets may follow bounded allowlisted redirects. Ordinary source failures skip
dependents and preserve independent work; aggregate ceilings stop the batch.
NBA targets October 20 only if the calendar establishes completed regular-season
games. Retained calendar evidence is HTTP 403, not proof of completed games or a
new failure in this task; denial skips NBA without bypassing restrictions.

WNBA's later retained dates belong to team rows without player IDs; reviewed
player rows still stop July 22. NFL retained player rows stop at Week 6. Newer
releases remain unknown until the approved checks run. Remaining unmatched local
players include 6 WNBA and 45 NFL source/team conflicts, not reviewed mappings.
Coordinator previews cover supported NBA/NHL collection and all four non-NBA
artifact imports; published downloads and candidate verification remain explicit
source-specific steps. MLB statistics for the 13 targets require one subsequent
bounded batch after official IDs are resolved, rather than speculative ID binding.

An optional independently reviewable proposal identifies ten Ohtani legacy rows
with missing pitching metrics, verified against exact official athlete/game/date,
final regular-season schedule and matching hitting values. It adds only missing
strikeouts, earned runs and outs, with before/after digests; it preserves row UUIDs,
game IDs, dates, opponents and existing metrics. It does not expand eligible
research: unqualified legacy IDs remain excluded. The generic importer's overlap
guard is unchanged; applying the optional correction requires a separately approved
row-specific transaction. No ID qualification or historical rewrite is proposed.
New collected artifacts, new-Player identities and all database imports require
separate exact approval after normalization; future write counts are unknown.

Verification: existing import CLI and two coordinator dry-runs passed with external
HTTP blocked; five isolated research API GETs passed against PostgreSQL-enforced
read-only transactions with flush/write guards. NBA's empty state, WNBA L5/L10
5/10, NHL 5/8, NFL 5/6, and MLB's 35 reviewed appearances were verified. No runtime
or frontend code changed, so no full suites or new browser runs were necessary.
No collection, imports, migrations or development data writes were performed
during that preparation checkpoint.

### Feature 7 approved collection — October 21, 2026

Executed only collection proposal SHA-256
`ca1df63304da86154ceb2b61a1a0ce88346ff8ce3c2f8f349b03fab139997b4a`:
**19 logical requests, 21 HTTP attempts (two asset redirects), 8,574,735 response
bytes, zero sportsbook credits and zero database writes**. All limits were respected;
22 dependent requests were skipped. No retries, endpoint substitutions or bypasses.

NHL profiles verified Hyman (8475786, L), Nugent-Hopkins (8476454, C) and Andersen
(8475883, G). Only Hyman had qualifying current-season profile appearances; the
other two game-log requests were skipped. Actual retained logs contain three new
October 20 appearances for McDavid/Draisaitl/Bouchard plus three Hyman appearances.
Hyman requires separately approved local Player creation; no Player was created.
NFL's changed asset adds eight reviewed-player appearances through October 19,
still Weeks 1–6. WNBA's asset bytes are unchanged: player coverage ends July 22;
later team-only rows and playoffs do not expand regular-season player coverage.
The NBA calendar returned **HTTP 403**; all 20 PlayerGameLog requests were skipped.
No NBA completed-game coverage was established or inferred.

MLB season-roster collection verified 12 existing prop-player identities against
official batting roles and independent retained schedule team identities. Liam
Hicks (689414) is excluded because official Rays affiliation conflicts with the
local Brewers record. No identity repair or MLB game-log collection occurred.
The separate ignored `mlb-followup-collection-proposal.json` proposes exactly
12 hitting requests/attempts, 25,165,824 response bytes and zero credits/writes;
completed-game counts remain unknown pending separate approval and collection.

The ignored `postcollection-import-proposal.json` proposes two independently
reviewable NHL/NFL transactions: **14 new logs, one Hyman Player creation, zero
updates/deletions/repairs**. Its comparison excludes 3,662 unchanged observations
and avoids observation-only rewrites. It binds exact UUIDs, source mappings,
artifact/record digests, target/revision, per-transaction counts and rollback rules.
No WNBA, NBA, MLB or Ohtani mutations are included. Both new proposals require
separate explicit approval of their exact file digests before execution.

Verification: nine mocked transport/dependency checks passed; all 21 response-file
sizes/hashes and published dataset sizes/digests passed offline checks. Existing
normalizers accepted 3,676 reviewed observations with zero rejected rows. Existing
importer previews ran in PostgreSQL-enforced read-only transactions with SQL/flush
guards; 11 new existing-player rows were confirmed, with three additional Hyman
rows pending creation approval. In-memory research previews verified 12 affected
players, including NHL 5/9 and Hyman 3/3 L5/L10 samples. Each NHL athlete retains
its own response observation timestamp. Database logs remain 35,538. No runtime or
frontend changes; full suites and browser checks were not rerun for data-only work.
All raw responses, ledgers, private proposals and task-local scripts remain ignored.

### Feature 7 approved import and MLB collection — October 21, 2026

Executed the separately approved NHL/NFL import (proposal SHA-256
`498c9bb54c29452fd91edea4cef9b573f18e80e2cc46f93b501ede85d9a60486`)
using the existing importer in two explicit sport transactions. Both committed:
six NHL and eight NFL logs, plus only the reviewed Zach Hyman Player. PostgreSQL
`localhost:5432/proppulse` remains at revision `20261018_04`, with **35,552 logs
and 1,055 Players**. Exact before/after hashes confirmed every pre-existing Player
and log unchanged. No unrelated writes, imports, migrations or provider calls were
part of those transactions. Private receipts retain inserted row UUIDs.

NHL usable research increases from four to five Players. Hyman has three recorded
appearances, with L5/L10 samples 3/3; McDavid, Draisaitl and Bouchard have nine,
with samples 5/9 through October 20. NFL remains 352 eligible Players, now with
the eight added October 19 appearances; coverage is still Weeks 1–6. Actual source
observation timestamps are preserved and completeness remains unknown.

Executed only the approved MLB hitting collection (proposal SHA-256
`f1ac8248011bde5b3d8be6e62ff96a0cf40d5be1794ed48aa8754bbc8c0feb35`):
**12 logical requests, 12 attempts, 2,123,913 response bytes, 12 successful datasets,
zero failures, zero credits and zero database writes**. No retries, substitutions,
additional identities, pitching or Ohtani calls. Liam Hicks remains excluded.
Offline official game/date/team/final-regular-season joins accepted 1,605 batting
appearances, with zero rejected source rows. **1,221 overlap existing unqualified
legacy game IDs** and are withheld without duplicate insertion or modification.

The separate ignored `mlb-import-proposal.json` binds source/identity/schedule and
record digests, existing UUIDs, conflict before-images, exact absence checks and
per-player rollback boundaries. It proposes **384 new logs across 12 existing
Players**, with zero updates, creations or repairs. It requires new explicit
approval and has not executed. This would add partial qualified research for
those 12 Players; excluding legacy overlaps leaves gaps and cannot establish full
season coverage or an uninterrupted last-ten-game history.

Focused verification passed: both approved scope/evidence preflights, post-import
idempotency (14 unchanged), 12 affected-player research API GETs on an isolated app,
NHL/NFL source/coverage/sample checks, MLB response hashes/byte ceilings, existing
normalizers and 12 read-only importer previews. Post-import checks and proposals
blocked provider HTTP and enforced PostgreSQL read-only transactions with flush/SQL
guards. No frontend/runtime changes; full suites and browser checks were not
repeated for this data-only execution. Protected reports remain unchanged.

### Feature 7 final MLB import and coverage — October 21, 2026

Executed the explicitly approved MLB import proposal SHA-256
`f1d9fd9375e21960a3fdef8ea332f45cac3fab8a2c8763d70dcc23d5eb774f12`.
All twelve per-Player transactions committed: **384 inserted, zero updated,
zero rejected**. Exact proposal, twelve source/normalized artifacts, record digests,
official athlete/UUID mappings, final regular-season game identities, target and
revision passed preflight. No libpq environment/query/DSN routing overrides were
present. Existing transactional importer and legacy-collision guards were reused.

Confirmed PostgreSQL totals: **35,936 logs and 1,055 Players**, revision
`20261018_04`. Every pre-existing log and every Player matched its before hash;
no duplicate Player/game keys exist. All 1,221 legacy overlaps remain untouched
and excluded. Second dry-run preview: **384 unchanged**, zero inserts/updates.
No provider requests, credits, migrations, identity repairs or Player changes.

| Existing MLB Player | New qualified appearances |
| --- | ---: |
| Brice Turang | 42 |
| Chandler Simpson | 13 |
| Christian Yelich | 40 |
| Cooper Pratt | 32 |
| David Hamilton | 37 |
| Garrett Mitchell | 41 |
| Jackson Chourio | 46 |
| Jake Bauers | 42 |
| Junior Caminero | 16 |
| Sal Frelick | 21 |
| William Contreras | 41 |
| Yandy Diaz | 13 |

| Sport / selected season | Eligible research Players before → after Feature 7 | Latest represented game before → after | Feature 7 new logs |
| --- | --- | --- | ---: |
| NBA 2026–27 | 0 → 0 | None → None | 0 |
| WNBA 2026 | 87 → 87 | July 22 → July 22 | 0 |
| NHL 2026–27 | 4 → 5 | October 17 → October 20 | 6 |
| NFL 2026 | 352 → 352 | October 18 → October 19 | 8 |
| MLB 2026 | 1 → 13 | September 27 → September 27 | 384 |

Focused read-only checks passed for all twelve imported hitters: 24 research API
GETs covering current summaries and exact retained Prop identities; 24 actual
stored hits/total-bases market/line checks; correct 2026 Regular Season, source,
last game and observation metadata; 5/10 valid recorded samples; missing pitching
metrics stay unavailable. The shared Discover URL helper preserved twelve actual
Player UUIDs, Prop IDs and selected lines. No arbitrary sportsbook prices or lines
were introduced. Current-time research and historical Event reference times remain
distinct: nine retained selections correctly have no eligible pre-reference games,
while three have recorded evidence. Imported observations do not backfill lookahead.

Live Discover returns no actionable MLB results because retained offers are stale;
no browser interaction with a live MLB card was possible. API/URL navigation was
verified without refreshing prices. Full suites, builds and browser runs were not
repeated for this data-only task. Private execution receipts and final verification
remain under ignored `backend/data/odds_runs/phase9-coverage-07/`.

Limits remain explicit: NBA calendar HTTP 403; WNBA player-source cutoff July 22;
NFL Weeks 1–6; Liam Hicks excluded for the source/local team conflict. The retained
six WNBA and 45 NFL source/team conflicts were not repaired, and NHL's other two
profile candidates still lack qualifying appearances. MLB overlaps leave gaps;
all source completeness remains unknown. L5/L10 means latest eligible recorded
samples, never proof of a complete season or uninterrupted recent-game coverage.

### Feature 8 — Saved selections and slip editing — October 22, 2026

Generic Saved Prop bookmarks remain unchanged. Optional exact rows in the same
`saved_props` table preserve Prop/Event/Player identity through existing relationships,
sportsbook, line, direction, original American price and provider observation time.
Authenticated create/read/edit/delete operations enforce ownership; repeated saves
retain the original evidence. Generic unsave never deletes exact selections.

Saved Props now separates bookmarks and exact selections, with player/market search,
sport/type filters, exact-line research links, original/current price details,
unsave and add-to-slip actions. Shared Prop cards (including Discover and Game Detail)
and exact research panels can save precise selections. Expired saved selections can
be copied into the research slip for reference; a different existing selection is
never overwritten. Exact save hydration preserves completed local mutations.

The drawer edits the existing item in place using shared comparison groups. Users
explicitly choose sportsbook/line/side and confirm; failed or stale alternatives
leave the original intact. Other items and stable identities survive editing,
navigation and reload. A changed identity captures new original evidence; repeating
the same identity does not reset its original price.

Price change compares decimal payout derived numerically from American odds for
one identical Prop/book/line/side only (+100 and -100 are equal). Labels are improved,
worsened or unchanged; last-known prices are informational. Original/latest provider
observation times display separately in Eastern time. Missing historical originals
remain "Original price unavailable." Missing/expired/started current offers remain
"Current price unavailable." Ingestion timestamps never renew freshness. Existing
availability policy and estimate safeguards remain authoritative; no coverage or
historical-statistics calculations changed.

Migration `20261022_05` follows `20261018_04`: five nullable SavedProp fields and two
nullable SlipItem fields, with no historical backfill. Existing bookmark and slip
identities remain intact. **Not applied to development PostgreSQL; separate explicit
approval is required.** Apply before running the updated backend against existing
tables. Downgrade discards new exact saved rows and original-price metadata, while
preserving generic bookmarks and slip identities; review before any rollback.

Validation: 86 focused backend tests passed across exact persistence/ownership,
atomic failures, migration upgrade/downgrade, offer availability/equivalence,
sportsbook comparison and existing slip/estimate safeguards. Disposable SQLite only;
PostgreSQL DDL/concurrent locking and a live migrated application were not tested.
Frontend: 113 Node tests, TypeScript and production build passed. Six Playwright
checks passed at 390px/1440px with all API/provider traffic mocked: exact save/unsave,
bookmark distinction, filters, invalid alternatives, failed/successful in-place edits,
reload persistence, expiry retention, exact research links, Discover and multi-sport
research. No development database changes, provider calls, commits, push or deployment.
The full backend suite and live-provider browser checks were not run.

Changed files for Feature 8:

- Backend: `app/models.py`, `app/schemas.py`, `app/routers/users.py`,
  `app/routers/interactions.py`, `app/services/slip_service.py`,
  `alembic/versions/20261022_05_saved_selections.py`,
  `tests/test_saved_selections.py`, `tests/test_offer_availability.py`.
- Frontend: `src/app/saved/page.tsx`, `src/lib/api.ts`, `src/lib/types.ts`,
  `src/store/savedProps.ts`, components `AppInit.tsx`, `ExactLinePanel.tsx`,
  `PropCard.tsx`, `SlipDrawer.tsx`, `SaveExactSelection.tsx`,
  `SelectionPrice.tsx`, `SlipSelectionEditor.tsx`,
  `tests/saved-selections.test.cjs`, `e2e/saved-selections.spec.cjs`.
- Documentation: this existing Phase 9 document. Both protected untracked reports
  remain untouched. All implementation changes remain uncommitted.

### Feature 8 approved migration execution — October 22, 2026

After separate explicit authorization, applied only `20261022_05` to
`localhost:5432/proppulse` from verified revision `20261018_04`. Rechecked the
reviewed migration SHA256 and the approved 3,113,322-byte backup SHA256 before
execution. The existing Alembic workflow used an explicit connection, one
transaction, bounded lock/statement timeouts and an SQL allowlist: exactly seven
nullable/no-default columns plus the version-row update. No other migration ran.

PostgreSQL confirms revision `20261022_05`; all seven columns have the expected
types, no defaults and NULL values on legacy rows. Every original-column row
fingerprint and count matched the backup before migration, after migration and
again after integration-test rollback. Constraints, indexes, triggers, functions,
relations and other captured schema objects are unchanged. Preserved counts:
4 users, 1 generic bookmark, 3 slips, 1 slip item, 6,145 Props, 6,843 offers,
19,895 offer snapshots, 35,936 game logs and 1,055 Players.

All **33 PostgreSQL integration checks passed**, with real authenticated API
routes in an isolated FastAPI app (no application lifespan): existing bookmark
and slip IDs, exact CRUD/deduplication, bookmark coexistence, ownership/auth,
saved-to-slip conflicts, stable slip editing, persistence across Sessions,
missing original prices and unavailable/expired estimate safeguards. Successful
write paths used actual retained offers at a frozen provider observation time;
no source timestamps/prices were changed or presented as currently live.
Disposable-user persistence writes stayed inside an outer rollback transaction;
source-table writes were blocked, and disposable users were confirmed absent.
No checks were skipped. No full-suite/frontend rerun was needed for this
schema-only execution; no production or provider checks were performed.

Backup and private verification evidence remain outside Git under
`<private-backup-directory>/`
(`migration-execution.json`, `postgres-integration.json`,
`post-integration-integrity.json`). No source-data import, provider request,
credits, unrelated database writes, downgrade, push or deployment occurred.
Feature 8 remains uncommitted; both protected untracked reports are untouched.
No further approval or corrective change is required for this migration.

### Feature 9 — Real-data UI polish — October 23, 2026

Refined the existing Discover → comparison → exact research → Saved → research
slip journeys. Availability contracts, provider thresholds, search semantics,
authentication, exact identities and calculation logic are unchanged.

- Sportsbook observation dates are visible without hovering, in Eastern time.
  Missing observations remain unknown. Original/current prices are separate;
  unavailable originals explain that no price was recorded. Expired, started,
  last-known and missing prices explain estimate exclusion and retain selections.
- Exact research switches between L5/L10 chart and table samples without fetching.
  The API supplies at most ten game rows; season denominators remain separate.
  Semantic column headers, a keyboard-scrollable table, chart text alternatives,
  missing-value gaps and explicit denominators improve readability. Source
  observations use readable Eastern dates; verified opponent IDs remain explicit.
- Discover filters have named active values and roomier mobile controls. API
  failures no longer announce zero results. Game-filter failures retain choices
  and offer a retry. Game Detail announces loading/errors and labels eligible books.
- Slip editing uses the drawer's full width and one scroll container. Removed
  duplicate price/status blocks. Failed alternative loading hides outdated choices
  and offers retry; focus enters the editor and returns after cancel/save. Failed
  edits retain the original pick. Bookmark actions prevent overlapping submission.
- Slip hydration failures show recovery instructions rather than an empty slip;
  mutations stay blocked until recovery. Successful empty retries remain visible.
  Temporary account API failures no longer delete the sign-in token. Saved refreshes
  keep populated controls mounted and exact-selection failures announce inline.
- Added loading/error announcements, explicit icon labels and brighter indigo
  secondary text. Fixed clipped Y-axis labels and bounded the recorded-game table.
  Existing skip link, focus rings, Escape handling and server layout are preserved.

Verification: `npm test` **116 passed**; `npx tsc --noEmit` and `npm run build`
passed. **14 Playwright checks passed**: 11 offline fixture checks covering
Discover URL/back navigation, all five sports/roles, exact-line missing values,
save/unsave, failed/successful edits, retry/focus restoration, expiry retention,
reload persistence and temporary failures; plus 3 actual development-data checks
at **390 / 768 / 1440px**, with no application API response fulfilled by fixtures.
Screenshots were visually inspected; horizontal overflow checks passed. Following
the axis-spacing adjustment, the six exact-research/development browser checks
were rerun with an explicit axis-label clipping assertion.

Real-data verification used `localhost:5432/proppulse`, revision `20261022_05`,
through a temporary API harness: PostgreSQL read-only connections, GET/OPTIONS
only, lifespan disabled and provider HTTP blocked. Started only the existing DB
container; no migrations or application writes. Discover returned zero eligible
props. Researched Jackson Chourio's retained MLB hits Prop
`LOCAL_PROP_ID` at DraftKings 0.5: expired October 20
observation, 46 recorded season appearances, recent L5/L10 values, no current best
price. Switched side/book, reloaded, checked sign-in-required saving and opened
the empty Game Detail. Also manually browsed A'ja Wilson's retained WNBA season
statistics. These are historical recorded samples, not verified complete seasons.
The opt-in `ui-polish-development.spec.cjs` takes retained player/Prop/Event IDs
through `PROPPULSE_DEV_*` and requires `PROPPULSE_DEV_READONLY_BROWSER=1` against
the guarded API; it never sends mutation requests.

Limitations: the retained dataset cannot demonstrate an actionable current offer.
Authenticated writes, edit recovery and saved/slip persistence were exercised with
clearly invented offline API fixtures, not by changing development accounts.
Opponent names are unavailable where only verified source IDs exist; complete
season coverage remains unknown. No manual screen-reader session, production
checks, provider refresh, backend regression suite (no backend changes), commit,
push or deployment. Generated browser evidence remains ignored.

Changed files (all frontend paths below are relative to `frontend/`):

- Pages/styles: `src/app/discover/page.tsx`, `src/app/games/[gameKey]/page.tsx`,
  `src/app/player/[id]/page.tsx`, `src/app/saved/page.tsx`, `src/app/globals.css`.
- Components: `src/components/AppInit.tsx`, `DataStatus.tsx`, `ExactLinePanel.tsx`,
  `NavBar.tsx`, `PlayerResearchChart.tsx`, `PropCard.tsx`, `SelectionPrice.tsx`,
  `SlipDrawer.tsx`, `SlipSelectionEditor.tsx`, `SportsbookComparison.tsx`;
  state: `src/store/slip.ts`.
- Tests: `tests/sportsbook-comparison.test.cjs`, `tests/ui-polish.test.cjs`,
  `e2e/exact-line-research.spec.cjs`, `e2e/saved-selections.spec.cjs`,
  `e2e/ui-polish.spec.cjs`, `e2e/ui-polish-development.spec.cjs`.
- Documentation: this file. Expected HEAD `6f389c3dafb0e96005990dd0e426ed7663a1a6f6`
  confirmed. Changes remain uncommitted. Pre-existing README/backend edits,
  untracked `frontend/.node-version`, and both protected untracked reports are
  preserved. No secrets, private approvals, backups or screenshots added to Git.
