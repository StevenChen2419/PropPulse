# Milestone 4A: Rest & Workload research

Follow-up: [verified participation enhancement and combined local checkpoint](milestone-4a-verified-participation-enhancement.md).
Verification counts and unavailable PostgreSQL statements below describe the
original implementation stage; the follow-up records subsequent PostgreSQL
verification and the combined engineering review. Earlier no-commit statements
are historical, superseded only by the user's explicit local-checkpoint request.

Implementation starts at `a360b4745492048c11b107cdf00f38ff9499824a`.
Parent/application AGENTS instructions and the existing history, Event schema,
ingestion, research-selection, frontend-navigation and inventory reports were
reviewed alongside current code. This phase adds descriptive NBA research;
Discover scoring, odds eligibility, historical hit-rate calculations and stored
user selections retain their existing contracts.

## Pre-implementation provenance and coverage audit

This audit used source code and checked-in historical reports only. No current
development database connection or retained provider payload inspection was
performed. Current retained-data counts and minute coverage are **not measured**.
The user requires a separately approved read-only process for that inspection;
implementation and fixture validation do not depend on accessing development data.

| Input | Evidence and limits |
| --- | --- |
| NBA appearances | `PlayerGameLog`, source `espn_nba`, external game ID, UTC game date, opponent, optional side and JSON statistics. Provider attribution is stored provenance, not independent reauthentication. Logs have no Event FK or historical player-team identity. |
| Minutes | ESPN ingestion maps `minutes`, including duration strings, to numeric minutes and skips basketball rows with no positive minutes. Older retained rows may lack minutes; no backfill is performed. Other basketball statistics include points, rebounds, assists, blocks, steals, threes and derived PRA. Possessions and validated usage rates are unavailable. |
| Completion/competition | Ingestion excludes preseason sections. Legacy rows lack universal final status and regular/postseason classification. Past-date statistics are a completion proxy; explicit unfinished/preseason markers must be excluded. |
| Event schedule | Verified provider namespace, opaque ID, participants and UTC scheduled start. No universal final/cancellation status, completeness watermark or complete team schedule. Event presence verifies a stored schedule, not player participation or all upcoming games. |
| Legacy Prop schedule | Mutable/inferred player-team, opponent, side and game time; may conflict with authoritative Events. Never use it to verify a schedule or manufacture Event links. |
| Stored fatigue | `FatigueScore` can be written by heuristics, legacy demos or experimental ML and has no method/version provenance. Its values cannot be treated as observed fatigue or independently validated predictions. |
| Existing workload screening | `risk_intelligence_service.py` uses ordinal hand-set sport thresholds and explicitly experimental labels; it is separate from the new descriptive research. |
| Experimental ML | `ml/generate_game_logs.py` generates schedules, statistics, stable lines and imposed fatigue penalties. `train.py` uses temporal splitting but also hand-maps anchor predictions to 0.28/0.68 using the full dataset. These are experimental outputs, not out-of-sample calibration or evidence of betting edge. No model is loaded, trained or applied in this phase. |

Historical documentation reports 22 Tatum and 81 Cunningham NBA points logs in
ending-year season 2026, and a later supplied baseline with one Event, ten linked
props and 6,054 unlinked props. These are dated reports, **not current counts or
proof of minute/schedule coverage**. They motivate missing-data handling rather
than a completeness claim. Synthetic arithmetic fixtures are identified as tests
and never inserted into development data.

## Calculation policy

`rest_workload_service.py` is a pure, read-only builder with an injectable UTC
evaluation clock. It does not invoke the fatigue scorer, model inference,
ingestion, offer calculations or Discover scorer. No migration or dependency is
needed. Other sports return `unsupported_sport` rather than NBA thresholds.

The reference instant is the selected authoritative Event start; without one it
is evaluation time. A legacy Prop timestamp never establishes verified schedule
context. Future Event references carry an explicit warning about potentially
missing intervening games. Historical Event references exclude later logs.

Eligibility requires NBA, the selected player, `espn_nba`, a non-synthetic
external identity, a valid UTC date strictly before evaluation and reference,
no explicit unfinished/preseason marker, and at least one recognized numeric
statistic. Unconfirmed games on the current UTC day are excluded. Zero minutes
means did-not-play; negative/nonfinite/malformed minutes are unavailable, not
zero. A recorded points observation can still support an appearance when minutes
are missing. Source labels and prior-date completion remain limited evidence.

Exact duplicates count once. Conflicting eligible records for one external ID or
one Eastern appearance date are excluded rather than choosing arbitrary values;
NBA does not use baseball-style doubleheaders. Rejected source/player/sport rows
cannot poison eligible duplicate groups. Every stored row reconciles to one
eligible appearance or one exclusion reason. Missing minute counts are tracked
separately from excluded appearance counts.

| Indicator | Formula and interpretation |
| --- | --- |
| Days since last recorded game | Eastern calendar date of reference minus Eastern date of latest eligible appearance. Not a count of full rest days or verified absence of intervening games. |
| Back-to-back | Date difference exactly 1; no appearance yields null. |
| Rest category | 1 = back-to-back, 2 = short rest, 3+ = extended rest; 0/unknown has no category. These thresholds are descriptive heuristics. |
| Recorded games in 7/14 days | Count eligible appearances in the half-open UTC interval `[reference - N days, reference)`. Lower-bound recorded counts; not a complete team schedule. |
| Density | Recorded 7-day count divided by 7, in games/day. |
| L5/L10 minutes | Select newest 5/10 eligible appearances across seasons, then average valid minutes in that window. Missing minutes do not cause older games to be pulled into the window. |
| Season minutes | Mean valid minutes in eligible appearances of the selected reference's ESPN ending-year season (October through September). No previous-season substitution. |
| Recent vs season | L5 average minus season average, in minutes/game; null if either average is unavailable. |
| Minutes trend | Last five average minus preceding five average; requires ten valid minute observations in the ten selected appearances. |
| Recent variability | Population standard deviation of valid L10 minutes; requires at least two observations. |
| Historical rest splits | Group each appearance by the Eastern-date gap to its preceding retained appearance in the same season. Omit first appearance and season transitions. Report separate valid-minute and points denominators, means and appearance date range. These are descriptive averages, not betting hit rates. |

Minute values above 100 are treated as malformed and excluded from minute
aggregates, never clipped. Averages and differences are rounded to two decimals;
density to three. Empty averages and one-observation variability are null.
L5/L10 insufficient-sample flags compare valid minutes with 5/10; season samples
below 5 are flagged. Small samples remain visible rather than suppressed, and
the UI flags rest-split samples below five. Season lists, appearance counts,
minute denominators and date ranges accompany the windows. No possession-based
usage rate is inferred from minutes, points or attempts.

## API contract

The existing `GET /players/{player_id}/research?prop_id=<uuid>` gains only
`rest_workload`. Existing exact Prop selection, unavailable-primary prices,
history, splits, available offers and error behavior remain independent. Even
the no-current-props response includes player-level workload at evaluation time.

A focused endpoint supports explicit context without requiring an active market:

```text
GET /players/{player_id}/rest-workload
GET /players/{player_id}/rest-workload?prop_id=<uuid>
GET /players/{player_id}/rest-workload?event_id=<uuid>
GET /players/{player_id}/rest-workload?prop_id=<uuid>&event_id=<uuid>
```

Unknown player/Prop/Event returns 404, malformed optional UUID returns 422,
wrong-player Prop or sport mismatch returns 400, and conflicting Prop/Event
selectors return 409. Event-only context requires an existing authoritative
player-Prop linkage; current Player.team is not used as proof of participation.
The focused endpoint also validates its player UUID. A wrong-sport linked Event
returns 400 there; the additive research builder instead uses evaluation time
and an explicit conflict note, preserving existing history and offer responses.
Inactive/expired Prop context remains addressable and never selects an alternate
Prop or sportsbook. `RestWorkloadOut` defines the focused endpoint's response.

The response contains:

- `status`: `available`, `no_history`, or `unsupported_sport`; `player_id`,
  `sport`, `classification`, `evaluated_at`.
- `reference`: UTC `at`, source `event`/`as_of`, nullable exact `prop_id` and
  `event_id`.
- `coverage`: stored and eligible counts, mutually exclusive `excluded_counts`,
  UTC appearance date range, sources, `schedule_complete: false`, and limitations.
- `rest`: nullable day gap, back-to-back, category, rolling counts, density,
  derived classification and formula explanation.
- `workload`: L5, L10 and season windows (valid minute `games`, `observed_games`,
  average, range, seasons, insufficient flag), differences, variability, missing
  minute count and explanation.
- `rest_splits`: category, total appearances, valid-minute and points counts,
  averages and date range.
- `interpretation`: heuristic classification, descriptive label, limitations,
  `experimental_model_used: false`.

UTC instants serialize with offsets; naive stored datetimes mean UTC. The client
displays dates in Eastern time. No response claims complete schedule coverage,
physiological fatigue, injury risk, validated probabilities or expected value.

## Frontend

The player research page presents Rest & Workload independently of the history
chart and primary offer availability. Compact rest indicators, minute windows,
baseline/trend/variability comparisons and rest-split cards share the existing
responsive design. Nulls say unavailable/unknown. Visible warnings explain
incomplete schedules and small samples; an accessible native disclosure exposes
coverage, exclusions, source labels and calculation details. The section follows
the selected exact Prop UUID and suppresses mismatched context during navigation.

The previous prominent fatigue Risk badge/bar/report on this page is replaced
with a collapsed experimental legacy-estimate disclosure. Legacy method/training
provenance is unknown; its score is not merged with observed research. Shared
Discover ranking, other surfaces, layout server component, saved/slip stores,
hydration and persistence are unchanged.

## Verification

Docker engine availability was checked using the explicit local named pipe, including
outside the sandbox; it is unavailable. No application database was used as a
substitute. Backend checks use `tests/run_no_provider_http.py`, which blocks HTTP
transports while allowing isolated ASGI requests. Browser fixtures intercept API
requests and reject unexpected origins. No provider ingestion or app lifespan
against development configuration is used.

Arithmetic fixtures include newest-to-oldest minutes `2,4,...,20`: L5 = 6,
L10 = 11, preceding-five mean = 16, trend = -10 and population SD = 5.74.
Appearances 1,6,7,8,13,14,15 days before the reference produce 7-day count 3,
14-day count 6 and density 0.429. A mixed-season 40/10 minute pair produces a
25-minute recent mean and a 40-minute current-season mean, with no cross-season
rest-split bridge. A missing minute in the newest five retains its slot and
leaves a four-observation minute denominator. These fixtures validate arithmetic,
not real-world completeness or model accuracy.

New backend checks cover rest categories, midnight/offset boundaries, rolling
window inclusivity, missing/invalid/future/same-day logs, season separation,
duplicates/conflicts, wrong-player/source/sport, duration minutes, fixed window
slots, sample sizes, split denominators, legacy/Event disagreements and no-model
behavior. Ten shared API scenarios run on isolated SQLite and are also defined
for guarded disposable PostgreSQL schemas. They cover exact expired Prop UUIDs,
Event linkage/errors, player-only research, no writes, and independent history.
Frontend tests cover observations/heuristics, unknowns, Eastern dates and older
responses; browser regressions cover unavailable odds plus missing history,
older API responses, no-current-props research and experimental legacy labels.

| Final check | Result |
| --- | --- |
| Backend: `.\venv\Scripts\python.exe tests/run_no_provider_http.py` | 621 discovered; 450 passed, 171 PostgreSQL skipped; zero external HTTP transport attempts. |
| Focused workload backend | 48 discovered; 38 passed (28 arithmetic, 10 SQLite API), 10 PostgreSQL skipped. Included in the full-suite total. |
| Frontend: `npm test` | 63 passed, zero failures/skips. |
| Frontend: `npx tsc --noEmit` | Passed. |
| Normal `npm run build` | Blocked by existing `next/font/google` Inter download: network EACCES. |
| Font-mocked production build | Passed, ten pages; temporary `NEXT_FONT_GOOGLE_MOCKED_RESPONSES` uses local Arial CSS. No production font/config change. This does not verify the ordinary font download. |
| Desktop Playwright | 22/22 passed, exit 0; includes four new workload/compatibility scenarios. |
| Mobile Playwright | 22/22 passed, exit 0, 390x844 touch viewport; same scenarios and workload overflow assertion. |
| Python compilation | `compileall -q backend/app backend/scripts backend/tests backend/ml` passed; compiles without executing scripts. |
| Whitespace | `git --git-dir=.git --work-tree=. diff --check` passed. |

Real PostgreSQL tests cannot execute on this host: the local Docker named pipe
does not exist and no disposable URL is supplied. The 171 skips include the ten
new scenarios. PostgreSQL-backed real-API browser integration was consequently
not run; SQLite and route-mocked browser checks do not substitute for that proof.
No separate lint check was run because the current package has no lint script.
The browser runs used the font-mocked build, so exact Inter typography is not
verified. The existing Windows managed-server teardown stalled after desktop
assertions; only the runner-owned Next process was stopped, then the runner
completed with exit 0. Mobile used a temporary configuration without managed
webServer and a separately owned Next server. That server was stopped and port
3199 was confirmed free. No checked-in Playwright configuration was changed.
The browser totals are separate executions of 22 scenarios, not 44 distinct
behavioral cases. Independent review found two edge defects (malformed-only
minutes and wrong-sport Prop Event validation); both were fixed and covered.

Code is ready for review with the PostgreSQL/real-API browser and ordinary-font
build verification gaps above. It is not represented as fully verified for
release. Current-data coverage inspection remains a separately approved read-only
task; no new research phase is started.

## Changed files

- `backend/app/services/rest_workload_service.py`
- `backend/app/routers/players.py`
- `backend/app/schemas.py`
- `backend/tests/test_rest_workload.py`
- `backend/tests/test_rest_workload_api.py`
- `frontend/src/components/RestWorkloadSection.tsx`
- `frontend/src/app/player/[id]/page.tsx`
- `frontend/src/lib/types.ts`
- `frontend/tests/fixtures/rest-workload.cjs`
- `frontend/tests/rest-workload.test.cjs`
- `frontend/e2e/navigation.spec.cjs`
- `docs/milestone-4a-rest-workload-research.md`

## Limitations and next research opportunities

Current retained-data coverage remains unmeasured. Recorded gaps may include
missed appearances, injuries, offseasons or missing ingestion. Future-event
comparisons can omit games between evaluation and that Event. Date-only or
imprecise provider timestamps can shift Eastern calendar interpretation. Current
season averages describe loaded observations, not necessarily a full season.
Minute missingness can bias means; split groups can be small and confounded by
opponent, role and competition. Historical regular/postseason separation and
provider final status are unavailable for many legacy records.

Future separately scoped work could add schedule-completeness evidence,
provider-final and historical team metadata, minute-coverage auditing, regular/
postseason separation, and richer observed workload fields. Predictive research
would need independent temporal out-of-sample evaluation and calibration before
any accuracy or betting-probability claim. No Phase 4B implementation, model
training, provider call, Event backfill, development mutation, refresh enablement,
deployment, commit or push is part of this milestone.
