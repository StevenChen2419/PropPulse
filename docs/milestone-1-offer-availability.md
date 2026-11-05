# Milestone 1: Unified Offer Availability and Freshness

## Original issues

- Research filtering checked timestamps without consistently validating prices, provider event identity, sportsbook identity, or side coverage.
- Slip writes, slip reads, and parlay estimates used different eligibility checks. Some paths fell back to legacy Prop prices without a persisted sportsbook offer.
- Saved props exposed expired offers and legacy prices without availability metadata.
- Game Detail consumed a `source` field its endpoint did not return.
- Historical ingestion counts could keep the home page reporting Live odds indefinitely. Persisted ingestion cache ages were not response-time ages.
- Research line-movement responses exposed raw primary-book prices as Current even if that book had expired while another remained available.
- Retained frontend selections could substitute another offer or retain an old actionable price after an exact offer disappeared.

## Shared policy

`backend/app/services/offer_service.py` owns exact offer resolution, price validation, eligibility, freshness, primary prices, and best-line serialization.

An offer must be a persisted PropBook row belonging to an active prop with a non-synthetic provider event and a known future game time. The requested sportsbook must be supported, and the exact sportsbook/line/side must exist. Existing line tolerance remains 0.001. Prices must be finite numeric American odds with absolute value at least 100; booleans are rejected. Unknown observation times and future observations are unavailable.

All comparisons normalize timestamps to UTC. Naive database timestamps mean UTC. A game is unavailable at its start time. Offers are Live through 30 minutes, Last known after 30 minutes through six hours, and Expired after six hours. The six-hour boundary remains inclusive. Last known is eligible only when every other policy check succeeds.

Availability states are `available`, `last_known`, `expired`, `game_started`, and `market_unavailable`. Unavailable prices are returned as null. Aggregate freshness is conservative: the oldest eligible offer controls the label; expired offers cannot win a comparison. Best prices compare only equivalent lines, while eligible alternate lines remain separate offers.

No policy path deletes saved props, slip items, snapshots, props, or watchlists. Legacy slip items without recorded sportsbook/line remain stored but require explicit reselection. Their identity is not inferred from today's primary offer.

## API contracts

- Prop, sportsbook-offer, and slip-selection responses include availability, actionable, source, observation age, observed/refreshed timestamp, expiry, and evaluation time.
- Primary Over/Under prices are nullable and resolved from the exact persisted offer.
- Game Detail returns source and availability metadata and counts only eligible sportsbooks.
- Ingestion status retains historical ingestion outcome/count fields and adds response-time current availability, current prop counts, current offer metadata, and dynamically evaluated per-sport ages/status.
- Unavailable payout estimates return a null result and explicit reason/status before statistical calculation or history lookup.
- Watchlisted players without available props remain visible with zero current props and null top-prop/next-game fields.
- Frontend and Pydantic contracts accept unavailable/null prices. Existing source labels remain live/last_known/unavailable.

## Frontend behavior

Offer selection requires backend eligibility metadata and checks expiry/game start locally. Missing preferred offers do not substitute a sportsbook, line, or side. Expired selections remain removable; unavailable prices cannot enter local returns or SGP estimate requests. Slip availability refresh preserves choices, removals, and in-flight edits.

Cards, research prices, Game Detail, summary cards, and freshness labels reevaluate locally over time, including while offline. Research current prices are policy-guarded; historical opening prices remain informational. The home page separates current availability from last ingestion time and counts. Styling, routes, server layout, and persistence workflows are preserved.

## Files added or modified by this milestone

Backend:

- `backend/app/services/offer_service.py` (new)
- `backend/app/services/slip_service.py`
- `backend/app/services/parlay_service.py`
- `backend/app/routers/props.py`
- `backend/app/routers/players.py`
- `backend/app/routers/users.py`
- `backend/app/routers/interactions.py`
- `backend/app/schemas.py`

Frontend:

- `frontend/src/lib/propSides.ts`
- `frontend/src/lib/types.ts`
- `frontend/src/lib/useOfferClock.ts` (new)
- `frontend/src/store/slip.ts`
- `frontend/src/components/PropCard.tsx`
- `frontend/src/components/SlipDrawer.tsx`
- `frontend/src/components/ParlayCalculator.tsx`
- `frontend/src/app/page.tsx`
- `frontend/src/app/games/[gameKey]/page.tsx`
- `frontend/src/app/player/[id]/page.tsx`
- `frontend/src/app/players/page.tsx`
- `frontend/src/app/analytics/page.tsx`

Tests and report:

- `backend/tests/test_offer_availability.py` (new; 14 tests)
- `backend/tests/test_props_ordering.py`
- `backend/tests/test_slip_sides.py`
- `backend/tests/test_parlay_service.py`
- `frontend/tests/prop-sides.test.cjs`
- `frontend/tests/sportsbook-selection.test.cjs`
- `frontend/tests/parlay.test.cjs`
- `frontend/tests/live-refresh.test.cjs`
- `docs/milestone-1-offer-availability.md` (new)

At Milestone 1 implementation completion, other pre-existing uncommitted files were left intact and no commit or push had been made. The later authorized checkpoint includes the reviewed prerequisite features with Milestone 1.

## Tests and verification

The new backend tests cover fresh and cached offers, expiration, game start, invalid prices, unsupported/missing identity, missing side, different line, legacy fallback rejection, synthetic identity rejection, expired saved props, unavailable slips, expired payout estimates, mixed offers, UTC/TTL/live boundaries, Game Detail's contract, historical ingestion success, unavailable watchlists, and research current-price eligibility.

Frontend regressions cover expiry/start blocking, exact preferred-offer preservation, Last known messaging, unavailable SGP display, availability refresh with pending/removal preservation, and offline clock cleanup. Existing fixture updates use real sportsbook identities and observed offers without weakening the statistical or persistence tests.

Executed commands:

| Directory | Command | Final result |
| --- | --- | --- |
| backend | `.\venv\Scripts\python.exe -m unittest discover -s tests -p test_offer_availability.py` | Passed initial focused suite, 12 tests; two further regression tests then passed in full suite |
| backend | `.\venv\Scripts\python.exe -m unittest discover -s tests` | Passed, 100 tests |
| frontend | `npm test` | Passed, 32 tests |
| frontend | `npx tsc --noEmit` | Passed |
| frontend | `npm run build` | Passed final production build |
| root | Python `compileall -q backend/app` | Passed |
| root | Scoped `git diff --check` | Passed for implementation files checked |

Early suite failures came from legacy fixtures and were corrected. The first sandboxed build failed on the existing Google Fonts fetch and caught an encoding issue introduced during editing; encoding was repaired and the final build passed with network access for the existing font. No paid API/provider calls were made. Provider-oriented test output comes from mocked clients/isolated fixtures. Application startup, ingestion scripts, and migrations were not run as verification.

Standalone `npm run lint` was not run because the repository lacks an ESLint configuration. Browser interaction/E2E checks and real PostgreSQL transaction checks were not run; test apps avoid the real application lifespan/database. The full repository whitespace check found a pre-existing README trailing blank line; it was left untouched. Git required read-only access outside the sandbox because of repository ownership checks.

## Limitations and migrations

No database migration or dependency change is required. Statistical modeling, ingestion scripts, production configuration, Redis, and application data are unchanged.

The current schema stores observation/ingestion together in PropBook.updated_at; it cannot independently establish the provider's own market observation time. The new metadata states this storage limitation rather than inventing a provider timestamp. Sportsbook titles use an explicit supported set; new provider titles/aliases require an intentional policy update. Offers remain eligible during the existing six-hour Last known window, which does not guarantee continued availability at the sportsbook. Local UI boundaries reevaluate every second, and withdrawn offers are learned through refresh; final eligibility is always rechecked for backend estimates and slip writes.

Legacy selections missing exact identity require user reselection, not automatic migration. Game Detail retains its existing 404 behavior when no eligible props remain. Browser behavior and production PostgreSQL concurrency remain unverified by this milestone.

## Suggested next milestone

Add distinct provider observation and ingestion timestamps plus stable bookmaker keys through an additive migration, then add browser workflow coverage for expiry, unavailable saved/slip selections, reconnection, and concurrent selection refreshes. Preserve the existing analytics meanings and historical records during that work.


## Authorized checkpoint review

The checkpoint groups the existing correlated parlay estimator, provider-history/research work, browser polling, risk intelligence, and offer-availability changes together because their API/type/source dependencies share files. Root repository instructions are committed separately. This checkpoint adds the pre-existing estimator dependency declarations; Milestone 1 itself did not change statistical modeling or dependencies.

The review corrected two joined empty API-key assignments in the environment template and an extra README EOF blank line. No application logic was reconstructed to split commit boundaries.

An inherited ingestion limitation remains deferred: partial refresh cleanup can delete omitted valid sportsbook offers for a touched prop, and HTTP-level success does not establish complete event/market coverage. Offer eligibility does not solve that ingestion cleanup issue. Future coverage-aware ingestion work should preserve omitted valid offers; this checkpoint does not claim complete ingestion failure protection.
