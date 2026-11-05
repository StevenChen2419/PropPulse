# Milestone 3F: Integration, security and release readiness

Verified October 15, 2026, starting from the expected
`a8f019323e52525ea6301809eb7200489cd3f48b`. Parent/application instructions and
Milestones 3A–3E reports were reviewed. The initial implementation did not authorize
or perform a commit, push or deployment; the later authorized local checkpoint is
recorded below. Development database access is deliberately skipped; previous
development inventory observations are not fresh measurements in this milestone.

## Architecture and isolation

The production-built Next.js frontend uses its actual fetch client against the
actual FastAPI router/authentication/service stack and PostgreSQL 15.18. Browser
requests are allowed only to the local frontend and local API. API responses are
not fulfilled by Playwright in the integrated suite. Controlled request delay and
abort exercise recovery without fabricating backend responses.

`backend/tests/integration_server.py` requires an explicitly supplied loopback
`proppulse_test_` PostgreSQL target with an empty database. Its application sessions
use a separate SELECT-only role and default read-only transactions. A PostgreSQL
write challenge must fail with SQLSTATE 25006 before serving requests. Database,
refresh and provider settings are overridden before app imports; replacement
settings disable env-file loading. HTTP transports are blocked and counted.

The real application's lifespan is disabled intentionally: its `create_all` and
refresh startup are excluded. Fixture schema creation happens only in the empty
disposable database. The test wrapper adds the test origin to CORS and replaces
the retained ingestion-status reader with a fixture status. These overrides are
not production configuration fixes. Test-only manifest, preservation and scenario
endpoints must never be deployed. Scenario writes use the disposable fixture
administrator, separately from the application's read-only sessions.

The fixture has four authoritative Event records, fifteen props, three players,
fifteen offers, fifteen movement snapshots, twenty-four game logs, and one each
of user, saved prop, slip and slip item. The primary Event has ten linked props
across two players/teams and five markets. Other records exercise identical
market/line across Events, expired offers, no history, an empty authoritative
Event, and two ambiguous legacy namespaces. All observations and prices are
synthetic test fixtures, not verification of provider coverage or freshness.

## Browser coverage

The unchanged `frontend/e2e/navigation.spec.cjs` contains the eighteen existing
mocked regressions. The new `frontend/e2e-real/integration.spec.cjs` exercises
actual backend responses, separately configured in
`playwright.integration.config.cjs` for desktop and a 390×844 mobile viewport.

Scenarios cover Home → one Event card → exact player/prop research, direct links
and reload, two players sharing the same Event, identical markets across Events,
expired prices with retained history, missing history with eligible prices,
empty authoritative detail, exact Discover/Feed membership, legacy ambiguity and
invalid identifiers, one-minute polling, pending-request overlap suppression,
network-error retry, saved/slip hydration, and line/expiry changes during polling.
The fixture's original line and observation timestamp are restored in `finally`;
full-row fingerprints must match afterward. Stored Under 19.5/FanDuel remains
selected even while current research moves to 21.5 or becomes unavailable.

All twelve integrated scenarios passed in desktop and mobile Chrome, and again
in desktop and mobile Edge. Existing mocked regressions passed unchanged on
desktop Chrome and at the mobile viewport. Edge also uses Chromium; no independent
Firefox/WebKit engine was installed or cached. Those engines were not downloaded
or claimed as tested. The mobile research screenshot was visually inspected;
forms, prices, history, movement and logs rendered, with narrow but usable columns.

## Security

See [the detailed advisory and remediation record](security-3f-audit.md) for exact
advisory IDs, affected versions, dependency paths, fixed versions and remaining
risks. Initial audit: seventeen vulnerable dependency entries, including one
critical, fourteen high and two moderate. Upgrades remain within existing Next.js
15 and React 19 major versions; no forced audit fix or major application migration
is performed. Compatibility checks and final audits are recorded below.

## Regression verification

The full backend suite through `tests/run_no_provider_http.py` passed **492 tests**,
including **128 genuine PostgreSQL cases**, with zero failures, errors or skips
in 75.845 seconds. Actual PostgreSQL classes: Event API 24, research selection 22,
Event ingestion 26, Event migration 15, ingestion/API 11, process locks 2, bounded
linkage 28. Mocked PostgreSQL target guards are excluded from this count.
External HTTP attempts: **0**. Python compilation of app, scripts, tests and
Alembic passed. Test schemas and advisory locks remaining after the full suite: 0.

These tests exercise exact-line comparison, 30-minute/six-hour and game-start
eligibility, Event identity/immutability, transaction and ingestion concurrency,
historical windows, and user-selection preservation. Migration/ingestion helper
execution inside isolated test fixtures is distinct from operational execution;
no development migration, ingestion, backfill or provider operation was run.

## Preservation

Before/after ordered full-row SHA-256 fingerprints and counts cover all thirteen
application tables. The browser preservation endpoint asserts exact equality,
including user preferences, saved props, slip line/book/side, offers, observation
timestamps, logs, Event and Prop UUIDs. Temporary fixture line/expiry mutations
are restored before final comparison. The detailed final hashes are retained in
ignored local evidence, with counts/results summarized here.

No development connection was made, so no fresh development hashes are claimed.
No development records, schema, credentials, environment files, backups or named
volumes were altered. Automatic refresh was forced off for the integration
process. No live ingestion/history process was launched.

## Performance and operational review

Small-fixture timing and query counts are observations, not load-test or capacity
claims. Upcoming Games reads full prop inventory and all Events for legacy
collision safety. Feed ranks eligible rows before paging; game-specific Feed is
deliberately unpaginated. Discover loads and scores eligible inventory and history
before paging. Output limits therefore do not bound database work. Saved/slip
hydration performs per-item lookups. Larger inventories require query profiling,
indexed/bounded identity resolution and representative load tests without
weakening ambiguity detection. Redis is not introduced.

The existing polling hook uses visibility/online/busy checks, an in-flight flag
and cleanup; request gates abort superseded requests and prevent stale publication.
Browser coverage verifies key recovery and selection behavior. It does not prove
all network timing schedules or full accessibility.

Production configuration needs a separately reviewed release procedure:

- Require a non-default JWT secret; the code default is `changeme`.
- Configure actual frontend CORS origins. Current `https://*.vercel.app` is a
  literal allowed origin, not a wildcard regex; the integration origin works only
  through the test wrapper.
- Validate the target schema/revision and immutable-link trigger before startup.
  `create_all` cannot upgrade existing columns or install the PostgreSQL trigger.
- Keep automatic refresh disabled unless explicitly authorized, funded and
  configured. Startup can launch provider subprocesses when enabled.
- Add a database-readiness check to the production health strategy; `/health`
  currently reports process/status data without verifying database readiness.
- Confirm TLS, secrets, authentication/rate limits, backup recovery, hosting
  environment values and operational monitoring outside this local test scope.

No production configuration was changed implicitly. No fatigue, Discover scoring
or prediction model was changed.

## Final execution and recommendation

| Executed check | Final result |
| --- | --- |
| Full backend with isolated PostgreSQL and blocked HTTP | 492 passed; 128 genuine PostgreSQL; 0 failures/errors/skips |
| Frontend Node suite | 59 passed; 0 failures/skips/cancellations |
| TypeScript `npx tsc --noEmit` | Passed |
| Production `npm run build` | Passed; Next 15.5.28; ten static pages |
| Existing mocked desktop Chrome | 18 passed; 8.9 seconds |
| Same mocked cases at mobile viewport | 18 passed; 8.8 seconds |
| Real-backend Chrome desktop/mobile | 24 passed (12 + 12); 18.7 seconds |
| Real-backend Edge desktop/mobile | 24 passed (12 + 12); 18.8 seconds |
| Dependency audit, complete | Exit 1: 9 entries; 0 critical, 7 high, 2 moderate |
| Dependency audit, production only | Exit 0: zero findings |
| Python compilation | Passed |
| Git whitespace, tracked and added text | Passed |

Total executed browser cases: **84**, all passed, none skipped. They comprise
**36 mocked** and **48 integrated** executions; repeating cases on another
viewport/channel does not create additional unique test scenarios. No failing
functional test remains. The initial sandbox build failed to download Google
Fonts; the permitted production build succeeded. Full audit intentionally
continues to return nonzero because development vulnerabilities remain.
Standalone lint was not run: its existing command/configuration is not a working
standalone ESLint workflow. No load test, real-provider freshness verification,
deployment smoke test, independent browser-engine run, comprehensive accessibility
audit or production startup/migration execution is claimed.

Final security versions are Next **15.5.28**, React/React DOM **19.0.9**, and
PostCSS **8.5.30**, with compatible patched transitives and regenerated npm lockfile.
The generated `next-env.d.ts` route-types reference is expected Next 15.5 output.
The remaining seven high entries propagate from unpatched braces 3.0.3 through
development glob tooling. The two moderate entries affect development selector
parsing. These are absent from the production audit but require a supported
toolchain remediation or a reviewed, evidence-backed CI/build isolation decision.
No blanket security-risk acceptance is made here.

Final observed local medians were approximately 22 ms for Event detail, 18 ms
for primary research, 24 ms for Discover, and 42 ms for Feed across 402 measured
actual API requests. Maximum observed Event detail was 60.18 ms and primary
research was 42.60 ms. Metrics include success and error scenarios.
Per-request query observations included Event detail 14, research 7, Discover 3,
Feed 16, game list 3 and ingestion status 1. These include ten-prop Event fixtures;
ranking's per-prop fatigue lookups explain much of Event/Feed query growth.
No ranking/fatigue behavior was changed to optimize these results.

Preservation counts were equal before/after: Events 4; players 3; props 15;
offers 15; snapshots 15; logs 24; users/saved/slips/slip-items 1 each;
fatigue/interactions/rankings 0 each. All thirteen full-row hashes matched.
Provider/external HTTP attempts were zero in backend verification and browser
integration; every browser case asserted zero unexpected external requests and
zero application mutation requests. Explicit test scenario mutations were confined
to the disposable fixture and restored.

The disposable container was `proppulse-test-m3f-20261015`, PostgreSQL 15.18 from
cached `postgres:15-alpine`, loopback port 59432, temporary test-only trust and
tmpfs without bind mounts/named volumes. Full backend tests used
`proppulse_test_m3f`; final browser fixture used `proppulse_test_m3f_final`.
Final cleanup found zero random test schemas and advisory locks in all three
disposable test databases, saved the preservation evidence, stopped the API,
and removed only that container. Ports 8000 and 3199 had no remaining listeners.
Development database/backend/Redis containers remained stopped.

### Reproduction

Provision an empty, disposable PostgreSQL 15 test database with the guarded name,
and provide its URL only to the test process. Do not substitute development.
From backend, run `venv/Scripts/python.exe tests/run_no_provider_http.py` with
`PROPPULSE_TEST_POSTGRES_URL` set. For browser integration, supply a separate empty
test database to `venv/Scripts/python.exe -B tests/integration_server.py`, serving
port 8000. The runner deliberately refuses a previously populated fixture DB.
Build frontend with `NEXT_PUBLIC_API_URL=http://localhost:8000`.

From frontend:

```powershell
npm test
npx tsc --noEmit
npm run build
npm run test:e2e
npx playwright test --config playwright.mobile.config.cjs
npm run test:e2e:integration
$env:PLAYWRIGHT_CHANNEL = 'msedge'
npm run test:e2e:integration
npm audit --json
npm audit --omit=dev --json
```

Run browser commands sequentially; each starts/stops its own frontend on 3199.
The fixture server remains separate until its final fingerprint evidence is saved.
Generated audit/preservation evidence lives in ignored `backend/data/odds_runs/`;
browser screenshots/results are ignored under frontend/test-results.

### Changed files

- Backend: new `tests/integration_server.py`; no production backend/schema change.
- Frontend: package manifest/lockfile, generated `next-env.d.ts`, new
  `e2e-real/integration.spec.cjs`, `playwright.integration.config.cjs` and
  `playwright.mobile.config.cjs`. The original eighteen mocked tests are unchanged.
- Documentation: this report and `security-3f-audit.md`.

### Readiness decision and next priorities

**Ready for Milestone 3F engineering review; not approved for production deployment.**
Actual local application integration and persistence checks pass, and known
critical production dependency findings are remediated. Release blockers are
unresolved applicable development/CI high-severity exposure without an approved
isolation/remediation decision, and unverified production secret/CORS/schema/
startup/readiness configuration. Large-inventory performance also lacks evidence.
The test-only CORS and read-only lifespan bypass must not be mistaken for passing
production operational checks.

Suggested next milestone: **3G — supported build-toolchain security remediation
and staging release hardening**. Scope the Tailwind/PostCSS and independent ESLint
glob-chain work separately, retain visual/regression parity, then validate secrets,
origins, migrations, readiness, backups and representative performance in staging
under explicit operational authorization. Add Firefox/WebKit and accessibility
coverage when those environments are available. Preserve current Event/Prop UUID
and historical-research contracts; prediction/fatigue development is out of scope.

No commit, push or deployment was performed.

## Final review and authorized local checkpoint

The final review started at the expected previous HEAD
`a8f019323e52525ea6301809eb7200489cd3f48b`. Complete tracked diffs, new files,
dependency graph, generated route-types reference and ignored artifacts were
reviewed, with independent read-only review. The user explicitly authorized one
local commit, `test: add real-stack integration coverage and security updates`.
No push, history rewrite, deployment or Phase 3G work is included.

One safety correction was made: `integration_target()` now rejects every URL
query parameter before engine creation or application imports. Libpq host,
dbname, service and options parameters could otherwise override a validated
loopback/disposable target. Four focused regressions cover valid/invalid targets,
query overrides, inert harness import and absence of test routes in production.
The import regression runs in a separate interpreter, blocks database connections
and does not execute the application lifespan. This raises backend discovery from
492 to **496**, while genuine PostgreSQL scenarios remain **128**.

Production `app.main:app` has no reference to this harness. Importing the harness
does not import the application, connect, create fixtures or register endpoints.
Manifest/scenario/preservation registration is nested inside explicitly invoked
`main()`, after guarded target validation and the empty-database check. The
production startup command remains unchanged; no environment flag activates
test routes. The test fixture and its administrative controls must not be served
as a production entry point.

Fresh final checkpoint results:

| Check | Actual result |
| --- | --- |
| Full blocked-HTTP backend discovery | **496 passed**, 0 failures/errors/skips; 80.256 seconds |
| Genuine isolated PostgreSQL cases included above | **128 passed**, PostgreSQL 15.18 |
| New harness guard regressions | **4 passed**, non-PostgreSQL |
| Frontend units | **59 passed**, 0 failures/cancellations/skips |
| TypeScript | Passed |
| Production Next.js build | Passed; Next 15.5.28; ten static pages |
| Mocked desktop Chrome | **18 passed**, 9.3 seconds |
| Mocked mobile Chrome | **18 passed**, 9.1 seconds |
| Actual backend Chrome desktop/mobile | **24 passed**, 19.6 seconds |
| Actual backend Edge desktop/mobile | **24 passed**, 19.7 seconds |
| Total browser executions | **84 passed**, 0 failures/skips; 36 mocked, 48 integrated |
| Complete fresh npm audit | 9 entries: 0 critical, 7 high, 2 moderate; exit 1 |
| Fresh production-only npm audit | Zero findings; exit 0 |
| Python compilation and Git whitespace | Passed |

No further dependency upgrade was made at checkpoint. Next 15.5.28, matching
React/React DOM 19.0.9, patched PostCSS 8.5.30 and sharp 0.35.5 resolve compatibly.
The targeted Next PostCSS override remains necessary and requires maintenance
until upstream safely updates its pinned dependency. Remaining development glob
and selector-parser risks and the production JWT/CORS/schema/startup/readiness
checks remain unresolved; the local commit is not a production release approval.

The fresh cached PostgreSQL 15.18 container was
`proppulse-test-m3f-review-20261015`, loopback 59433, tmpfs-only with no bind/named
volume mounts. Full tests used `proppulse_test_m3f_review`; browser fixtures used
`proppulse_test_m3f_review_browser`. Both databases ended with zero random test
schemas and advisory locks. Across **404 measured actual API requests**, all
thirteen table counts and ordered full-row fingerprints matched their baseline;
fixture counts remained 4 Events, 3 players, 15 props/offers/snapshots each,
24 logs, one each user/saved/slip/item, and zero fatigue/rankings/interactions.
Backend external HTTP attempts and integrated API external HTTP attempts were
both **zero**. Every browser case asserted zero unexpected external requests.
Development PostgreSQL was never connected to; credentials, backups and existing
data/volumes were preserved.

Preservation/audit logs remain ignored under `backend/data/odds_runs/`; browser
screenshots/traces/results, `.next`, dependencies, environments and caches are
excluded from the checkpoint. After evidence capture, the API was stopped and
only the disposable review container removed. Ports 8000/3199 had no listeners;
the three development containers remained stopped.

The ten-file checkpoint comprises both backend test files, the integrated browser
suite and two configurations, frontend manifest/lockfile/generated route-types
reference, and the two Phase 3F reports. Phase 3G is ready for separately scoped
planning, with the deployment blockers above retained; it was not begun.
