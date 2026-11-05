# Milestone 3I: inventory performance

October 16, 2026. Starting commit: `a643efab49be086ff8020daadb9c25f845a15027`;
the working tree was clean. Application and parent AGENTS instructions and the
3G, 3H and 3D reports were reviewed before implementation. Parent instructions
required bounded parallel work: benchmark harness, frontend verification and
independent regression/review work; the primary agent owned application changes.

## Safety and measurement method

Only a newly created, explicitly identified local `postgres:15-alpine` container
is used: `proppulse-test-m3i-20261016`, ID
`96be3b365ab7b19f98dfb31a307887ae81821aa5bf6712bd26cb28b1f0e8f151`, loopback
port 59624. PostgreSQL has two CPUs, 1 GiB memory, 128 PIDs and tmpfs-only data
storage; no bind mounts or named volumes. Test-only trust authentication is
restricted to this disposable environment. Docker commands pin the local named
pipe, rather than inheriting a remote context. Development containers remained
stopped; no development database connection was made.

The existing `tests/profile_inventory.py` was run **before editing performance
code** to reproduce the historical 6,000-prop fixture. Its three observations
are an initial diagnostic, not the final 30-request acceptance measurement.
The unchanged source was also retained under ignored
`backend/data/odds_runs/m3i/baseline_source/app/`. Git-normalized blobs of the
seven modified original modules were verified against the starting commit:

| Original module | Git blob |
| --- | --- |
| routers/props.py | 51f867e541bac07fff0f39f4efa50759268ae10e |
| routers/users.py | a0071b6b5970d95af6fab42a19ea7d8b493c9db2 |
| services/offer_service.py | 33b5908ed2cb0c1db2a95f016bfd323f70a38a50 |
| services/game_identity_service.py | 89447a055eacc93e204daba9e0d4c84c18ce15b7 |
| services/trend_service.py | 26de2d1dce70084cac2217b40296c211df3cf46d |
| services/ranking_service.py | bb5ddd8fdc675d42809e566d5c6e70a58e02413d |
| services/discovery_service.py | 6b8a2f45c95ac8bdbff95e6d24c1120d711ee24d |

The new explicitly invoked `tests/benchmark_inventory.py` uses deterministic
UUIDs, a fixed UTC clock, five sports and a separate random schema per run in a
guarded loopback `proppulse_test_` database. Explicit synthetic database, refresh
and provider environment values are installed first. The configuration module's
initial settings construction can read `.env`; its instance is replaced with
`Settings(_env_file=None)` **before engine construction**. No configured development
target is used and no application lifespan runs. External HTTP is blocked.
Requests use PostgreSQL read-only
transactions; complete table counts and content fingerprints bracket the reads.
Fixture creation is explicit; existing disposable migration tests are separate
from the performance fixture's metadata bootstrap.

Timing uses ASGI TestClient, warm-up followed by 30 sequential requests per
surface. Tracemalloc is a separate request. It measures Python allocations,
excluding libpq/PostgreSQL/native memory; process working-set RSS is recorded
separately. The host Python process is not CPU-capped. These are local laboratory
measurements, not production worker/network/ingress capacity certification.
The statistical harness loads a fixed synthetic user through a dependency
override and one SQL lookup; it does not time JWT signature verification. Both
versions receive identical identity/personalization inputs. Focused hydration
and integrated browser tests exercise the actual authentication dependencies.

The richer fixture has ten props per player, multiple markets and lines, three
books, snapshots, linked and unlinked games, archived/unavailable collision
evidence, start boundaries, stale legacy schedules, missing history/fatigue and
both current/prior-season logs. Saved 20 and slip 10 reference distinct players;
another owner has separate selections. The scaling history has ten valid current
observations per populated player; focused original-source goldens additionally
exercise cross-season recent windows and strict four/five-decision thresholds.

All-candidate Feed/Discover and all-card Games oracle captures call the same route
implementation with a larger output limit **only in the harness**. HTTP timing
uses the unchanged public limit of 20 and offset 0/2000. Additional HTTP responses
cover sports, Event filters, exact research selections, legacy conflicts, errors,
empty offsets and `/todays-games` compatibility. No response fields are excluded:
the clock is frozen, so request-time metadata also compares exactly. Golden
results are generated from retained pre-optimization source, never from optimized
output. The focused JSON fixture files record original-source hashes.

## Initial reproduction

| Historical fixture, 6,000 props | Median ms | SQL statements | Traced peak MiB |
| --- | ---: | ---: | ---: |
| Upcoming Games 20 | 1,519.68 | 3 | 67.15 |
| Feed first / offset 20 | 1,021.85 / 1,030.83 | 5 / 5 | 58.30 / 58.30 |
| Discover first / offset 20 | 4,957.84 / 5,096.48 | 2 / 2 | 111.04 / 111.37 |
| Event Detail, 50 props | 53.64 | 7 | 1.32 |
| Player Research | 37.52 | 7 | 0.41 |
| Saved 20 | 96.68 | 102 | 0.34 |
| Slip 10 | 52.67 | 53 | 0.22 |

This reproduces the reported scale of the original bottlenecks. Preliminary runs
and validation overlapped some host work; final statistical runs are separate.
Raw initial evidence: ignored `backend/data/odds_runs/m3i-historical-baseline.json`.

## Investigation and implementation

Discover already loaded player logs in one batch, but recomputed exact-line
history twice for every qualified prop and constructed full response dictionaries
before sorting/pagination. The response retained many identical player/Event,
offer-metadata and historical-window structures for rows never returned.
Eligibility, best-line comparison and aggregate freshness repeatedly constructed
and formatted timestamp-rich dictionaries when callers needed only a boolean.

The read-only inventory service executes the **same SQL text and bind values**
as the existing eager ORM query, using the public ORM label-style setting. It
consumes Python rows in batches of 256, deduplicates props/offers in first-row
order and shares player/Event values. Lightweight request-local subjects replace
ORM instrumentation and the ORM's full joined-row object buffer. Tuple-backed
records also avoid a separate attribute dictionary per prop/offer/log. The complete
column layout is validated before interpretation. An unexpected loader shape or
pending session mutations fall back to the original ORM loader. Write paths and
Event-specific fast paths retain ORM loading. Broad historical loads use the
same validated Core approach, preserving all game-log columns, exact SQL/binds,
date order and log identity deduplication. Loads for at most 50 props retain the
existing small-request ORM path; this threshold changes only materialization,
never historical membership. The driver can still buffer native rows; this is
not a server-side cursor or bounded database scan.

Discover still examines and scores **every eligible candidate**. It retains
compact sorting tuples and original scores/reasons, applies the original stable
sort, and serializes only the selected page. Identical player/sport/market/line/
effective-start historical inputs share request-local trends. A second cache
shares line-independent validation/ordering across lines for the same historical
subject; each exact line still classifies every eligible value and uses the same
window implementation. The summary code was extracted without changing formulas.
Stage profiling exposed cache thrashing when the database interleaved players.
Past-date history is therefore prepared by player, storing only six exact scalar
inputs per candidate and releasing the full historical dictionaries before
scoring. FIFO budgets retain at most 128 prepared histories and 256 exact-line
trends; eviction only causes recomputation. Prices and scores are still evaluated
in the original candidate order. Cache keys include the UTC date; histories
containing today's/future/invalid dates, missing starts, or a changed UTC day
use the original per-candidate calculation. Thus time-sensitive completion
evaluation remains intact. Ranking weights, sample
requirements, hit-rate denominators and tie-breaking keys are unchanged.
Discover did not use fatigue before this milestone and still does not.

Offer policy now evaluates a compact internal state and formats metadata only
when required. Public decisions retain all original fields and precedence.
Predicates, best-line selection and aggregate freshness use that same shared
policy; no parallel eligibility formula or SQL approximation was introduced.
Compact Discover scoring omits offer serialization but retains exactly the
original best Over/Under and equivalent-line book count.

Games collision evidence now projects only the identity fields of **all unlinked
props**, without activity, offer, schedule or page filtering. Complete Event rows
already represent every linked identity, including empty Events; repeating every
linked Prop contributes no new collision evidence. Missing opaque IDs, unresolved
contexts and inactive/expired conflicts remain included. Candidate grouping and
stable ordering remain unchanged. Only a group's winning freshness observation
needs full metadata serialization; equal-age ties still retain the first winner.

Feed uses the lightweight loader and compact shared offer policy, preserving its
whole-candidate ranking, popularity denominator, Eastern-day priority and stable
pagination. Per-player fatigue response dictionaries are reused without changing
scores/models/reasons. Refresh aggregation reads the same conservative selected
observation without formatting unrelated metadata. Event/legacy game-specific
Feed remains deliberately unpaginated.
No SQL LIMIT is pushed ahead of eligibility or ranking.

Review also caught an ORM-identity-map dependency in personalized Feed: removing
tracked candidate props made interaction relationships issue lazy queries.
A real-authentication regression with 30 interacted players reproduced **65**
statements. Interaction prop/player associations are now eagerly loaded and
identical sport/type/player affinity sets are constructed once per request.
The request uses **5 SELECTs**, preserving ranks, reasons, fatigue and trends.
No interaction history is truncated or shared across users.

Saved/slip hydration first applies the existing owner/open-slip filters, then
loads only referenced props with player/Event/offers eagerly and fatigue once per
distinct player. The original saved/item rows determine response order. No
eligibility filter removes historical selections. Slip resolution still uses
the stored sportsbook, side and line; no better live price is substituted and
no payout logic changes. Real-authentication regressions measure Saved 20/40
at **5/5** queries and Slip 10/20 at **6/6**, with unchanged full-table fingerprints.
An initial joined offer loader met a smaller query count but a new regression
exposed a correctness problem: a legitimate merge plan reversed equal-price
case-equivalent `FanDuel`/`FANDUEL` entries, changing the reported best book.
Offers now use a separate `selectinload` batch; the original lazy-load order in
that regression is preserved. One extra query is preferable to changing a tie.

## Equivalence and verification

Focused evidence includes:

- 51 original-only offer-policy golden cases, zero field exclusions: inclusive
  30-minute/six-hour thresholds and ±1 microsecond, Event start equality,
  future/missing observations, invalid prices/IDs, primary versus alternate
  offers, exact line tolerance, duplicates, case handling and UTC offsets.
- 30 original-only history/scoring cases across all five sports plus complete
  PostgreSQL Discover responses: four/five decisions, pushes, missing statistics,
  missing history/fatigue, cross-season recent windows, strict season windows and
  equal-score ties.
- ORM/Core exact SQL and parameter equality, all-column ordered subject equality
  for 300 props/598 offers, collection deduplication, shared identities, clean
  sessions, fallback behavior and original pagination/deep-offset equivalence.
- Inactive/expired/unresolved legacy conflicts, collisions outside the visible
  Games limit and an empty Event whose corrected schedule collides with legacy.
- Saved/slip authorization, original ordering, exact selected book/line/side,
  unavailable selections, fixed query growth and read-only data preservation.
- 630 compact-versus-full scoring comparisons, original price/score visitation
  order, bounded-cache eviction and midnight fallback. Full public trends are
  always constructed by the original serializer for the returned page.

Final-source verification (reruns are not added to totals):

| Check | Result |
| --- | --- |
| Complete backend via `tests/run_no_provider_http.py` | **573 passed**, including **161 PostgreSQL scenarios**; zero failures/errors/skips, 99.961 seconds |
| External HTTP attempts in complete backend run | **0** |
| Frontend `npm test` | **59 passed**, zero failures/skips/cancellations |
| `npx tsc --noEmit` | Passed |
| Frontend production build | Passed; ten static pages, explicit localhost API origin |
| Existing mocked Chrome desktop/mobile | **36 passed**, exit 0 |
| Final-source real Chrome desktop/mobile | **24 passed**, 16.9 seconds, exit 0 |
| Final-source real Edge desktop/mobile | **24 passed**, 16.7 seconds, exit 0 |
| Browser data preservation | All **13 tables / 80 fixture rows** unchanged; provider HTTP attempts **0** |
| Python compilation | `compileall -q backend/app backend/scripts backend/tests backend/alembic` passed |
| Git tracked whitespace | `git diff --check` passed |
| Changed/new text whitespace | All 19 changed/new text files passed direct whitespace inspection |

Browser total is **84 passing executions**: 36 mocked plus 48 integrated. Chrome
and Edge are both Chromium; this is not independent Firefox/WebKit/mobile-engine
coverage. The checked-in Playwright-managed Windows server teardown initially
hung after assertions. An ignored temporary config and separately supervised
owned Next process ran the same existing tests successfully. Exact owned process
handles were cleaned up; final ports 8000/3199 had no listeners. No broad process
kill was used. Earlier interrupted runs are not counted as passes.

The full backend uses explicitly isolated PostgreSQL and blocked HTTP. Tests
that exercise existing ingestion/migration code operate only on synthetic data,
mocks and disposable schemas; their console messages are not live-provider work.
Existing mocked browser tests and actual-router/read-only PostgreSQL browser
tests are distinct evidence. Browser fixture scenarios explicitly mutate and
restore their synthetic rows before the final complete-table fingerprint check.

## Capacity, indexes and release constraints

No schema, dependency, operational migration, production setting, frontend design,
fatigue model or research formula was changed. No migration was applied to
development. Existing isolated migration cases remain part of verification.
Provider requests, refresh workers, ingestion, Event backfills, deployment,
commits and pushes are outside this milestone and were not performed.

Candidate retrieval, global ranking and legacy collision evidence still scale with
inventory. Chunked Python materialization and page-only response construction do
not establish constant-time pagination or constant total memory. There is no
proven safe fixed candidate cap or SQL top-K replacement for all existing policy
and stable encounter-order semantics. A future indexed design needs a declared
stable tie contract and equivalent global collision/eligibility evidence first.

The existing 3G/3H build isolation, dependency advisories, gateway abuse controls,
TLS, monitoring and release acceptance requirements remain in force. A successful
local benchmark does not resolve those release gates.

## Final statistical results

The final 6,000-prop comparison passes all 37 response surfaces with exact JSON
scalar types, values and array order, zero field exclusions and unchanged fixture
content fingerprints within each run. Both first and deep Discover pages meet the latency and
memory targets in this run; the median's approximately 4–8 ms margin is too small
to claim dependable capacity headroom. Feed and Games still miss their 500 ms
median targets. Both sizes pass all 37 surfaces: **74 exact before/after response
comparisons**, with zero differences. All four baseline/optimized fixture
fingerprints are unchanged after reads. Seed-function hashes match across runs;
final optimized application hashes match between sizes.

Each cell below is **before → after**. Latency is milliseconds, peak is MiB.
Each surface has 30 timed observations after warm-up. Some baseline observations
overlapped validation on the host, which can inflate tail latency; final optimized
measurements ran without other heavy validation. These are engineering evidence,
not a controlled CPU-isolated capacity certification.

| 6,000 props | Median ms | p95 ms | Traced peak MiB |
| --- | ---: | ---: | ---: |
| Feed first | 1,340.38 → 556.92 | 1,421.03 → 609.59 | 69.003 → 18.178 |
| Feed offset 2,000 | 1,327.13 → 561.25 | 1,376.24 → 596.57 | 69.002 → 18.327 |
| Discover first | 5,519.03 → 996.30 | 5,827.97 → 1,058.67 | 122.986 → 31.197 |
| Discover offset 2,000 | 5,599.29 → 992.27 | 6,007.18 → 1,049.79 | 122.988 → 31.155 |
| Games | 1,479.43 → 523.90 | 1,604.93 → 566.09 | 79.950 → 15.407 |
| Event Detail | 19.24 → 17.52 | 23.24 → 25.28 | 0.212 → 0.213 |
| Player Research | 14.96 → 14.27 | 20.03 → 15.22 | 0.241 → 0.251 |
| Saved 20 | 101.02 → 17.20 | 117.86 → 20.77 | 0.376 → 0.435 |
| Slip 10 | 53.62 → 17.21 | 105.17 → 23.63 | 0.252 → 0.271 |

| 12,000 props | Median ms | p95 ms | Traced peak MiB |
| --- | ---: | ---: | ---: |
| Feed first | 2,632.33 → 1,119.55 | 2,717.56 → 1,240.15 | 138.024 → 35.795 |
| Feed offset 2,000 | 2,674.01 → 1,114.82 | 2,853.95 → 1,197.69 | 138.023 → 35.939 |
| Discover first | 11,172.59 → 2,033.25 | 14,631.46 → 2,111.31 | 246.409 → 61.933 |
| Discover offset 2,000 | 11,147.89 → 2,028.67 | 14,304.19 → 2,200.92 | 246.417 → 61.924 |
| Games | 3,066.29 → 1,081.26 | 3,162.05 → 1,152.15 | 160.104 → 31.698 |
| Event Detail | 16.57 → 18.49 | 19.41 → 55.10 | 0.212 → 0.212 |
| Player Research | 33.93 → 33.49 | 44.35 → 40.64 | 0.237 → 0.250 |
| Saved 20 | 89.47 → 20.13 | 123.46 → 24.58 | 0.376 → 0.433 |
| Slip 10 | 46.57 → 17.62 | 66.47 → 24.17 | 0.252 → 0.273 |

SQL statements include **one extra benchmark-only `SET TRANSACTION READ ONLY`**.
Thus final application counts are Saved **5**, Slip **6**; the table shows 6/7.
Rows are actual SELECT cursor row counts, including joined duplicates, not unique
objects or physical scanned rows. Query count is identical at both sizes.

| Surface | SQL before → after | SQL rows 6k before → after | SQL rows 12k before → after | Eligible/ranked/items 6k / 12k | Returned |
| --- | ---: | ---: | ---: | ---: | ---: |
| Feed first | 6 → 6 | 15,953 → 15,953 | 31,470 → 31,470 | 4,952 / 9,905 | 20 |
| Feed deep | 6 → 6 | 15,929 → 15,929 | 31,470 → 31,470 | 4,952 / 9,905 | 20 |
| Discover first/deep | 3 → 3 | 28,278 → 28,278 | 56,577 → 56,577 | 4,563 / 9,139 | 20 |
| Games | 4 → 4 | 21,651 → 17,151 | 43,298 → 34,298 | 600 / 1,200 groups | 20 |
| Event Detail | 8 → 8 | 24 → 24 | 24 → 24 | 7 / 7 | 7 |
| Player Research | 6 → 6 | 46 → 46 | 46 → 46 | 10 / 10 recent games | 10 |
| Saved | 93 → 6 | 145 → 115 | 145 → 115 | 20 / 20 | 20 |
| Slip | 49 → 7 | 75 → 60 | 75 → 60 | 10 / 10 | 10 |

Public page size remains 20. Games' existing public `total` is the returned
limited-card count (20); 600/1,200 are full-oracle groups, not a changed contract.
Discover scores 4,952/9,905 eligible subjects; 4,563/9,139 pass the unchanged
minimum-history scoring rule. Event Detail's seven props and Research's ten recent
games are comparable small requests; the initial historical reproduction also
measured the pre-change 50-prop Event fixture. A default research selection has
no snapshots; the exact-prop oracle additionally exercises existing snapshots.

RSS is whole-process Windows working set measured after each separate trace in
the fixed endpoint sequence. It includes allocator retention, driver buffers and
prior endpoint work, so it is neither an endpoint allocation peak nor proof of a
leak. Native memory is not included in tracemalloc.

| Surface | RSS MiB 6k before → after | RSS MiB 12k before → after |
| --- | ---: | ---: |
| Feed first | 179.96 → 156.90 | 259.12 → 203.17 |
| Feed deep | 179.95 → 157.18 | 260.39 → 203.89 |
| Discover first | 230.50 → 156.89 | 429.94 → 207.13 |
| Discover deep | 234.09 → 158.43 | 444.28 → 269.98 |
| Games | 234.28 → 159.56 | 366.22 → 267.07 |
| Event Detail | 241.29 → 165.25 | 373.34 → 267.72 |
| Player Research | 242.71 → 165.50 | 375.65 → 267.89 |
| Saved | 243.36 → 167.88 | 377.70 → 268.04 |
| Slip | 245.89 → 169.52 | 380.41 → 268.11 |

The fixture contains, respectively, 600/1,200 players, 645/1,289 Events,
6,000/12,000 props, 17,055/34,107 offers, 13,272/26,568 game logs,
1,200/2,400 snapshots and 514/1,028 fatigue rows. Both sizes have two users,
21 saved rows, two slips and 11 slip items, including the other owner's rows;
interactions and rankings are empty in the scaling fixture. Personalized Feed
has separate real-authentication regression coverage.

## Stage profiling and remaining work

The separate instrumented Discover request takes 5,474/11,112 ms with tracing
and wrappers, with 31.13/61.68 MiB peaks. These timings are not acceptance latency.
Stages overlap. Call-net deltas below are cumulative retained allocation changes,
not gross allocations or independent peaks; **do not sum them**.

| Discover stage | Calls 6k / 12k | Instrumented ms 6k / 12k | Call-net MiB 6k / 12k |
| --- | ---: | ---: | ---: |
| Inventory materialization | 1 / 1 | 1,488 / 3,121 | 13.140 / 26.264 |
| Eligibility | 5,002 / 10,003 | 351 / 707 | 0.420 / 0.837 |
| Historical-log loading | 1 / 1 | 558 / 947 | 11.958 / 24.010 |
| Exact-line trends, including page serialization | 3,392 / 6,768 | 1,154 / 2,357 | 16.006 / 31.562 |
| Compact preparation summaries | 4,952 / 9,905 | 4 / 8 | 0.429 / 0.853 |
| Reconstruct scorer windows | 4,952 / 9,905 | 6 / 13 | 0.556 / 1.115 |
| Original scorer | 4,952 / 9,905 | 220 / 452 | 3.004 / 6.018 |
| Full page serialization | 20 / 20 | 31 / 35 | 0.192 / 0.192 |
| Aggregate refresh evaluation | 1 / 1 | 484 / 1,004 | approximately 0 / 0 |

Separate cProfile requests take 2.57/5.05 seconds, also slower than uninstrumented
latency. Full historical validation runs 1,220/2,420 times. At 6k the baseline
ran it 9,515 times; the first bounded-cache implementation still ran it 4,445
times because of interleaved players. Grouped past-date preparation removed that
thrashing without reordering price/scoring visits or dropping candidates.

Inventory decoding, UUID/type conversion, complete historical loading, exact-line
window calculations and repeated shared offer/freshness evaluation remain the
main Python work. At 12k, materialized inventory and historical logs alone retain
approximately 50 MiB during the instrumented request. Further safe improvements
need narrower equivalent SQL projections or a more explicit global ordering and
identity contract, with a fresh original-behavior oracle. This milestone does not
claim constant time or constant memory.

Target status: 6k Discover first/deep meets all targets with little median margin;
12k Discover meets memory but misses median and p95 latency. Feed and Games miss
500 ms median at both sizes and 1 s p95 at 12k. Saved/Slip query targets and small
Event/Research p95 targets pass at both sizes. Higher RSS than traced memory is
explicitly observed. No target miss was addressed by changing research semantics.

## Five-client load observations

A separate process runs five concurrent clients against the 12k fixture for
300 seconds, rotating the nine key public endpoint shapes. Completed requests
are allowed to drain: actual elapsed time is **302.922 seconds**, **370 requests**,
**zero failures**, zero pool timeouts and unchanged fingerprints for all 13 tables.
No tracemalloc or all-candidate oracle retention runs during this load interval.
The test has synthetic fixed-clock data and in-process ASGI clients, not a
production HTTP server/network/ingress workload.

The test deliberately uses QueuePool size 5, overflow 0 and timeout 30 seconds.
Application defaults allow overflow 10 and use a 5-second timeout; these results
do not certify that deployment configuration. Peak checked-out connections are
five, ending at zero. Pool acquisition median/p95/max are **0.0058 / 0.0132 /
31.072 ms**. This instruments `_do_get` elapsed time, including connection
creation; it is not a pure queue-wait metric. There is no evidence that pool
acquisition dominates the observed latency. CPU/Python heap processing and
concurrent inventory graphs remain the major capacity concern. Production
overload responses, request queues and ingress backpressure are not certified.

| Five-client 12k endpoint | p95 ms |
| --- | ---: |
| Feed first / deep | 5,916 / 5,994 |
| Discover first / deep | 10,583 / 11,340 |
| Games | 5,616 |
| Event Detail | 864 |
| Player Research | 289 |
| Saved | 84.6 |
| Slip | 68.3 |

RSS starts at **200.70 MiB** and ends at **652.43 MiB**; five-second samples span
**272.67–716.01 MiB**. Median RSS during seconds 30–60 is **366.58 MiB**, compared
with **641.69 MiB** during seconds 270–300: **+275.11 MiB**. This is material drift,
not a stable-memory result. Concurrent live inventories, native buffers and
allocator retention can contribute; the run does not establish their relative
contributions or prove/disprove a leak. Longer soak tests and allocation/native
heap investigation are required before a capacity or leak-free claim. Single-
request traced-memory success must not be interpreted as concurrent RSS safety.

Sustained load checks statuses and table preservation. A separate bounded
five-client exact-response oracle round completed afterward: **45/45 complete
responses match the preserved baseline**, all statuses are 200, provider HTTP
attempts are zero, and all 13 table fingerprints remain unchanged within the run.
This correctness round does not distort the five-minute latency/RSS observations.
Each sustained-load client completed 74 requests. Across all clients, median/p95/
maximum latency is 4,730.28 / 10,470.28 / 11,974.47 ms; the mixed-endpoint aggregate
is not a substitute for the endpoint results above.

## Query plans and indexing decisions

`EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` runs against captured, parameter-bound
SELECTs in the disposable fixture. The inventory SELECT deliberately remains
identical before and after; the main savings are Python materialization and
repeated computation, rather than fewer scanned candidate rows. PostgreSQL may
choose sequential scans for these broad, mostly eligible synthetic inventories.
The fixture is not a representative production selectivity distribution.

Representative final plans (warm shared buffers, shared reads zero):

| Query | Rows returned 6k / 12k | PostgreSQL execution ms 6k / 12k | Shared buffer hits 6k / 12k | Work/index evidence |
| --- | ---: | ---: | ---: | --- |
| Discover joined inventory | 15,006 / 30,009 | 23.760 / 61.089 | 32,437 / 64,853 | Offer scans inspect 17,055 / 34,107 rows per scan; eligibility scan removes 1,890 / 3,786. PK lookups and another complete offer scan join output. |
| Discover historical logs | 13,272 / 26,568 | 3.647 / 9.801 | 275 / 549 | Complete sequential log scan, required across all candidate players. |
| Games legacy collision projection | 1,500 / 3,000 | 0.739 / 1.221 | 161 / 320 | `ix_props_event_id` bitmap index/heap scan for NULL Event IDs plus all 600 / 1,200 players. |
| Games complete Event evidence | 645 / 1,289 | 0.051 / 0.086 | 12 / 23 | Complete Event scan, including empty Events. |
| Games joined inventory | 15,006 / 30,009 | 22.471 / 60.580 | 32,437 / 64,853 | Same broad offer/prop plan as inventory. |

The corresponding original Discover inventory plans take 21.873/91.041 ms and
original log plans 4.307/16.790 ms, with the same rows and buffers. That timing
variation is not an SQL optimization claim. Original Games identity inventory
returns all 6,000/12,000 props in 2.373/6.021 ms; projection reduces transferred
rows without excluding any unlinked collision evidence. Plan row visits include
loop multiplicities and overlapping nested/index/heap visits; they cannot be
added as unique scanned records. Complete actual plans, SQL/binds and node-level
rows/removed/loops remain in each ignored JSON report.

The 12k Event plan uses `ix_props_event_id` to return seven props (21 joined
rows); narrow log lookup uses `ix_player_game_logs_player_id`. Research's player
prop lookup scans 12,000 props, rejects 11,990 and returns ten props/21 joined
rows, taking 24.195 ms in this plan. Its 24 game logs use the player index and
snapshots use `ix_prop_book_snapshots_prop_book_time`. Saved/Slip batches use
`props_pkey` and `ix_prop_books_prop_id`; owner/item tables remain tiny sequential
scans. These plans support future narrow indexes, not candidate caps.

The existing player game-log index serves narrow research/page lookups; the
existing snapshot composite index serves exact-prop history. Broad Discover
needs the historical rows for all candidate players, including prior-season
recent windows. A current-season-only database filter would change its results.
There is no stored season column on game logs.

Props have an Event index, but no dedicated player index. A future additive
`props(player_id)` index is a reasonable narrow-research experiment on a larger
production-shaped fixture. Saved owner, open-slip owner/status, slip-item parent
and interaction owner indexes also deserve selective multi-user measurements.
These fixtures contain only two users and do not establish a useful benefit
for those indexes. Offer parent/uniqueness indexes already exist; adding only a
freshness index would not remove the global ranking work or permit discarding
expired collision evidence. No new index is essential to the measured Python
improvements, so no Alembic revision was introduced or applied.

## Reproduction and evidence

From `backend`, set `PROPPULSE_TEST_POSTGRES_URL` to an explicitly owned loopback
PostgreSQL 15 database named with the `proppulse_test_` prefix. Never reuse the
application database. The benchmark rejects unsupported destinations and
connection overrides. It creates and removes a random schema, blocks provider
HTTP, installs synthetic configuration before database imports and checks full
table fingerprints after all requests.

```powershell
.\venv\Scripts\python.exe tests/benchmark_inventory.py --label baseline --size 6000 --baseline-source --requests 30 --oracle-pages
.\venv\Scripts\python.exe tests/benchmark_inventory.py --label optimized --size 6000 --requests 30 --oracle-pages --compare baseline --stage-diagnostics
# Repeat both commands with --size 12000.
.\venv\Scripts\python.exe tests/benchmark_inventory.py --label smoke --size 12000 --requests 1 --no-trace --concurrency-seconds 300
# Preserve smoke-12000.json as concurrency-12000.json before the next command.
.\venv\Scripts\python.exe tests/benchmark_inventory.py --label smoke --size 12000 --requests 1 --no-trace --concurrent-oracle-once
```

The baseline switch expects the ignored, preserved original source at
`data/odds_runs/m3i/baseline_source/app`. On a fresh checkout, reconstruct that
directory from the recorded starting commit before benchmarking. Do not capture
the optimized tree as a new baseline. Focused goldens included with this change remain available
independently of the large ignored performance evidence.

Reports are under ignored `backend/data/odds_runs/m3i/`: `baseline-6000.json`,
`baseline-12000.json`, `optimized-6000.json`, `optimized-12000.json`,
`concurrency-12000.json`, and `concurrent-oracle-12000.json` (also retained as
`smoke-12000.json`). The compact extraction is `final-benchmark-summary.md`.
Original pre-grouping experimental reports are retained as
`optimized-pre-group-6000.json` and `optimized-pre-group-12000.json`; they are not
the final acceptance measurements. Frontend logs and supervised browser configs
are in its ignored `frontend/` directory; the full backend log is
`backend-final.log`. Generated evidence, database files, logs and build output
must remain untracked.

## Changed files

- `backend/app/routers/props.py`: inventory loading, page-only Discover
  serialization, grouped historical preparation and cheaper Games freshness.
- `backend/app/routers/users.py`: scoped Saved/Slip relationship and fatigue batches.
- `backend/app/services/inventory_read_service.py`: validated tuple-backed
  read-only prop/offer/player/Event/log subjects, with ORM fallbacks.
- `backend/app/services/discovery_service.py`: lossless historical scoring inputs.
- `backend/app/services/game_identity_service.py`: complete unlinked identity projection.
- `backend/app/services/offer_service.py`: shared compact availability/price state.
- `backend/app/services/ranking_service.py`: reused fatigue and prepared affinities.
- `backend/app/services/trend_service.py`: shared unchanged line-window formulas
  and request-local validated-history reuse.
- `backend/tests/benchmark_inventory.py`: guarded PostgreSQL timing, memory,
  oracle, plans, fingerprint and concurrency harness.
- `backend/tests/test_inventory_equivalence.py`, `test_inventory_read.py`,
  `test_hydration_batch.py`, `test_offer_policy_equivalence.py`, and
  `test_discover_equivalence.py`: focused correctness and batching regressions.
- `backend/tests/fixtures/offer_policy_pre_3i.json` and `discover_pre_3i.json`:
  frozen original-source goldens; no optimized-output regeneration.
- `backend/tests/test_offer_availability.py` and `test_slip_sides.py`: existing
  mocks aligned with batched reads and stored selection UUIDs.
- `docs/milestone-3i-inventory-performance.md`: this evidence and limitations.

Frontend source, dependencies, deployment settings and database schemas are unchanged.

## Review readiness and follow-up

Milestone 3I is ready for a Git checkpoint review with the measured capacity
limitations explicitly accepted. The source changes preserve the original
research/odds/identity contracts across 74 sequential and 45 concurrent exact
response comparisons. Subsequent sports-research work can build on those frozen
contracts; intentional future behavior changes should have separately reviewed
tests rather than silently regenerating these goldens.

The remaining performance work is global inventory/history processing, the 12k
latency misses, and concurrent RSS growth. Investigate native/allocator retention
and longer soak behavior before any production capacity claim. Narrow indexes
remain proposed experiments only. Existing 3G/3H security and release gates remain.

After resuming from the usage interruption, existing logs and final artifacts were
verified rather than rerunning passed benchmarks or the full suites. Application
source remained unchanged; only documentation was completed. No commit, push or
deployment was performed, and HEAD remains the recorded starting commit.

Cleanup verified the exact owned container ID, milestone label, empty mount list
and tmpfs-only PostgreSQL storage before removing that container. No benchmark
Python processes or browser-test listeners on ports 8000/3199 remained. Generated
evidence is preserved in ignored files; the development database was not touched.

## Final engineering review and authorized local checkpoint — October 17, 2026

The checkpoint review began on `master` at the expected
`a643efab49be086ff8020daadb9c25f845a15027`, with exactly the 19 Phase 3I files
listed above. The complete implementation diff, new loader, benchmark harness,
regressions, original-source golden fixtures and relevant 3D/3G/3H contracts were
reviewed. Independent review found no confirmed actionable defect. No application
source or golden fixture was changed during this checkpoint; only this report was
extended with fresh verification and the authorized checkpoint record.

Review confirmed that all eligible Discover candidates are scored before the
original stable sort and pagination; weights, denominators, explanations and
recent/current-season windows are unchanged. Request-local cache keys and
time-sensitive bypasses preserve historical subjects. Tuple materialization
retains SQL, identity deduplication and encounter order, with ORM fallback for
unsupported layouts or pending session changes. Complete Event/unlinked evidence
preserves legacy collision rejection. Saved/Slip ownership and exact selections,
including case-equivalent sportsbook ordering, retain their original behavior.
No application writes, new schema or operational migration are required.

Fresh checkpoint verification supersedes implementation-stage test timings:

| Check | Final checkpoint result |
| --- | --- |
| Full backend with blocked provider HTTP | **573 passed**, zero failures/errors/skips, **101.770 seconds** |
| Genuine PostgreSQL scenarios included above | **161**, PostgreSQL **15.18** |
| Backend external HTTP attempts | **0** |
| Frontend unit tests | **59 passed**, zero failures/skips/cancellations |
| TypeScript / production frontend build | Both passed; ten static pages |
| Mocked Chrome desktop/mobile | **36 passed**, 15.2 seconds |
| Real-backend Chrome desktop/mobile | **24 passed**, 17.0 seconds |
| Real-backend Edge desktop/mobile | **24 passed**, 17.4 seconds |
| Browser total | **84 passed**, all processes exit 0 |
| Browser preservation | All **13 tables / 80 fixture rows** unchanged; provider HTTP attempts **0** |
| Python compilation | Passed for app, scripts, tests and Alembic sources |

Fresh verification used only `proppulse-test-m3i-checkpoint-20261017`, ID
`b6f2e5b1e05eef0c173243a688d3f868982194ac09f1ac22ed4f09baa5f5ae73`, with two CPUs,
1 GiB memory, 128 PIDs and tmpfs-only PostgreSQL storage, bound to loopback port
59624. Backend random schemas used `proppulse_test_m3i_checkpoint`; browsers used
the separate newly created `proppulse_test_m3i_checkpoint_browser` database.
Refresh stayed disabled and provider HTTP was blocked. Development containers
remained stopped. New logs remain ignored under
`backend/data/odds_runs/m3i/checkpoint-20261017/`.

An independent artifact audit reimplemented strict JSON type/key/value/list-order
comparison and confirmed **74/74 stored sequential oracles** match with zero
exclusions. All 39 current application file hashes match both final statistical
reports and both concurrent reports; all 38 preserved original application files
match starting-commit blobs. Original-source provenance was checked for the 30
Discover and 51 offer golden cases. All four statistical reports retain 30
observations for each of nine endpoint shapes and unchanged within-run fingerprints
for all 13 tables. The concurrent artifact records **45 successful strict
comparisons**, HTTP 200, no excluded fields and zero provider attempts; successful
response bodies are not duplicated there, so this audit verifies the recorded
comparator execution/results rather than replaying those unretained bodies.
The five-client report confirms 370 requests, zero failures and +275.11 MiB warmed-
to-late RSS drift. The ignored audit is `checkpoint-20261017/evidence-audit.json`.
No performance or sustained-concurrency benchmark was repeated because application
source is unchanged and the preserved evidence verifies successfully.

After verification, the disposable backend database had zero leftover random test
schemas and zero advisory locks. The exact checkpoint container was removed after
checking its ID, milestone label, empty mount list and tmpfs configuration.
Development PostgreSQL/backend/Redis containers remain stopped. Browser-owned
processes and listeners were removed. No development database was accessed.

The user authorized exactly one local commit:
`perf: optimize discover inventory and saved slip hydration`.
Its scope is the 19 reviewed source, test, fixture and documentation files.
Only the two intentional original-source JSON goldens belong in Git. Raw reports,
logs, retained baseline source, dumps/backups, environment files, browser artifacts,
temporary configurations, dependencies, caches and build output remain excluded.
No push, history rewrite, deployment or next milestone is part of this checkpoint.
