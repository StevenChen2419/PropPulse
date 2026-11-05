# Milestone 3E: Stable frontend navigation and research

Implemented from clean `master` at
`4018a5bb6ab186eb4efd3a047d84f149f82cf64e`. Parent/application AGENTS,
Phase 3D Event API contracts, Phase 3C ingestion and Phase 3A historical research
informed this change. No development database connection or inventory inspection
was made; the supplied one-Event/ten-linked-prop baseline is not remeasured here.

## Audit and scope

| Surface before this change | Finding | Implemented behavior |
| --- | --- | --- |
| Home game cards | Derived `game_key` URLs and keys | Event UUID URLs/React keys; explicit legacy fallback |
| Game Detail | Every route segment sent as `game_key` | UUID versus legacy selector; empty Event keeps metadata |
| PropCard across Feed, games, Discover and Saved | Player-only link lost selected prop | Exact `prop_id` deep link |
| Player research | Generic initial call and market/line selection; polling could replace subject | URL-backed Prop UUID, deterministic default pinned, Event/game and UUID market controls |
| Discover | Derived keys; list refresh could remove selected option | Explicit Event/legacy values and retained unavailable option |
| Async loaders | Several callbacks lacked cancellation/generation guards | AbortSignal plus latest-request generation checks |
| Player transition | Prior player's snapshot could survive a failed route change | Rendering scoped to current player ID; mismatched prop research hidden |
| Snapshot formatting | Appended Z to existing UTC offsets | Offset-aware/naive UTC values format consistently in Eastern time |

Existing design, sports/markets, rankings, historical calculations, authentication,
server layout, watchlists, saved state and slip persistence remain in place.
No backend service, schema, migration, ingestion or model behavior changed.

## Route architecture and identity

The existing App Router `games/[gameKey]` directory supports both contracts.
Keeping one dynamic segment avoids conflicting sibling dynamic routes and
preserves usable old links. Its parameter name is an implementation detail.

- Canonical: `/games/LOCAL_EVENT_ID` requests
  `/props/game?event_id=<same_uuid>`.
- Compatibility: `/games/<URL-encoded legacy key>` requests `game_key` when the
  decoded segment contains the legacy `|` delimiter. It never creates a UUID.
- A segment without a legacy delimiter is treated as an Event ID, including
  malformed identifiers, so API validation produces the explicit 422 state.
- Router values may be encoded or already decoded. The page decodes an encoded
  segment once and retains a key that already contains legacy delimiters, so
  literal percent escapes within a key remain exact.
- A schedule correction or player-team change leaves the Event URL unchanged.
  Headers and linked prop context use authoritative away/home teams and schedule.

`gameNavigation.ts` centralizes route construction, selector serialization,
Eastern-time context labels and safe error messages. Filter values use
`event:<uuid>` or `legacy:<key>` to distinguish provenance; those prefixes are
UI values, not backend canonical identifiers. No teams/timestamps are parsed out
of Event UUIDs. Backend Event filtering remains responsible for exact membership;
the frontend does not mix in unlinked props by matching participant names.

Home calls the preserved upcoming game-list API and labels the section
**Upcoming Games**. `/todays-games` has not been changed into a local-date filter.
Home has no selected-game filter to reconcile; selecting a card navigates to its
stable detail URL. Discover uses Event UUIDs for verified game filters and retains
the selected unavailable Event even if the refreshed eligible list omits it.
Changing sport or clearing the filter is an explicit user action. A disappearing
game, request error or ambiguous legacy key never selects another matchup.

## Exact player research

PropCard links now use `/player/<player_uuid>?prop_id=<prop_uuid>` everywhere the
shared card appears. The player's Active Props rows also link to exact UUIDs and
use authoritative context for linked records. Generic player search, watchlists
and analytics entries that do not identify a Prop retain generic player links.

The research page calls `/players/{player_id}/research?prop_id=<uuid>`. No market
or line is sent alongside it. Generic entry asks the backend for its deterministic
default, immediately records the returned UUID for polling, and replaces the URL
with that UUID. Browser refresh, back/forward and copied links retain the subject.
The same Prop UUID survives line movement and offer expiration.

Game choices group available props by their returned Event UUID or explicit
legacy key. Unresolved props stay separate rather than inventing a matchup.
Market options use Prop UUID values, distinguishing identical markets/lines in
different games and duplicate rows within a game. Changing the game explicitly
opens its first returned available Prop; the market selector then selects exact
UUIDs within it. Unavailable selected props are appended to the choices when they
are absent from `available_props`, so expiry cannot remove the selected subject.

A research Prop selection is not a sportsbook offer or slip selection. It follows
the Prop's current displayed line; it does not silently pin or replace a stored
slip's sportsbook/side/line tuple. Unknown or wrong-player UUID errors keep the
URL and show a safe error instead of retrying with generic research.

## Request lifecycle and refresh

`createRequestGate()` cancels the previous AbortController and increments a
generation on each request or cleanup. Publishing success, failure and loading
state requires a current generation. This also protects against transports that
ignore aborts or finish parsing after a selection changes. API methods accept
optional AbortSignals without changing existing callers.

Home has one gate for its combined Feed/game-list load. Discover has independent
gates for ranking results and game options. Filter handlers invalidate in-flight
work immediately. Game Detail cancels on route/revision changes and unmount.
Research additionally checks player/Prop route identity and retained selected ID;
its rendered snapshot is scoped to the current player. Same-subject polling
retains the chosen UUID and historical snapshot while loading. Switching to
another player cannot expose the old header/history after a failed request.

The existing one-minute visible/online polling hook is unchanged: it avoids
overlapping, hidden, offline or busy refreshes, handles connection/visibility
recovery, and removes timers/listeners on unmount. No new polling interval or
state-management dependency was introduced. Follow/auth behavior is unchanged.

## Odds, history and empty states

The selected primary sportsbook and displayed line remain explicit. Primary
availability and nullable Over/Under prices are evaluated separately from
eligible alternate offers. An available alternative cannot make the primary
selection actionable. Best Over/Under prices require an eligible offer at the
exact displayed line; the explicit sportsbook list labels alternate lines.
Local offer-clock evaluation continues to suppress expired/started prices.

History is rendered independently: unavailable primary odds retain L5/L10,
season windows, samples, exclusions, limitations, charts and observed game logs.
Missing history retains sportsbook availability and line movement. Existing
cross-season recent windows, strictly current-season windows and null-rate
semantics are preserved. The existing history summary identifies statistics as
historical observations, not validated predictions.

Known Events with zero eligible props keep teams and schedule and show **Odds
unavailable for this game.** This covers expired/inactive markets without turning
the Event into a missing-game error. Explicit unavailable Prop research remains
selected. Discover explains that current offers and sufficient current-season
history are needed; an early-season empty ranking is valid.

Provenance appears in game/research context: verified Events use authoritative
metadata; legacy/unresolved contexts are explicitly unverified. Technical provider
IDs are available through existing contracts but are not repeated on every card.
Player.team remains player metadata and never establishes verified participants.

HTTP 400/404/409/422 receive readable conflict, unknown identity, ambiguity or
malformed-link messages. Network failures request retry. `ApiError` carries HTTP
status, while scoped page messages avoid exposing raw database/internal details.
Authentication callers preserve their existing error behavior. No error triggers
a redirect or fallback to another game or prop.

## Persistence and compatibility

No Zustand store, saved/slip identity, hydration routine, watchlist contract,
authentication, or layout server boundary was changed. AppInit still hydrates on
full loads; client navigation retains the mounted stores. Existing exact-offer
and hydration regressions remain in the frontend suite. Browser tests also hydrate
a saved Prop and an Under selection at a different stored line, navigate from
game to research, reload, and confirm that exact choice remains intact.

No persisted-state migration is required. Legacy URLs still depend on old keys;
Phase 3D may intentionally return 404 or 409 for stale/ambiguous identities. The
frontend discloses those outcomes instead of guessing a canonical alias.

## Automated and browser verification

Frontend unit tests use the existing Node runner, TypeScript transpilation,
static React rendering and hook-execution fixtures. New cases exercise canonical
and legacy routes, query/AbortSignal serialization, exact Prop links, generic
default pinning, line movement, duplicate markets, retained expired choices,
primary/alternative separation, missing/cross-season history, stale success and
failure responses, navigation/unmount cleanup, HTTP errors and player transitions.

A minimal Playwright dev dependency/configuration adds browser verification.
It runs the built production frontend on `127.0.0.1:3199`, with `reuseExistingServer`
disabled. Tests intercept API requests, fulfill only synthetic fixtures and abort
all unexpected external requests; no backend or provider is running. Every test
asserts that no unexpected request was attempted. Saved/auth data are local test
fixtures; no production credentials or data enter the browser tests.

Use the existing installed Chrome on Windows (or set `PLAYWRIGHT_CHANNEL=msedge`):

```powershell
# From frontend
npm test
npx tsc --noEmit
npm run build
npm run test:e2e
```

The config launches Next directly to simplify Windows process cleanup, bounds
the suite, and uses one worker. Sandbox process-cleanup limitations required the
successful browser run to execute with subprocess-management permission. Browser
traces, screenshots and reports are ignored in Git. No browser binary was
downloaded. A clean environment must provide a compatible browser channel.

| Check | Result |
| --- | --- |
| Frontend Node tests | **59 passed**, zero failures/cancellations/skips |
| `npx tsc --noEmit` | Passed |
| Production build | Passed; ten pages generated |
| Mocked Chrome browser suite | **18 passed**, zero failures/skips, 9.0 seconds; exit 0 |
| Backend Event API regressions | **48 passed**, including 24 PostgreSQL |
| Backend research-selection regressions | **44 passed**, including 22 PostgreSQL |
| Backend offer-availability regressions | **15 passed** |
| Backend external HTTP attempts | **0** in each focused run |
| Git whitespace and frontend UTF-8 checks | Passed for tracked and new source files |

The API fixtures used PostgreSQL **15.18** in disposable
`proppulse-test-m3e-20261015`, database `proppulse_test_milestone3e`, loopback port
58768, temporary test-only trust and tmpfs without bind/named-volume mounts. Only
the existing `proppulse_test_`/random-schema test paths were used. Zero test schemas
and advisory locks remained before removing that exact container. Development
PostgreSQL/backend/Redis stayed stopped. No schema migration or ingestion script
was run as an operational action.

Independent review caught stale prior-player snapshots after route failures;
the identity gate and two transition regressions fix that. The first build
caught mixed source encoding introduced while editing; UTF-8 was repaired and
subsequent builds passed. Initial browser assertions were corrected to target
visible paragraphs rather than duplicate/hidden option text; no application
availability rule was weakened to satisfy them.

Browser scenarios cover Home-to-Event-to-Prop navigation, direct links/reloads,
multiple games with identical markets, explicit market switching, line movement,
expiration with retained history, unavailable primary/available alternatives,
missing history, a delayed obsolete response, retained Discover filters,
saved/slip hydration and watchlist display, safe 400/404/409/422 errors, retry after
network failure, a real one-minute timer tick, and encoded legacy keys including
literal percent escapes. The added legacy regression exposed a router-decoding
assumption; normalization now handles both encoded and decoded segments, and
the final full browser run passed all eighteen cases. A captured research-page
screenshot was also visually inspected for layout and readable context.

The complete backend suite was not rerun because no backend behavior changed;
the 107 relevant API/availability tests above all executed with zero failures,
errors or skips. No standalone lint or cross-browser result is claimed.

## Files and remaining work

Implementation: four existing pages (Home, Game Detail, Discover and Player),
PropCard, API client/types, new `gameNavigation.ts` and `requestGate.ts`.
Tests: `game-pages.test.cjs`, `navigation-reliability.test.cjs`,
`research-navigation.test.cjs`, adjusted research-history navigation mocks,
`e2e/navigation.spec.cjs` and `playwright.config.cjs`. Package manifests add
Playwright and its test command; `.gitignore` excludes browser output.

Remaining limitations: browser tests use mocked application data rather than
real provider/integration traffic; only desktop Chrome is executed here.
Mobile, Firefox/WebKit and exhaustive screen-reader testing remain future work.
Legacy identity/alias coverage and historical provider metadata retain Phase 3D
limitations. Broader analytics player links remain generic where their contracts
provide no Prop UUID. Dependency audit findings reported during installation
were left for separate review; no unrelated upgrades were applied. No standalone lint result is claimed because the repository
has no standalone ESLint configuration.

No development writes, provider/history requests, backfills, enabled refresh,
backend behavior changes, fatigue/ranking changes, UI redesign, commits or pushes
were performed. Phase 3F can build on canonical navigation and these mocked browser
regressions; live coverage verification still requires separate authorization.

## Final review and authorized local checkpoint

The checkpoint review began on `master` at the expected
`4018a5bb6ab186eb4efd3a047d84f149f82cf64e`. The working tree contained only the
nineteen Phase 3E implementation, test, package/ignore and documentation files.
Complete diff/new-file inspection and independent read-only review found no new
confirmed regression requiring another implementation change. Event/Prop UUID
selection, explicit legacy compatibility, primary versus alternate offers,
request cancellation/generation checks, prior-player identity gating, saved/slip
choices and existing visual structure remain consistent with the contracts above.

Fresh checkpoint verification:

| Check | Actual checkpoint result |
| --- | --- |
| Frontend `npm test` | **59 passed**, zero failures/cancellations/skips; exit 0 |
| `npx tsc --noEmit` | Passed, exit 0 |
| `npm run build` | Passed, exit 0; ten pages generated |
| `npm run test:e2e` | **18 Chrome tests passed**, zero failures/skips, 9.2 seconds; exit 0 |
| Event API suite with blocked external HTTP | **48 passed**, including **24 real PostgreSQL** cases |
| Research-selection suite with blocked external HTTP | **44 passed**, including **22 real PostgreSQL** cases |
| Offer-availability suite with blocked external HTTP | **15 passed** |
| Relevant backend total | **107 passed**, including **46 PostgreSQL** cases, zero failures/errors/skips |
| External HTTP attempts in all three backend runs | **0** |
| Unexpected browser external requests | **0**, asserted by every browser case |
| Git whitespace and UTF-8 source checks | Passed |

The API suites used cached PostgreSQL **15.18**, disposable container
`proppulse-test-m3e-checkpoint-20261015`, database
`proppulse_test_m3e_checkpoint`, loopback port **60374**, temporary test-only
trust and tmpfs with no volume/bind mounts. The existing disposable-name/random
schema safeguards remained active. Cleanup verified zero remaining test schemas
and zero advisory locks before removing only that container. The frontend test
server also stopped; port 3199 had no listener. Development PostgreSQL/backend/
Redis remained stopped; no development database connection was made.

### Dependency audit — existing findings, not remediated by this checkpoint

A fresh read-only `npm audit --json` reported **17 vulnerable dependency entries**:
**1 critical, 14 high and 2 moderate**. Comparing the lockfile to HEAD confirmed
**zero changes to any existing package version**. The only added packages are
`@playwright/test`, `playwright` and `playwright-core`, all at 1.64.1 and used as
development tooling; none appears in the audit findings.

- Critical: existing `next` **15.3.2**.
- High direct dependencies: existing `eslint-config-next` **15.3.2**, `postcss`
  **8.5.15**, and `tailwindcss` **3.4.19**.
- High transitive entries: `@next/eslint-plugin-next`, `brace-expansion`, `braces`,
  `browserslist`, `chokidar`, `fast-glob`, `js-yaml`, `micromatch`, `nanoid`,
  `sharp`, and `source-map-js`.
- Moderate transitive entries: `baseline-browser-mapping` and
  `postcss-selector-parser`.

These are recorded separately from the passing functional checks. No audit-fix
command or speculative/unrelated package upgrade was applied. Remediation needs
its own compatibility and security review.

The proposed checkpoint excludes credentials/environment files, browser output,
node_modules, build artifacts, database backups, provider responses and local
verification manifests. Earlier no-commit statements describe the implementation
stage. Only the nineteen reviewed files are authorized for the local commit
`feat: add stable event navigation and prop research deep links`. No push or
history rewrite is authorized or performed, and Phase 3F is not started.
