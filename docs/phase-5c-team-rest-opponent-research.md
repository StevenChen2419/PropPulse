# Phase 5C — team rest and opponent matchup research

Implemented October 18, 2026 from requested HEAD
`67cf5768c4d79610d2bcae2fcab53e41165a1316`. The implementation checkpoint
left changes uncommitted. The separately authorized final review/local commit
checkpoint is recorded below.
Parent/root AGENTS instructions, Phase 5A/5B and Phase 4A rest, verified
participation, NBA integration and real-data demonstration reports were reviewed.
The two pre-existing untracked reports are preserved unchanged.

## Features and reused storage

The existing player research endpoint gains a separate `matchup_context` field.
It contains selected team/opponent identity, the latest **recorded completed**
team game, Eastern calendar gap, full intervening days, conditional back-to-back,
and player PTS/REB/AST/MIN averages against the selected opponent. Overall,
L5 and L10 opponent windows expose actual appearance counts, each statistic's
valid denominator and covered date range. Empty averages remain null.

Reuses `PlayerGameLog.stats['_nba']`, existing `NBAEvidenceRecord` NBA.com
team/game evidence, the selected Prop's linked Event and Phase 5B statistics.
The narrow `nba_matchup_context.py` service reads stored rows only. The existing
season eligibility logic was extracted to `recorded_nba_scope`; the output and
behavior of `season_summary` are unchanged. No participation certification,
ingestion, odds, Discover, authentication or user persistence pipeline changed.

**No migration, table, column or dependency was added.** Existing schema revision
`20261018_04` remains required. Migrations were applied only in disposable tests.
No provider HTTP occurs in research requests.

## Exact identity and freshness rules

The selected Prop must belong to the player and its exact `event_id` must match
the linked NBA Event. Only `Event.scheduled_start_at` supplies the reference;
legacy Prop game time, opponent and current `Player.team` have no authority.
An explicit 30-entry reviewed full-name map resolves Event participants to
canonical NBA team IDs. Abbreviations, fuzzy names and unknown participant names
are withheld. No odds Event-to-NBA-game-ID crosswalk is invented.

Team support requires eligible NBA.com appearances across stored season and
competition scopes, independently of the requested statistics scope, with reviewed local-player
crosswalk metadata, the expected Stats provider, canonical game ID, matching
Eastern game date and distinct supported team/opponent IDs. At least one must
lie within the preceding 14 Eastern calendar days of the selected reference;
its observation must also be within 14 days and no later than evaluation or
reference. All supported appearances in that recent interval must agree on one
team, and that team must be an Event participant. Trade-shaped conflicting teams,
stale data or unsupported identity return one concise unavailable explanation.
This is conservative recorded team support, not current roster certification.
The 14-day policy qualifies selected-Event identity, not the age of historical
opponent samples. Once fresh identity is supported, older selected-season opponent
statistics remain eligible under their own source/scope/observation rules. General
player statistics remain usable. Player-only research requires no Prop
and returns unavailable matchup context without querying team evidence.

## Team results, rest and back-to-back

The reader uses existing `provider=nba_com`, `kind=game`,
`source=nba_api.stats.leaguegamelog` records. Their existing offline normalization
requires paired known team IDs, reciprocal home/away MATCHUP, matching date,
opposite W/L and consistent non-tied scores. A past date alone never establishes
completion. No result normalizer or verified participation calculation changed.

Only canonical game identities with `status=completed`, Eastern date precision,
known distinct teams and observations no later than both reference and evaluation
are eligible. The game date must precede both reference date and observation's
Eastern date. As-known conflicting versions or multiple games for the team on
one date withhold team rest. Identical repeated observations collapse by game ID.
The latest retained supported result is explicitly the latest **recorded** game,
not necessarily the actual latest team game. Source, game ID, observation and
date-only precision remain exposed; no tip-off/completion timestamp is invented.

- Calendar gap = selected Event Eastern date minus recorded game Eastern date.
- Full intervening calendar days = `max(gap - 1, 0)`.
- Gap 1 supports **Yes, if the team plays the selected game**.
- Other gaps and missing evidence yield **Unknown** back-to-back. Existing
  LeagueGameLog evidence never certifies complete relevant schedules, so this
  service never emits a definitive negative.

October 17 to October 18 is gap 1 / intervening 0 / conditional Yes. October 16
to October 18 is gap 2 / intervening 1 / Unknown. Missing rows do not establish
rest; missing evidence never renders zero. Team gaps are separate from player
rest, recovery, DNP and missed-game totals.

## Opponent statistics and partial coverage

The service reuses Phase 5B season, competition, source selection, appearance
eligibility, observation/reference cutoff, ordering and duplicate rules. It then
requires validated NBA metadata and an exact `opponent_id` match. Display strings
are never compared. NBA.com and ESPN are never mixed; ESPN's legacy metadata
does not support this exact NBA-opponent path and remains unavailable here.
The opponent sample may include older supported appearances from a different
player team within the same selected season/competition.

Choose the newest eligible opponent appearances first, then take at most five
or ten slots. Missing numeric values never pull older replacements into a window.
Each PTS/REB/AST/MIN average uses its own valid values within those slots; zeros
remain valid, malformed/negative/nonfinite values remain unavailable, and minutes
above 100 are excluded. Existing normalization validates integer counting stats.
Two games produce two-game L5/L10 coverage, not a claim of complete windows.
No eligible opponent games yields unavailable averages, not zero performance.
Overall and window date ranges and counts make the partial coverage explicit.

These are historical player results, not predictions or current defensive-strength
ratings. No new scoring or betting probabilities are introduced.

## Frontend

The existing research page now orders selected player/game/Prop first, recent
performance and player rest next, then **Matchup & Team Rest / Against This
Opponent**, followed by detailed historical research/charts and existing advanced
participation/experimental disclosures. Exact request-selection guards hide old
matchup data while a different Prop is pending or failed. Saved/slip hydration,
watchlist and unavailable selected market behavior retain existing semantics.

The new section uses the existing card styles, responsive two/three-column team
facts and a fixed-width four-column average table. All/L5/L10 sample sizes and
valid counts remain visible. Team provenance/coverage and opponent window dates
use small disclosures. Unsupported identity produces a single short explanation.
Desktop and 390px mobile screenshots were visually inspected; browser assertions
confirm no horizontal page overflow in supported and unavailable states.

## Verification and safety

All new statistical/result examples are **invented offline provider-shaped
fixtures**, not evidence of current live NBA coverage. They were imported only
into disposable test targets via existing guarded helpers; never development.
The authorized NBA.com request budget was not reused. Provider request count: **0**.

Owned `postgres:15-alpine` container `proppulse-test-5c`, ID
`8e5d1a6751ce35748d8c038ac7a0d35b91519891ed4a82d57b23efdf2c2d4eb5`,
label `proppulse.milestone=5c`, loopback port 52469, tmpfs storage, no host mounts,
512 MiB / one CPU / 128 PID limits. Databases: `proppulse_test_5c` for random-schema
tests and separate initially empty `proppulse_test_5c_browser` for browser checks.
Version **15.18**, schema revision **20261018_04**, queried in disposable storage.
The browser API disables lifespan/refresh, blocks provider HTTP and uses a
PostgreSQL-enforced read-only role. Browser traffic is restricted to local origins.
All **15 tables / 167 rows** matched baseline counts and SHA-256 fingerprints,
including saved props, slip selections and watchlist. Zero provider HTTP attempts.
Ignored preservation evidence is `backend/data/odds_runs/5c/preservation.json`;
screenshots remain ignored under `frontend/test-results/`.

| Check | Actual result |
| --- | --- |
| Focused matchup tests with blocked HTTP | 17 passed, including 1 disposable PostgreSQL API scenario; zero provider attempts. |
| Existing season-summary focused tests | 6 passed, including 1 PostgreSQL scenario; zero provider attempts. |
| Full backend `tests/run_no_provider_http.py` | 916 passed, including 257 PostgreSQL scenarios, 154.915 seconds; no failures/errors/skips; zero HTTP attempts. |
| Frontend `npm test` | 81 passed, no failures/skips. |
| `npx tsc --noEmit` | Passed, exit 0. |
| Normal `npm run build` | Passed, ten routes, no font mock. |
| Combined desktop/mobile Playwright integration | 42 passed / 4 intentionally skipped, exit 0, 2.1 minutes including teardown. Includes 32 existing workflows, 4 synthetic evidence, 4 statistics/navigation and 2 new matchup cases. The 4 actual-source-only cases skip in this offline fixture mode. |
| Python `compileall -q app scripts tests alembic` | Passed, exit 0; operational scripts were not executed. |
| Git whitespace and preserved reports | Tracked `git diff --check` and new-file whitespace/encoding checks passed. Both existing report hashes match their initial values. |

The focused tests cover exact Prop/Event identity, stale/missing/conflicting team
support, selected Eastern date, completed/as-known results, conditional Yes versus
unknown negatives, absent results, exact opponent IDs, L5/L10 slots, independent
denominators, zeros/missing values, season/competition/source separation,
player-only research and SELECT-only requests. Existing full/browser regressions
cover saved/slip/watchlist preservation, odds expiry and selected navigation.
Independent read-only engineering review found no blocking issues.

All browser assertions finished successfully before the known Windows managed
Next-server teardown stalled. After verifying its exact command and PID, only
the owned port-3199 Next process was terminated; Playwright then exited 0 with
the results above. The owned fixture API was likewise identified and terminated.
After exact container ID/label/loopback/tmpfs/no-mount verification, the container
and its two disposable databases were removed. No listeners remained on test
ports 8000, 3199 or 52469. No development service or storage was accessed.

Final Git status contains only the 12 Phase 5C files listed below plus the two
pre-existing untracked reports. Nothing is staged, committed or pushed. Preserved
SHA-256 values:

- `docs/phase-5a-simplification-audit.md`:
  `2efcc90e58203aba9ac81980d3cf143b561296943faa9fbb23acd05f38231f96`
- `docs/milestone-4a4-espn-collection-plan.md`:
  `369d01900c5e69681fadc2438c214643136490b4f7b2703868920c4845e171b3`

No separate ESLint run: this package has no lint script/configured workflow.
No current provider collection, operational migration/backfill, automatic refresh,
development database access, deployment, commit or push was performed. Cold-cache
external font acquisition was not independently tested.

## Files and remaining real-data requirements

- `backend/app/services/nba_matchup_context.py`: narrow stored matchup reader.
- `backend/app/services/nba_season_summary.py`: shared existing scope extraction.
- `backend/app/routers/players.py`: additive response integration.
- `backend/tests/test_nba_matchup_context.py`: focused service/API regressions.
- `backend/tests/nba_matchup_fixture.py`: guarded invented browser fixture.
- `backend/tests/integration_server.py`: registers that fixture.
- `frontend/src/components/MatchupContextSection.tsx`: compact responsive display.
- `frontend/src/lib/types.ts`: additive contract.
- `frontend/src/app/player/[id]/page.tsx`: display and research ordering.
- `frontend/tests/matchup-context.test.cjs`: missing/zero/partial rendering checks.
- `frontend/e2e-real/nba-matchup.spec.cjs`: desktop/mobile stored-data checks.
- This report.

Real current-season use still requires separately authorized responses/import,
reviewed exact player UUID crosswalks, sufficiently recent team-supported NBA
statistics, supported paired completed team observations and a separately reviewed
operational persistence procedure. Existing evidence append guards remain test-only;
this feature does not create an operational ingestion path. Any database readiness
upgrade must be separately authorized. Complete schedule support would be needed
before enabling negative back-to-back conclusions. None of this blocks the stored,
partial research feature implemented here.

## Final engineering review and authorized local checkpoint

October 18, 2026. Starting HEAD remains
`67cf5768c4d79610d2bcae2fcab53e41165a1316`. The user authorized one local
commit containing exactly the 12 Phase 5C files above, titled
`feat: add NBA team rest and opponent matchup research`. Earlier uncommitted
statements and verification counts describe the implementation checkpoint.
This final checkpoint supersedes them after the correction below.

All 12 files and the complete change were reviewed, with an independent read-only
review. The explicit 30-name Event mapping was also compared successfully against
the installed offline NBA team directory. No provider request was needed.

One confirmed scope-coupling defect was fixed: the requested statistics season
and competition formerly controlled the recent team-identity sample. Asking for
an older season or Playoffs could therefore hide team rest and supported historical
opponent statistics even when fresh current Regular Season identity was stored.

Identity now considers each stored NBA scope through the unchanged Phase 5B
eligibility/observation guards, then unions recent supported affiliations before
checking conflicts and exact Event participants. The 14-day game-date/observation
policy remains an identity safeguard. It is not a limit on the age of an opponent
sample once selected-Event identity is supported. Stale-only records never establish
current identity, and scope selection cannot hide conflicting recent affiliations.
No mutable team/opponent strings or historical-team assumptions were introduced.

Opponent windows still use only the requested source/season/competition scope.
Missing team results do not hide supported opponent history; missing opponent
samples do not hide independently supported team rest. If recent identity itself
is unavailable or ambiguous, both matchup calculations require it and are withheld,
while general player research remains available. The response contract and frontend
needed no change for this correction. Incomplete schedules still never establish
a negative back-to-back. Empty statistics remain null, with zero sample counts.

Five added focused regressions cover older-season/Playoffs history with fresh
independent identity, absent team results, cross-competition identity conflicts,
stale-only historical data, and future/nonappearance guards. PostgreSQL API and
desktop/mobile browser assertions additionally confirm that an empty Playoffs
statistics scope retains exact selected-Prop team rest and null opponent averages.
The focused blocked-HTTP run passed **22 tests**, including one PostgreSQL scenario,
with **zero external HTTP attempts**. Final read-only review found no blockers.

Final verification used a new owned `postgres:15-alpine` container
`proppulse-test-5c-review`, ID
`672578d446e3d19bccbfb97f341636156973ca9593e9e26f85954576ba8cbfd4`,
label `proppulse.milestone=5c-review`, loopback port **52470**, tmpfs data, no host
mounts, 512 MiB / one CPU / 128 PID limits. Random-schema tests used
`proppulse_test_5c_review`; the separate initially empty browser database was
`proppulse_test_5c_review_browser`. PostgreSQL **15.18** and schema revision
**20261018_04** were queried only in disposable storage. Existing guards,
disabled lifespan/refresh, blocked HTTP and the PostgreSQL read-only API role
remained active. The browser database preserved **15 tables / 167 rows** by counts
and SHA-256, including saved props, slips and watchlist, with zero provider attempts.
Ignored evidence: `backend/data/odds_runs/5c-review/preservation.json`.

| Fresh final check | Actual result |
| --- | --- |
| Backend `tests/run_no_provider_http.py` | **921 passed**, including **257 PostgreSQL scenarios**, 154.489 seconds, no failures/errors/skips; **zero external HTTP attempts**. |
| Focused corrected matchup suite | **22 passed**, including one PostgreSQL scenario, 0.712 seconds, no failures/skips; zero HTTP attempts. |
| Frontend `npm test` | **81 passed**, no failures/skips. |
| TypeScript `npx tsc --noEmit` | Passed. |
| Ordinary `npm run build` | Passed, ten routes; no font mock. |
| Combined desktop/mobile Playwright integration | **42 passed / 4 intentionally skipped**, exit 0, 1.4 minutes including teardown. Four actual-source-only cases skip in offline fixture mode. New independence assertions passed on both viewports. |
| Python compilation | `compileall -q app scripts tests alembic` passed; no operational script executed. |
| Python dependencies | `pip check`: no broken requirements. |
| Frontend dependencies | `npm ls --all --omit=optional`: exit 0; no missing/invalid required dependencies. Existing optional-platform gaps and extraneous installed WASM packages unchanged. |
| Offline NBA directory mapping | All 30 exact full-name/canonical-ID associations matched. |
| Whitespace, preserved hashes, staged manifest | Passed; only the 12 Phase 5C files are included. |

The full suite's provider/ingestion-looking console messages come from mocked
unit scenarios; actual external transport attempts were zero. No development
database was connected. No operational ingestion/migration or automatic refresh
was run. Authentication, odds freshness/Discover ranking, ESPN history/charts,
season-summary behavior, saved/slip/watchlist semantics, verified participation,
migrations and readiness remain unchanged, with their regressions in the final run.

All browser assertions completed before Windows managed-server teardown stalled.
Only the identified owned Next PID was terminated, then Playwright exited 0.
After preservation checks the exact fixture API PID was stopped. Container ID,
label, loopback port, tmpfs and absence of mounts were verified before removing
the container and both disposable databases. Ports 8000, 3199 and 52470 had no
remaining listeners. No development service was touched.

The two pre-existing reports retain their original hashes above and remain
untracked and unstaged. Generated outputs are excluded. The authorized local
commit contains exactly the 12 reviewed files; no push or deployment follows.
Real current-season data requirements and the cold-cache font/ESLint limitations
remain as described above. No further full-suite run is needed for this report-only
final update.
