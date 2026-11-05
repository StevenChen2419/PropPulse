# Milestone 4A enhancement: verified rest and participation

## Scope and baseline

This extends, rather than replaces, the original
[4A implementation report](milestone-4a-rest-workload-research.md).
At the start of this enhancement HEAD was still
`a360b4745492048c11b107cdf00f38ff9499824a`, with the twelve original 4A files
modified/untracked. Phase 4A was **uncommitted**. Those changes were retained.
Parent/application AGENTS instructions, current code, migration/readiness history,
ESPN paths, research endpoints and regression tests were inspected.

No development database or retained provider payload was accessed. This is a
source-capability audit; it does not measure current NBA record counts. No live
ESPN/NBA/odds HTTP, ingestion, backfill or operational migration is authorized or
performed. Synthetic fixtures are confined to tests/disposable databases.

## Existing data versus required evidence

| Evidence | Existing implementation | Consequence |
| --- | --- | --- |
| Provider game identity | `PlayerGameLog.external_game_id`, source `espn_nba`; Event identity separately namespaced by provider/sport | IDs exist, but log-to-Event cross-provider correspondence is not established. |
| Final status | Game-log ingestion does not persist provider final/completion status; optional JSON completion markers are consumed by legacy research | Past dates and statistics cannot prove provider final status for the new measures. |
| Game dates | ESPN game-log `events[eventId].gameDate` is retained; Event stores scheduled UTC start | A scheduled past start is not an actual final game. Verified evidence needs actual game time/date plus explicit status. |
| Team identity | Game logs store opponent label and optional home flag. Current Player.team is mutable. Event stores participant labels, without ESPN team IDs | Cannot assign historical player membership or the selected player's provider team from current labels. |
| Provider athlete identity | Roster/name matching uses ESPN athlete ID transiently; it is not retained as a durable verified crosswalk | Persistent unambiguous player identity is required for game-specific participation. |
| Participation | Positive-minute game-log statistics are kept; basketball rows with missing/nonpositive minutes are skipped | Retained rows cover some appearances; absence cannot establish DNP or inactive. Zero points is not evidence of DNP. |
| DNP / inactive | No durable classifications; ingestion skips rather than retains zero-minute rows | Cannot count missed games from missing logs. |
| Box-score completeness | No stored summary/box-score coverage or completeness watermark | Missing athlete rows remain unknown even when a team game is known. |
| Historical membership | No dated provider player-team intervals | Trades cannot be reconstructed from current team. |
| Schedule completeness | Event is odds inventory; there is no complete NBA schedule/final-status coverage record | Team previous-game and negative back-to-back claims cannot be verified from Events alone. |

`fetch_player_game_logs.py` currently implements athlete discovery and athlete
game-log requests; `team_directory.py` implements team/roster discovery. Source
inspection found no implemented NBA scoreboard, summary or box-score parser with
retained final/DNP/inactive semantics. No upstream fields or enum values for these
unimplemented paths were guessed or presented as verified ESPN contracts.

## Deliberate implementation boundary

The existing calculation service gains typed **internal normalized evidence**
inputs and an additive verified result. These local records are a calculation
contract, not an ESPN payload schema. The current API does not have a trustworthy
repository adapter for them and therefore returns explicit unknown verified
metrics. It continues to show legacy recorded-appearance and minute research.
Legacy log markers, numeric points and current team labels are not silently
promoted to final game, participation or membership proof.

The user explicitly allows completing the locally testable portion when an
upstream contract is unverified. Accordingly, no speculative database tables,
duplicate services, operational ingestion command, new Alembic revision or
readiness requirement is introduced. Existing revision `20261014_02` and Event
links remain unchanged. New durable evidence will be necessary for trustworthy
live coverage; the minimal proposal below is **not an implemented migration**.

## Proposed durable schema and connector

After separately authorized contract validation, use additive evidence records
outside historical statistical logs so DNP rows cannot alter legacy hit-rate or
ranking denominators:

- Provider games: unique `(provider, sport_key, provider_game_id)`, home/away
  provider team IDs, scheduled start, nullable actual game start/date, normalized
  status, evidence source and provider observation time. Store postponed/cancelled
  states explicitly; never infer final from time. Do not create/link odds Events.
- Participation: unique `(provider, sport_key, provider_game_id,
  provider_player_id)`, exact local player UUID crosswalk, game-specific provider
  team ID, state `appeared`/`dnp`/`inactive`/`unknown`, evidence source and observation
  time, plus box-score coverage state. Absence in a box score stays unknown unless
  the validated contract explicitly establishes a classified nonappearance.
- Membership evidence: provider player/team IDs, local player UUID, effective
  half-open interval, evidence source and observation time. Keep historical
  intervals and conflicting evidence; no rewrite from the current roster.
- Coverage evidence: provider/sport/team scope, inspected time interval,
  schedule/box-score completeness, observation time, source and reconciliation
  outcome. A successful HTTP status or a list of known games cannot itself assert
  complete coverage. Partial/pagination failures must preserve unknowns.

Provider team IDs can remain namespaced strings in these records; a separate
team-label dimension is optional, not necessary to calculate rest. Do not place
participation evidence in `FatigueScore` or fabricate rows in PlayerGameLog.
Any future migration must be additive, separately reviewed, tested on disposable
PostgreSQL, and accompanied by the readiness-policy update if its expected
revision changes. It must not be applied to development implicitly.

The proposed optional connector must require NBA sport, explicit inclusive date
range and provider team-ID allowlist, with no default backfill. Suggested initial
bounds are 14 dates, two teams and 64 requests per invocation, concurrency one,
and a configured minimum interval between requests. Every attempt consumes budget.
Validate scoreboard/final, summary/box-score participation and team/athlete
crosswalks against authorized retained examples before writing an adapter. Retry
only idempotent reads for bounded transport failures/5xx (at most two retries),
honor bounded Retry-After for 429 and stop on authorization, identity or schema
errors. Never retry a partial parse as if it were complete coverage.

Dry-run must be the default. A future write mode should require an explicit
write flag and reviewed dry-run manifest tied to sport/date/team scope, with
transactional, idempotent upserts and conflict reports. Observation times must
not be fabricated from ingestion times; preserve valid evidence on failed refresh.
No network or writes may occur inside research requests. None of this proposed
connector was executed, and its suggested bounds are not claimed as existing
operational safeguards.

## Implemented evidence and confidence rules

`GameEvidence`, `ParticipationEvidence`, `MembershipEvidence`,
`ScheduleCoverageEvidence` and the `VerifiedRestEvidence` aggregate are immutable
internal records in the **existing** `rest_workload_service.py`. The optional
`verified_evidence` builder argument supplies already retrieved evidence; no
public endpoint accepts client-supplied assertions. The implemented namespace is
explicitly ESPN/NBA; other providers/sports are excluded rather than conflated
with bare game IDs. Each record has source and observation time. Naive internal
timestamps follow existing UTC storage semantics; external adapters must validate
timezone-aware provider timestamps before normalization.

Only explicit `completed` games strictly before reference/evaluation can support
verified metrics. A completion time, when provided, must lie between game start
and observation and before the reference. A final observation after a historical
reference without a completion time does not prove finality before that reference.
Future observations cannot support present claims. Postponed, cancelled,
unfinished and unknown-status games never count as completed just because a
scheduled start is past.

Participation is explicit `appeared`, `dnp`, `inactive` or `unknown`. Statistics
are not required by this normalized evidence contract: zero points and missing
minutes do not invalidate an explicit reliable appearance. Nor do statistics or
missing logs establish a verified appearance/nonappearance on their own. Provider
identity, team participants, player UUID, membership consistency and observation
chronology are validated. Invalid/conflicting evidence prevents exact totals and
negative back-to-back claims. Identical duplicates count once; contradictory
game identities, statuses, participation or overlapping team memberships fail
closed rather than choosing one. Inputs are scoped to this player's research.

Membership is effective on `[starts_at, ends_at)`. Team at reference comes from
that dated evidence, never Player.team. Each missed game is scoped to membership
at that game, so a trade cannot rewrite past team assignments. Game-specific
participation team evidence can support a partial observation even when a full
membership interval is unavailable. Gaps in membership withhold exact totals.

Schedule coverage is an explicit assertion that **all games and statuses** in
the half-open provider-team interval were reconciled. The calculator can merge
contiguous/overlapping complete coverage intervals; gaps remain incomplete.
Coverage cannot extend beyond evaluation or its observation time. Upcoming
references therefore cannot receive a future complete-coverage assertion.

| Metric | Definition and confidence |
| --- | --- |
| Last confirmed appearance in coverage | Latest accepted final game with explicit `appeared` participation. This is a confirmed recorded fact, but its recency is partial when later participation/schedule coverage is incomplete. |
| Player calendar gap | Eastern date(reference) minus Eastern date(last confirmed recorded appearance). |
| Player full intervening rest days | `max(player calendar gap - 1, 0)`; calendar days between those dates, not measured recovery or proof of no unobserved appearance. |
| Previous final team game in coverage | Latest accepted completed game for the provider team established at the reference. Its status is partial unless coverage from that game through reference excludes a later game. |
| Team calendar gap | Eastern date(reference) minus Eastern date(previous final team game in coverage). |
| Team full rest days | `max(team calendar gap - 1, 0)`. October 19 to October 21 gives gap 2 and full rest 1. |
| Confirmed missed games | DNP + inactive after last confirmed recorded appearance and before reference. An exact total requires continuous historical membership, complete schedules and known participation in every completed game. Otherwise null. |
| Partial missed lower bound | Explicit DNP + inactive in that bounded interval, with no missing row counted as missed. Null without a confirmed appearance baseline. Partial zero is not displayed as an exact zero. |
| Unknown participation | Known relevant final games with explicit unknown participation. Distinct from games with no trustworthy participation evidence. Counts describe known coverage, not the unobserved schedule. |
| Uncovered games | Known relevant final games without accepted participation evidence. Missing box-score rows remain uncovered. No-baseline counts are withheld in the UI rather than displayed as established zero. |
| Team back-to-back | True when accepted final team evidence includes the prior Eastern calendar date. False requires complete previous-game-to-reference coverage; incomplete negative evidence gives null. |

The outer research builder additionally requires an authoritative selected Event
before exposing verified team back-to-back. Evaluation time alone is not proof
that the team is playing a selected game that day. The pure calculator's reference
is a hypothetical selected-game reference supplied by its trusted caller.

Every non-null game result includes stable provider game/team IDs, ESPN/NBA
namespace, UTC game/observation/completion time, source, Eastern gap and full-day
count, plus `confirmed`/`partial` recency status. Appearance results additionally
include participation source and observation time. `confirmed` does not mean
physiological fatigue is measured. Offseason gaps are calendar gaps and can be
large; no season-average or travel/recovery assumption is imposed. Overtime does
not change participation classification, and minutes are not used to classify
verified DNP.

## API and frontend additions

Existing focused `/players/{id}/rest-workload` and additive research responses
retain their player, exact selected Prop and authoritative Event context and
400/404/409/422 behavior. There is no selector fallback or Event association.
The existing `rest`, `workload`, `rest_splits`, history and odds behavior remain
separate and backward compatible. The new `verified` response contains:

```text
status: confirmed | partial | unknown
reference_at, context_team_id, provenance
last_confirmed_appearance: game result | null
last_completed_team_game: game result | null
team_back_to_back: boolean | null
confirmed_missed_games: integer | null
partial_missed_games_lower_bound: integer | null
dnp_games, inactive_games, unknown_participation_games, uncovered_games
schedule_complete, evidence_counts, notes
```

`VerifiedRestOut` and TypeScript contracts carry these additions. Current API
requests have no audited retrieval adapter and return `unknown`, null confirmed
game/missed/back-to-back fields and an explicit retrieval-not-connected note.
Zero evidence counters describe received records, not zero actual missed games.
No extra database query, write, provider request or model invocation is needed.

RestWorkloadSection shows **Player rest** and **Team schedule** separately, with
Confirmed / Partial coverage / Unknown indicators. It distinguishes date gap
from full intervening days, exact totals from positive lower bounds and unknown
participation from missing box-score coverage. Dates display in Eastern time.
An accessible disclosure explains provenance and incomplete data. The existing
recorded appearance section is explicitly labeled separately; minute windows,
rest splits and the experimental legacy-fatigue disclosure remain available.
Older API responses without `verified` show unknown verified evidence while
preserving all original research. Exact Prop UUID rendering guard remains intact.

## Verification

All provider HTTP was blocked by the backend runner and real-API fixture server;
browser routing rejected unexpected origins. No normal application lifespan or
automatic refresh was used for the integration fixture.

| Check | Final result |
| --- | --- |
| Full backend, `tests/run_no_provider_http.py` | **668/668 passed**, zero skips/failures, including **174 PostgreSQL scenarios**; zero external HTTP transport attempts. |
| Verified evidence arithmetic | **41/41 passed**, included in full total. |
| Existing + enhanced rest/API scenarios | **54/54 passed** when PostgreSQL enabled; includes 13 SQLite and the same 13 PostgreSQL API scenarios, plus 28 recorded-workload tests. Included in full total. |
| Frontend `npm test` | **68/68 passed**, zero failures/skips. |
| Focused frontend research | **9/9 passed**, included in full frontend total. |
| TypeScript `npx tsc --noEmit` | Passed. |
| Route-mocked Chrome | **25 desktop + 25 mobile passed**, exit 0; final confidence-label/unknown-baseline polish additionally covered by unit and real-API browser checks. |
| Real backend + PostgreSQL browser integration | **13 desktop + 13 mobile passed**, exit 0; includes new verified-unknown/UUID/reload regression. |
| Font-mocked production build | Passed, ten pages, temporary `NEXT_FONT_GOOGLE_MOCKED_RESPONSES` mapping to local Arial; production source/config unchanged. |
| Uncached ordinary production build | Failed: `next/font` could not fetch Inter; HTTPS connect `EACCES` after three retries. A prior ordinary command reused mocked font cache and was not counted as genuine font verification. |
| Python compilation | `compileall -q backend/app backend/scripts backend/tests backend/ml` passed without executing scripts. |
| Whitespace | `git --git-dir=.git --work-tree=. diff --check` passed. |

The initial full run passed 661 tests while final tests were being integrated;
the final 668-test run supersedes that count. Existing research, Event identity,
odds freshness, ranking equivalence, ingestion-mock and saved/slip regressions
are part of the full suite. New cases cover explicit zero-point/missing-minute
appearances, DNP/inactive, multiple missed games, incomplete box scores, trades,
coverage gaps, unfinished/postponed/cancelled games, offsets/Eastern midnight,
offseason gaps, duplicate/conflicting provider IDs and participation, finality
chronology, future observations, historical references and honest API unknowns.
No model or sportsbook probability claim is tested or made.

Docker was available for this enhancement (unlike the original implementation
report). Only a newly created labeled container was used:
`proppulse-test-4av-e54e19e4e162`, ID
`728a014a1efc646a4016aa5e92f0d208fa99b6666e075dba1ceb79ef29565ec2`,
`postgres:15-alpine` from the cached image with `--pull=never`, loopback port
60505, 512 MiB limit, one CPU, 128 PIDs and tmpfs-only data. Unit/integration
fixtures used random schemas in `proppulse_test_4av`; browser fixtures used a
separate empty `proppulse_test_4av_browser`. No development DB connection was
made. Existing migrations were exercised only in disposable test schemas; no
new migration was introduced.

The actual FastAPI/browser integration used `tests/integration_server.py`, with
database-enforced read-only API role and lifespan disabled. Its preservation
check reported **unchanged fingerprints across 13 tables**, **zero provider HTTP
attempts**, and 214 measured requests. Test-only scenario writes were explicitly
confined to fixture setup/control and restored, never performed by research
requests. Saved/slip navigation and actual polling retained exact selections.

Windows managed-server teardown stalled after all browser assertions. Only its
known owned Next PID was stopped, after which Playwright exited 0 with 26 passed.
The owned Python fixture processes were identified and stopped; ports 8000/3199
were closed. The container ID, label, name, tmpfs, mounts and port were verified
before removing that container. No broad process cleanup or existing container
operation was used. A font-mocked build was restored after the uncached font
failure; mocked typography is not equivalent to genuine Inter verification.

Independent review found and corrected historical final-status timing,
nonappearance observation before final, duplicate provider-game identity,
missing appearance baseline, and team-only UI false-zero issues. Final independent
evidence-suite review found no remaining actionable defect. No standalone lint
command was run because the current package has no lint script.

## Files changed by this enhancement

- `backend/app/services/rest_workload_service.py`
- `backend/app/schemas.py`
- `backend/tests/test_verified_rest.py` (new)
- `backend/tests/test_rest_workload_api.py`
- `frontend/src/components/RestWorkloadSection.tsx`
- `frontend/src/lib/types.ts`
- `frontend/tests/fixtures/rest-workload.cjs`
- `frontend/tests/rest-workload.test.cjs`
- `frontend/e2e/navigation.spec.cjs`
- `frontend/e2e-real/integration.spec.cjs`
- `docs/milestone-4a-verified-participation-enhancement.md` (new)

These sit on top of the original uncommitted 4A files. No prior work was reset,
replaced, committed or pushed. No ranking, persistence, Event association,
production configuration or automatic refresh behavior changed.

## Remaining live-coverage requirements

The code is ready for review as the locally testable evidence-contract and
honest missing-data enhancement. **It is not a connected live verified NBA
participation feature.** Current API verified fields remain unknown until an
authorized, audited retrieval adapter and durable evidence ingestion exist.
Required next inputs are final game identities/times, persistent provider player
and team crosswalks, classified box-score participation, dated memberships and
complete interval reconciliation. Those require separately authorized upstream
contract validation, additive schema/migration review, dry-run reconciliation and
disposable PostgreSQL verification before any operational writes. No provider
verification, ingestion, automatic backfill, development migration, deployment,
commit or push was performed here. No physiological fatigue or betting accuracy
claim is supported by these descriptive calculations.

## Combined Phase 4A final review and local checkpoint

October 17, 2026. The user explicitly authorized one local commit containing both
implementations, titled `feat: add NBA rest workload and verified participation research`.
HEAD before the checkpoint remained `a360b4745492048c11b107cdf00f38ff9499824a`.
Git identified **15 distinct source, test and documentation files**, not an
estimated count. The complete tracked diff and all nine untracked files were
reviewed; the original work was preserved. Earlier no-commit statements in these
reports describe their implementation stages, not this authorized checkpoint.

Independent review confirmed recorded rest/minutes behavior, unknown verified
defaults, missing-log versus DNP separation, complete-evidence requirements for
exact totals and negative back-to-back claims, partial lower bounds, UTC/Eastern
chronology, historical memberships, exact Prop/Event identity, unchanged
odds/Discover/history/saved/slip semantics, experimental fatigue labels and the
absence of speculative migrations or a live participation adapter.

One confirmed navigation defect was corrected: valid uppercase Prop UUID query
values did not match canonical lowercase response IDs in the selected-research
and workload rendering guards. Both comparisons now ignore UUID letter case
without changing the original URL, request value or selected identity. A new
alphabetic UUID browser regression verifies selected market and workload
visibility, canonical response reference, unchanged uppercase URL/requests and
reload. No unrelated refactor or provider integration was added.

Final checkpoint executions:

| Check | Result |
| --- | --- |
| Full backend with external HTTP blocked | **668 passed**, including **174 PostgreSQL scenarios**, zero skips/failures; zero HTTP transport attempts. |
| Verified participation calculation tests | **41 passed**, included in the full total. |
| Recorded workload and research API tests | **54 passed**, including **13 PostgreSQL API scenarios**, included in the full total. |
| Frontend unit tests | **68 passed**, zero failures/skips. |
| TypeScript | Passed. |
| Mocked Chrome desktop/mobile | **26 + 26 = 52 passed**, exit 0; includes the UUID casing regression. |
| Real-backend PostgreSQL Chrome desktop/mobile | **13 + 13 = 26 passed**, exit 0; all **13 fixture tables** preserved, zero provider HTTP attempts. |
| Python compilation and Git whitespace | Passed. |
| Uncached ordinary production build | Failed fetching existing Google Inter after HTTPS `EACCES` retries; no unrelated typography change. |
| Temporary font-mocked production build | Passed, ten pages; mock and generated caches remain excluded from Git. This does not verify genuine Inter rendering. |

All database verification used a new cached `postgres:15-alpine` image, confirmed
as PostgreSQL **15.18**, in labeled container `proppulse-test-4acp-983af185c4ff`,
ID `d39d3243feec7f4288be8ea9f15e97b264b989b9609e38fe3f5098520b801a36`,
loopback port 50247, tmpfs-only data, 512 MiB memory/one CPU/128 PID limits.
Tests used `proppulse_test_4acp` random schemas and a separate initially empty
`proppulse_test_4acp_browser`. Provider keys were blank, refresh disabled, and
the real browser API used its database-enforced read-only role with lifespan
disabled. No development PostgreSQL or live provider was accessed.

The final real-API preservation check measured 214 requests and reported matching
before/after fingerprints for every fixture table. The known owned Next process
was stopped after all assertions to unblock the existing Windows teardown issue;
the runner then exited successfully. The disposable database container was
identity/label/mount/port checked and removed, and the owned API fixture process
was stopped. Generated reports, browser traces/screenshots, font mocks, build
outputs, caches, provider payloads, environment files and local backups are
excluded from the explicit 15-file commit manifest.

The normal-build failure is a reproducible networking limitation. It is accepted
for this local engineering checkpoint only; neither font-mocked browser rendering
nor the local commit establishes release readiness. Live verified NBA coverage
still requires the separately authorized contract, identity, participation,
membership, coverage, storage and reconciliation work described above. This
checkpoint introduces no such connector, backfill, operational migration,
automatic refresh, model training, deployment, push or Phase 4B work.
