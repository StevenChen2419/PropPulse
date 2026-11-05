# Portfolio demonstration (3–5 minutes)

Use two clearly announced modes: **retained genuine statistics, read-only**, then **invented offline interaction fixtures**. Do not describe expired development offers as live, or fixture prices/authentication responses as genuine sportsbook/account data. No screenshots or video are supplied by this document.

## Before presenting

1. Follow the root README setup. For an existing retained database, do not seed, migrate, refresh providers, register users or change saved/slip state without authorization. Keep refresh disabled. Confirm `/health` and `/ready`, then open Players and inspect available seasons/coverage. Record player names/URLs that actually have retained history; do not promise current-season results.
2. Build the frontend once with `NEXT_PUBLIC_API_URL=http://localhost:8000`. The offline replay below expects that exact API origin and frontend port 3199. It intercepts API requests in the test browser; it does not need a backend or database.
3. Use a separate browser profile for retained research. Remain signed out to avoid accidental account mutations. Public Discover/Players/Research can be shown without authentication. Existing credentials are private and environment-specific. Public registration has no UI; do not create development accounts for the presentation.
4. Prepare a 1440px desktop window and a 375–390px mobile view. Avoid showing terminals containing secrets, provider files, account details or private paths. Suggested captures belong in ignored `frontend/test-results/`, never public assets.

## Recording/narration sequence

| Time | Screen and action | Say/show |
| --- | --- | --- |
| 0:00–0:35 | Discover: search a player/team; select sport/market/book/side, sort and change page; reload the URL | Search/filter/pagination occur on the server. If retained offers have expired, show the honest empty state; use the offline replay for populated results. |
| 0:35–1:35 | Players → Research: choose a retained player and populated season; switch metrics | Show real recorded L5/L10 samples, source and last recorded game. NBA historical season is useful when 2026–27 is unavailable. WNBA ends July 22; NFL/NHL/MLB coverage is partial. |
| 1:35–2:15 | Research exact-line controls and chart; expand sportsbook comparison | Explain pushes/decided denominators and compare equivalent lines only. Missing odds stay unavailable; historical snapshots are not verified complete movement. Announce the switch to invented fixtures if offers are expired. |
| 2:15–3:35 | Offline Saved Props and research slip: save an exact choice, edit side/book/line, handle a rejected edit, reload, then display expiry | Fixtures show interaction behavior only. Original selection survives errors/expiry. Reload persistence here is fixture state, while isolated backend tests separately verify SQL persistence and user ownership. |
| 3:35–4:15 | Mobile navigation, filters, chart and collapsed slip; optional rejected login | Show readable source/freshness states and recovery. Explain real sign-in uses bcrypt/JWT and user-scoped PostgreSQL state; the replay uses invented authentication state. |
| 4:15–4:40 | README architecture diagram and verification report | Highlight transactional ingestion, identity resolution, bounded credits, freshness, migrations and regression tests. State that public deployment remains a separate step. |

## Reproducible offline replay and reset

The checked-in Playwright scenarios already provide isolated, labeled invented fixtures for Discover search, multi-sport season summaries, exact-line research/comparison, saved selection/slip editing, expired prices and failed login. No provider keys, backend server or test PostgreSQL are needed. The responses exist only inside Playwright's browser context, not an application demo route.

From `frontend`, with existing npm dependencies and installed Chrome:

```powershell
$env:NEXT_PUBLIC_API_URL='http://localhost:8000'
$env:NEXT_TELEMETRY_DISABLED='1'
npm run build
# Terminal 1; keep running for the replay:
node node_modules/next/dist/bin/next start --hostname 127.0.0.1 --port 3199
# Terminal 2, also in frontend:
$env:PLAYWRIGHT_EXTERNAL_SERVER='1'
npx playwright test e2e/discover-filters.spec.cjs e2e/multi-sport-research.spec.cjs e2e/exact-line-research.spec.cjs e2e/saved-selections.spec.cjs --headed --debug
```

Playwright Inspector starts paused; use Step/Resume to show each scenario. Test titles and this narration identify all values as invented. Fixtures include recognizable athlete/book names to exercise rendering; those names do not establish genuine observations. To avoid any ambiguity in a recording, add an editing/recording title **“Offline interaction fixtures — invented data”** before this segment. This document does not claim that such a recording exists.

Reset by stopping the replay and rerunning the same command: each test starts a new browser context and rebuilds in-memory fixture state. There is **no database reset command**. Close the test browser and frontend terminal when done. Never run legacy seed, demo refresh or line-movement scripts against retained research. Screenshot suggestions: Discover filters/URL, genuine historical summary with coverage, exact-line chart, comparison with separate lines, exact saved choice, edited/expired slip, and narrow mobile layout. Create them deliberately; automated failure captures do not constitute a finished portfolio gallery.

## Limits to say aloud

Fresh clones do not include private retained provider data. Replaying genuine statistics therefore needs an already provisioned, authorized retained dataset; otherwise demonstrate the empty state and clearly labeled fixture research. NBA 2026–27 access is not successfully verified; source completeness is unknown; NFL is retained-only; WNBA stops July 22; MLB legacy exclusions and Liam Hicks identity conflict remain. Prices naturally expire, no provider refresh is part of the demo, and historical movement/payout approximations are not verified sportsbook quotes. Mocked auth state is not a real successful login or database persistence check. See the final report for actual backend and browser verification.
