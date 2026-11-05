# Milestone 3A: Player matching diagnostics and historical research

Follow-up: [PostgreSQL verification and local checkpoint](milestone-3a-postgresql-verification.md).
This document records the initial implementation stage. Its unavailable database,
skipped PostgreSQL tests, and not-yet-committed statements are historical; the
follow-up records the subsequent authorized verification and checkpoint.

## Scope and starting state

Implemented from clean `master` at
`7ef957ddc35f99126db01dddba48125316a8dc96`. Parent and application AGENTS
instructions, Milestones 1–2 documentation, current implementations, and tests
were reviewed. Effective `LIVE_REFRESH_ENABLED` was confirmed `False` without
printing credentials or environment contents.

No Event model, foreign keys, migrations, dependency changes, game-route changes,
provider requests, production service startup, application database writes,
commits, or pushes are part of this work. Existing offer eligibility, observation
timestamps, exact-line comparisons, locking, budgets, saved props, and slips retain
their existing behavior. Test provider messages come from mocks, not live calls.

## Confirmed problems

- The retained NBA smoke report contains seven parsed offer rows, four persisted
  rows, and three aggregate unmatched rows. It does not contain the skipped
  identities; they cannot be reconstructed or invented.
- Normalized-name dictionaries could silently overwrite provider candidates.
  Historical and odds matching each had this weakness.
- The prior read-only audit verified Tatum's 22 and Cunningham's 81 `espn_nba`
  points logs on the same player IDs as their props. All belonged to ending-year
  season 2026. October 20, 2026 props select ending-year season 2027; the old
  service excluded other seasons before calculating every window.
- Offer prices, movement, and history were rendered behind a successful-trends
  condition, hiding valid offer information when history was unavailable.
- Player-derived game keys are mutable and are not authoritative event evidence.

The player counts and event inventory from that audit are historical observations,
not fresh database measurements made by this implementation.

## Matching architecture

`player_matching.py` provides a reusable candidate index, `MatchResult`, exact
matching policy, and bounded `MatchingDiagnostics`. Name normalization remains
exact after the established accent/punctuation/suffix normalization; no fuzzy
matching is introduced. Sport scoping remains at the database/provider caller.

Local candidate lists preserve duplicate names. Roster directories preserve every
distinct provider candidate instead of overwriting a normalized key. Repeated
identical known provider identities do not create false collisions; multiple
unidentified roster entries remain ambiguous. Unique roster values retain the
legacy dictionary shape, with lists used for collisions, so existing callers can
transition through `roster_candidates`.

Odds matching rejects local ambiguity and roster collisions before selecting a
player. A new player requires a unique roster team belonging to the provider
event; unavailable rosters no longer create unknown-team players. An existing
unique player can still match using its known team when a roster is unavailable.
Unknown teams and mismatches fail closed. Smoke scope still prohibits roster
changes and player creation. Rejected identity does not rewrite a player's team.

Historical matching similarly rejects duplicate local names and duplicate
provider/roster candidates before requesting a specific athlete's history.
Provider athlete IDs remain transient; a persistent cross-provider athlete
identity table is outside this phase.

### Reason codes

Each parsed offer row has one final persistence disposition:

| Code | Meaning |
| --- | --- |
| `matched` | Identity accepted and row accepted for persistence; transaction outcome is separate |
| `ambiguous_player` | More than one local normalized-name candidate |
| `roster_name_collision` | More than one provider or roster candidate; no arbitrary selection |
| `scope_existing_players_only` | Smoke scope would require creating a player |
| `unknown_team` | Required player/roster team is unknown |
| `team_not_in_event` | Known team is not a provider event participant |
| `roster_unavailable` | No usable provider roster was available for a missing identity |
| `missing_player` | Available/empty provider lookup has no matching identity |
| `invalid_offer` | Parsed persistence input lacks required identity/time/price data |
| `duplicate_offer_row` | Repeated identical input row; only one is processed |
| `conflicting_offer_identity` | Conflicting rows for one group/book identity; all conflicting rows rejected |
| `duplicate_event_group` | Repeated group already applied in this transaction |
| `bookmaker_identity_conflict` | Stable provider-book identity cannot resolve uniquely |
| `bookmaker_label_collision` | Existing selection label conflicts with another offer |
| `stale_provider_observation` | Older/missing observation cannot replace a known newer one |
| `invalid_prop` | A new prop cannot be constructed from accepted data |

### Counting and reporting

`matching_diagnostics` is retained in per-sport/run and smoke reporting:

- `stage` distinguishes persistence from historical identity matching.
- `row_unit` is `offer_rows` for parsed sportsbook offers and `player_requests`
  for historical identity attempts. These units must never be added together.
- `row_counts` assigns each input row one final disposition. Parser rejections
  occur earlier and remain covered by existing parser issues, not invented rows.
- `group_counts` counts unique event/market/normalized-name groups **per reason**.
  A group can contain an accepted book and a rejected book; group counts across
  reasons are intentionally not additive.
- Samples include sport, event, market, bounded normalized name, outcome/reason,
  local/roster candidate counts, roster lookup status, smoke restriction, and
  affected row count. Nonmatching failures can have null candidate counts because
  matching was not evaluated.
- Samples are capped at 40 per sport, with skipped groups prioritized over
  successful groups. Complete reason counters survive sample truncation.
  `samples_truncated` counts omitted group/reason samples, not omitted offer rows.
- `transaction_outcome` separates pending attempts, committed persistence, and
  rolled-back work. An accepted match is never itself proof of a committed write.

No raw provider payload, credential, or credential-bearing URL is stored in the
new diagnostic samples. Old aggregate reports remain unchanged.

## Historical window semantics

One shared result/diagnostic builder powers research, trends, and compatibility
helpers. Eligibility is evaluated before windowing, with one exclusion reason per
stored row and normalized UTC ordering:

- Same player UUID selected by the caller, matching sport, approved sport-specific
  provider source, valid statistic (including zero), and eligible date.
- Strictly before both the selected prop's scheduled start and evaluation time.
- Explicit preseason and unfinished markers, if available, are rejected.
- Unknown same-UTC-day completion is excluded conservatively for every sport;
  explicit `stats.completed=True` can admit a same-day completed observation.
- Duplicate nonempty external game IDs count once, after statistic validation.
- Missing/invalid statistics never become zero. Signed yardage remains supported.

| Window | Meaning |
| --- | --- |
| L5 | Most recent five eligible observations, across seasons |
| L10 | Most recent ten eligible observations, across seasons |
| Current season | All eligible observations in the prop's selected season only |

Each window retains `games`, `decisions`, `hits`, `pushes`, and `hit_rate`, and adds
`seasons` plus `season_scope` (`empty`, `current_season`, `previous_seasons`, or
`mixed_seasons`). Pushes count as games but not decisions; all-push/empty decision
windows have a null rate. Samples remain newest-first.

For the October 2026 NBA scenario, prior season observations can supply L5/L10,
while the 2027 season window correctly has zero games. Nothing is hardcoded to a
player. A September/October mixed window identifies both ending-year seasons.

Average, median, and splits describe all eligible loaded historical observations,
not exclusively the current season. UI labels state this meaning. The legacy
`build_line_results` helper remains explicitly season-scoped; recent research uses
the shared builder instead. Player summaries pass the prop time to the same trend
policy. Historical queries no longer impose a January lower bound that could
discard a valid older recent sample.

### Competition and completion limits

The schema does not separately store regular season versus playoff classification
or a provider final-status field. Existing ESPN ingestion excludes preseason
sections, and the service also excludes explicit preseason markers when present.
Unclassified stored records cannot retrospectively be separated into regular and
postseason samples. The API/UI disclose this rather than assigning guessed types.

Past-date provider statistics remain a completion proxy, not proof of provider
final status. Conservative same-day exclusion can delay valid research until the
next UTC day. A future, separately scoped history metadata improvement can remove
that limitation without fabricating completion for legacy records.

## API and frontend contract

Research adds `history` independently of `selected_prop` offer availability:

- Status: `available`, `no_history`, `no_valid_market_statistics`, or
  `excluded_history`.
- Stored rows, numerically valid market rows, eligible unique observations,
  selected season, current/previous-season sample sizes.
- Mutually exclusive `excluded_counts` and insufficient-L5/L10 flags.
- Human-readable competition and completion limitations.

Valid-market counts describe raw stored numeric fields before source/date/dedup
checks; eligible counts describe observations after those checks. Their difference
is not itself a specific missing-statistic count. Stored row counts reconcile to
eligible rows plus exclusion counts.

The generic no-history message is replaced with precise states. Prior-season
history produces trends even with an empty current-season window. Existing trend
field names remain; Pydantic and TypeScript contracts carry the added metadata.
New frontend fields are optional for compatibility with older responses.

Selected prices and movement render without requiring trends. Research summaries
show actual samples, window seasons, exclusions, and historical-not-predictive
labels. Feed/Discover comparisons also disclose recent-window season scope.
Game navigation, market/line selection behavior, layout, saved/slip stores, and
hydration remain unchanged. Stable prop/event selection is deferred to Phase 3B
and its subsequent contract/UI work.

## Read-only event classification

From `backend`, run:

```powershell
.\venv\Scripts\python.exe -B scripts/classify_event_backfill.py
```

The CLI prints bounded JSON to stdout and writes neither files nor database rows.
It imports no application lifespan, models, or ingestion. PostgreSQL explicitly
enters a read-only repeatable-read transaction before any inventory SELECT, sets
a statement timeout, limits inventory size, and always rolls back. Oversized
inventories fail rather than presenting incomplete counts. Connection errors are
sanitized. Tests verify query ordering and rollback, including failures.

By default it scans local ignored `data/odds_runs/*.json`; repeatable
`--retained-report` arguments select operator-trusted reports. Only a validated
controlled-smoke report with matching sport/event scope, successful processing,
and complete event metadata qualifies. This trusts retained local operator
evidence; it is not cryptographic provider authentication. Only allowlisted event
fields are projected, never the complete payload.

| Category | Meaning |
| --- | --- |
| `verified_retained_metadata` | Authoritative retained participants/start match the stored provider identity/time |
| `candidate_requires_verification` | Provider identity exists but independent event evidence is absent |
| `conflicting_metadata` | Stored/retained schedules or sport conflict, or unresolved derived keys disagree |
| `missing_provider_identity` | Provider event/sport identity is incomplete |
| `legacy_unknown_origin` | Unsupported or explicitly synthetic identity origin |

Verified metadata can resolve mutable player-team disagreement; player-derived
teams never verify an event. Missing identities are counted per prop, not asserted
to be distinct actual events. Categories expose group and prop-row counts;
diagnostic samples are bounded and distributed across categories.

### Findings in this implementation session

Local retained-report inspection accepted **one** controlled-smoke report and
ignored **three** unrelated/invalid JSON reports. The accepted evidence identifies
Boston Celtics at Detroit Pistons, provider event
`26b036ff107f3c658258eaf4a6f26228`, sport `basketball_nba`, October 20, 2026 at
19:00 UTC. This is historical retained evidence, not a live provider recheck.

The read-only PostgreSQL attempt failed with `OperationalError` before obtaining
an inventory. No current category counts are claimed. The previous audit observed
6,064 props, 93 populated composite event identities, 26 derived-key splits, and
321 missing identities; these are historical context only. Rerun the classifier
when the existing development database is available, without launching refresh
or using another paid provider request.

## Verification

Final integrated commands and results:

| Directory | Command | Result |
| --- | --- | --- |
| backend | `.\venv\Scripts\python.exe -m unittest discover -s tests` | 237 discovered: 226 passed, 11 skipped |
| frontend | `npm test` | 37 passed, zero failures/skips |
| frontend | `npx tsc --noEmit` | Passed |
| frontend | `npm run build` | Passed, including all ten static pages |
| root | `.\backend\venv\Scripts\python.exe -m compileall -q backend/app backend/scripts` | Passed |
| root | `git --git-dir=.git --work-tree=. diff --check` | Passed |

Focused backend regressions include 21 matching tests, 19 event classifier tests,
10 historical research/service/API tests, the existing seven trend tests,
37 Milestone 2 ingestion tests, and 13 smoke-wrapper tests. Frontend adds five
rendering regressions for truthful history states, independent offers, scope,
sample size, and exclusion labels. Earlier focused commands used the corresponding
`-p test_*.py` unittest discovery patterns and Node test runner files.

The eleven skips are the existing optional real PostgreSQL integration/process
tests because no disposable test URL was supplied. Existing `datetime.utcnow()`
deprecation warnings remain. Git emits line-ending normalization warnings; the
whitespace check itself succeeds. Explicit `--git-dir`/`--work-tree` avoided the
environment's ownership check without changing global Git configuration.

No isolated real PostgreSQL verification or browser E2E is claimed. Optional
PostgreSQL tests remain gated by the explicit disposable-test URL and were not
pointed at application data. No standalone ESLint check is claimed; the repository
does not provide the expected standalone configuration.

## Changed files

Backend implementation:

- `backend/app/services/player_matching.py` (new)
- `backend/app/services/team_directory.py`
- `backend/app/services/trend_service.py`
- `backend/app/services/event_backfill.py` (new)
- `backend/app/routers/players.py`
- `backend/app/schemas.py`
- `backend/scripts/fetch_odds.py`
- `backend/scripts/fetch_player_game_logs.py`
- `backend/scripts/smoke_odds.py`
- `backend/scripts/classify_event_backfill.py` (new)

Frontend implementation:

- `frontend/src/lib/types.ts`
- `frontend/src/lib/researchLabels.ts` (new)
- `frontend/src/app/player/[id]/page.tsx`
- `frontend/src/components/PlayerResearchChart.tsx`
- `frontend/src/components/PropSideComparison.tsx`
- `frontend/src/components/ResearchHistorySummary.tsx` (new)

Tests and documentation:

- `backend/tests/test_player_matching.py` (new)
- `backend/tests/test_history_research.py` (new)
- `backend/tests/test_event_backfill.py` (new)
- `backend/tests/test_milestone2_ingestion.py`
- `backend/tests/test_smoke_odds.py`
- `frontend/tests/research-history.test.cjs` (new)
- `docs/milestone-3a-matching-history.md` (new)

## Compatibility, remaining risks, and Phase 3B

No stored rows or identities were changed. Collision rejection and refusal to
create unknown-team players can intentionally reduce ingestion coverage; the
diagnostic reasons make that reduction explainable. Normal verified player
creation, stable offer/snapshot identities, and failed-refresh preservation remain
covered by regression tests. Older-observation skips retain their separate legacy
counter and now also have a diagnostic disposition.

Provider athlete IDs are not yet persisted, team names require exact normalized
agreement, historical coverage is provider-dependent, and unknown competition/
completion metadata remains limited. Current game keys and research selection
still have the identity weaknesses identified in the architecture audit.

Phase 3B should add a minimal Event UUID, canonical provider/sport/event unique
identity, authoritative participants and UTC schedule, plus nullable indexed
`props.event_id` with restricted deletion. Keep legacy fields during compatibility.
Backfill only independently verified relationships using this classifier's
manifest; leave unresolved props untouched. Test fresh/legacy upgrades against an
isolated real PostgreSQL database, including the initial revision's current-model
bootstrap behavior. Do not introduce a blanket non-null relationship, inferred
participant backfill, or cancellation status unsupported by provider evidence.
