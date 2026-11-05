# Phase 9 Feature 10 — portfolio and deployment readiness

Date: October 23, 2026. Starting HEAD verified as `0eac644990350311e62e01846406b86ec8e38d76`. Feature 10 was left uncommitted at the implementation checkpoint; a subsequent explicit owner request authorizes one local Feature 10 commit. No provider refresh/spending, development database write/migration, push or deployment was performed.

**Security Stage 2 follow-up:** [Cookie sessions and API security](security-stage2-auth-api.md) supersedes the historical localStorage/JWT/dependency disposition below. Public deployment remains unapproved.

**Security Stage 3 follow-up:** [Provider-independent verification](security-stage3-production-verification.md) records the completed local Linux/HTTPS/gateway/recovery checks and remaining image/hosting gates. It supersedes historical build and hosting assumptions below; no platform is selected.

## Deliverables and presentation status

- [README](../README.md): recruiter-facing product/features, five supported sports, actual stack, engineering achievements, reliability limits, Windows setup/testing and links to operational details. Removed obsolete synthetic-data/ML accuracy/live-coverage claims. Preserved the pre-existing Node 24.22.1/major-24 requirement.
- [Architecture](architecture.md): one concise current overview with Mermaid, core entities, ingestion/identity normalization, observation/ingestion times, offer policy, exact-line research, authentication and implemented background boundaries.
- [Demo walkthrough](portfolio-demo.md): 3–5 minute narration, startup, authentication boundaries, offline Playwright replay/reset, suggested recording/screenshots and honest retained-data limitations. No curated video/gallery was created; automated test captures remain ignored.
- [Deployment update](milestone-3h-staging-recovery.md#current-deployment-guide): current provider-independent hosting requirements, environment reference, startup/migrations, health/readiness, secret handling and recovery. Extends existing deployment documentation rather than adding a competing deployment plan.

**Ready for a guided local portfolio demonstration with labeled offline fixtures.** A genuine retained-data segment needs a read-only preflight after the owner makes the stopped development PostgreSQL available. Public deployment is not ready: advisory remediation, hosting configuration and target-platform verification remain open. No claim of complete current-season coverage is made.

## Necessary implementation/configuration changes

1. Allowed CORS PATCH preflights so browser-based exact saved/slip edits can work across approved frontend/API origins. Untrusted origins remain denied; unauthenticated edits remain 401.
2. Added a default-deny backend Docker context and a non-root runtime UID. Runtime app/ingestion source, requirements and migrations are admitted; local secrets, provider data, tests, venvs, ML artifacts and backups are excluded. The pre-existing CA-certificate Dockerfile change is intact. This is source/context verification, not a successful new production-image build.
3. Aligned readiness with Alembic head `20261022_05`. Fixed revision 05's fresh-bootstrap duplicate-column failure by accepting existing compatible nullable columns while refusing incompatible shapes. Existing rows/evidence are never backfilled or reset. This changes migration implementation only; no development migration ran. Revision 05 downgrade remains destructive to exact saved selections and must not be used as routine rollback.
4. Corrected stale migration-test head assertions and current additive-response/null-price test assumptions. Fixed obsolete browser selectors/fixtures for the current Discover UI; assertions still check search, errors, URL identity and loading behavior.
5. Made the shared environment example usable from the local backend: localhost service URLs, safe refresh default, clear required/optional comments and ignored unrelated frontend dotenv entries. Production secret/origin validation remains active.
6. Removed hardcoded legacy login demo-account/weak-password prefills. Login now requests an environment-provisioned account without promising seeded personas.
7. Fixed Discover retaining the previous URL search when a user clears/types text and changes another filter before debounce. Filter changes now carry pending search text; desktop/mobile browser regression covers clearing immediately before sorting.
8. Expanded Git exclusions for private runtime/provider artifacts, environment variants, backups and recording directories. Already tracked reviewed mapping inputs remain tracked.

## Focused security review

| Area | Finding / disposition |
| --- | --- |
| Hardcoded secrets/client env | No real secret was introduced. Known local DB credentials and development JWT placeholders are explicitly local; production rejects weak JWT defaults. Only public API origin is exposed through NEXT_PUBLIC. Removed advertised legacy login credentials. No real env file contents were printed. |
| CORS | Confirmed missing PATCH; fixed with trusted/untrusted preflight and unauthenticated-edit regressions. Explicit production HTTPS origins still required. |
| Authentication/ownership | Reviewed bcrypt/JWT validation and current-user filters on bookmarks, exact selections and open slips. Existing ownership/persistence regressions execute in isolated fixtures. No ownership bypass identified in reviewed paths. |
| Session boundaries | Tokens remain in localStorage; XSS exposure, no server revocation/account recovery, seven-day development default and no gateway abuse limiter remain deployment considerations. No cookie session is claimed. |
| Development routes | Production app does not include the test integration server or its __test__ routes. Existing isolated test verifies 404. Docker context excludes tests. |
| Error leakage | Reviewed debug=False, sanitized validation errors and readiness/database failures; regression tests pass. Ingestion artifacts must remain private and use existing provider redaction. No new raw error response added. |
| Docker/artifact exposure | Missing ignore file could include env/provider artifacts; fixed. Effective context export admitted 84 source/config files and zero forbidden relative env/data/tests/venv/ML/cache paths. Non-root runtime configured; full runtime image/native dependency execution not verified. |
| Dependency security | Current registry checks described below; unresolved Python and build-tool findings block public release. No force audit fix, framework migration or speculative transitive override was applied. |

### Dependency evidence

**Stage 1 follow-up (October 23, 2026):** The historical results below are retained
as the Phase 9 checkpoint, not the current dependency disposition. See
[dependency remediation](security-stage1-dependencies.md) and
[npm verification](security-stage1-npm.md) for the reviewed constraints lock,
compatible updates, fresh-install regression evidence and remaining advisories.
The existing development environment was not upgraded. Public deployment remains
unapproved; dependency remediation does not close hosting/authentication/operations
requirements for later security stages.

Current npm audit: **three moderate development entries** (`postcss-selector-parser`, `postcss-nested`, `tailwindcss`) propagating the selector-parser advisory; **production-only audit: zero findings**. The suggested remediation changes Tailwind major version, so no untested styling/toolchain migration was made. See the [maintainer advisory](https://github.com/postcss/postcss-selector-parser/security/advisories/GHSA-rj75-hqrm-r3gf). The historical seven-finding report is not the current result.

A separate ignored audit venv queried pip-audit against **76 exact installed application-environment package versions**, including transitives. It reported **64 raw advisory entries across 11 packages**; repeated IDs/aliases occur, so this is not a count of 64 distinct exploitable application flaws. The direct requirements-only no-deps attempt was rejected because numpy/scipy are ranges; the installed-version audit then completed. It does not prove a clean requirements resolution on Linux.

| Installed package | Version | Raw entries |
| --- | --- | ---: |
| anyio | 4.13.0 | 2 |
| cryptography | 48.0.0 | 7 |
| ecdsa | 0.19.2 | 2 |
| pip | 25.0.1 | 12 |
| pyasn1 | 0.6.3 | 6 |
| python-dotenv | 1.0.1 | 2 |
| python-jose | 3.5.0 | 1 |
| python-multipart | 0.0.9 | 14 |
| scikit-learn | 1.4.2 | 2 |
| starlette | 0.37.2 | 14 |
| ujson | 5.12.1 | 2 |

The ASGI/parser dependency family needs a compatible FastAPI/Starlette upgrade and verification before internet exposure; overriding Starlette beyond FastAPI's supported range is not an acceptable quick fix. Some findings concern unused form/ML/build operations or asymmetric JWT keys, while the app pins HS256 with a private symmetric secret. That limits particular exposure but does not justify a blanket clean/security claim. Some reported entries have no fix version. Resolve runtime findings, distinguish build-only tools, and re-audit a clean target-platform installation before release. Application requirements (including pre-existing certifi) were preserved byte-for-byte; only the ignored audit tool environment was installed.

## Verification evidence

All application tests used the existing environment. Backend external HTTP transports were blocked; **zero external HTTP attempts** were recorded. Temporary PostgreSQL 15 used a cached image, random host port, loopback-only binding, tmpfs, memory/CPU/PID limits, no development mounts and an explicit `proppulse_test_feature10` database. Tests owned random schemas and cleaned them up. No development service was started.

| Check | Result |
| --- | --- |
| Focused security/saved selections before full suite | 19 + 31 passed |
| One full backend checkpoint | 1,110 discovered/run: 1,105 passed, 3 failed assertions, 2 skipped; not reported as an uninterrupted green suite |
| Corrections and focused backend reruns | Discover browse 20 passed; equivalence 8 passed; PostgreSQL readiness 13 passed; security/environment 20 passed after final config fix. The three full-suite failures are covered by passing focused reruns. No second full backend run. |
| PostgreSQL scope | 282 discovered PostgreSQL scenarios; two actual-artifact cases skipped because no authorized actual-statistics demo artifact was supplied. Fresh/repeated migration, metadata consistency, ownership/data integrity and readiness cases otherwise ran in the full checkpoint. |
| Migration graph | `alembic heads`: single `20261022_05`; fresh bootstrap/repeated head/model comparisons passed in isolated PostgreSQL. Development revision supplied by user was not queried/migrated. |
| Health/readiness | Actual app TestClient/lifespan in isolated PostgreSQL verified /health 200, /ready 200 and no create_all/refresh start; bad config/revision/unavailable DB cases tested. No new live development HTTP server was started. |
| Frontend Node tests | 116 passed, rerun after Discover change |
| TypeScript | Passed after final frontend change |
| Next.js production build | Passed after final frontend change; local existing dependencies/cache, no clean Linux/native image claim |
| Browser desktop/mobile | Final production build: **66 passed + 3 retained-development skips per configuration** (132 passed / 6 skipped combined); zero final browser failures |
| Docker ignore verification | Offline scratch COPY/export succeeded; effective context excludes private/runtime/test artifacts. Non-root source configured; new full backend runtime image not built. |
| npm registry audits | Full: three moderate dev entries (expected exit 1); production-only zero (exit 0). Initial sandbox registry failure retained separately, not counted as an audit result. |
| Python registry audit | Completed with findings (expected exit 1); exact installed graph, not requirements resolver/native build certification |
| Git/diff preservation | Starting patch/content hashes retained privately; final preservation and whitespace results recorded below |

Browser scenarios cover Discover server query contracts/filters/URL navigation, exact-line research/comparison, sport-specific season windows, source coverage, freshness/expiry, Saved Props, in-place slip edit rejection/success/reload and rejected login. Browser authentication state and mutation APIs are mocked; genuine successful browser login and real PostgreSQL writes through a browser are not claimed. Separate backend tests cover database behavior and ownership. Responsive checks include 375, 390, 430, 768, 1280, 1440 and 1920px; automated screenshots were visually inspected at desktop/mobile widths.

Earlier browser attempts found obsolete selectors/error/loading expectations and timed out; these were corrected before the final result. One run was interrupted after another obsolete assertion was found. These failed/partial attempts are retained as evidence and are not presented as passing. Three opt-in retained-development scenarios per browser configuration remain skipped, because development PostgreSQL is stopped and no read-only development API was launched.

Not run: actual retained-data SQL/API/browser walkthrough in this session; genuine current-provider or paid historical-odds checks; full new Linux backend image/native wheels; clean dependency installation; public HTTPS/CORS/gateway tests; live successful browser login; public deployment; current-host backup/restore; production load/cold-start, full accessibility, Firefox/WebKit. No lint gate is configured. Avoiding these unapproved/unavailable operations is deliberate, not evidence they pass.

## Coverage limitations and next steps

NBA 2026–27 provider access is not successfully verified. WNBA retained records stop July 22. NFL is limited to retained observations. MLB legacy exclusions and the Liam Hicks identity conflict remain. Source completeness and historical sportsbook movement are unknown/unverified. Development prices can be expired; no current/live coverage claim is made.

Before the genuine-data presentation segment, make retained PostgreSQL available under an explicitly read-only API and verify selected player/season URLs; otherwise use the documented offline replay with its invented-data label. Before public deployment, remediate/disposition dependencies, configure TLS/origins/secret manager/DB roles, add gateway abuse controls, rehearse migrations/restore on isolated staging and curate authorized genuine statistics. Hosting recommendation: Next.js service + FastAPI service + managed PostgreSQL; omit unused Redis and keep refresh off. No infrastructure was purchased or deployed.

## File ownership / Git separation

Pre-existing work was captured before edits under ignored `backend/data/odds_runs/feature10/baseline/`: exact file copies, SHA-256 manifest, complete starting patch and porcelain status. Initial index was empty.

- **Pre-existing + carefully integrated Feature 10:** `README.md` (Node requirement retained); `backend/Dockerfile` (CA install retained, non-root appended).
- **Pre-existing, unchanged byte-for-byte by Feature 10:** `backend/requirements.txt`, `backend/scripts/fetch_odds.py`, `backend/tests/test_milestone2_ingestion.py`.
- **Pre-existing untracked, unchanged byte-for-byte:** `docs/milestone-4a4-espn-collection-plan.md`, `docs/phase-5a-simplification-audit.md`, `frontend/.node-version`.
- **Feature 10 tracked edits:** `.env.example`, `.gitignore`, `backend/alembic/README.md`, `backend/alembic/versions/20261022_05_saved_selections.py`, `backend/app/config.py`, `backend/app/main.py`, `backend/app/services/schema_readiness.py`, `backend/tests/test_discover_browse.py`, `backend/tests/test_discover_equivalence.py`, `backend/tests/test_event_migration_postgres.py`, `backend/tests/test_ingestion_postgres.py`, `backend/tests/test_nba_evidence_migration_postgres.py`, `backend/tests/test_saved_selections.py`, `backend/tests/test_security_hardening.py`, `docs/milestone-3h-staging-recovery.md`, `frontend/e2e/discover-filters.spec.cjs`, `frontend/e2e/navigation.spec.cjs`, `frontend/src/app/discover/page.tsx`, `frontend/src/app/login/page.tsx`.
- **Feature 10 new files:** `backend/.dockerignore`, `docs/architecture.md`, `docs/portfolio-demo.md`, `docs/phase-9-feature-10-readiness.md`.

During implementation, no file was staged, committed, reset or pushed, and the expected HEAD remained unchanged. The subsequent authorized commit checkpoint includes only the 25 reviewed Feature 10 files, including the preserved shared README/Dockerfile edits. The six unrelated pre-existing files remain unchanged and uncommitted. Private baseline/audit/test outputs, approval/provider data, screenshots and build artifacts are excluded from Git.

## Final checkpoint disposition

Final desktop and touch/mobile production-browser runs each passed 66 scenarios,
with three opt-in retained-development checks skipped per run. Frontend tests
(116), TypeScript and production build passed after the Discover fix. Local
Markdown links resolve; Git diff whitespace passed (line-ending normalization
warnings only); at that implementation checkpoint, the index was empty and HEAD matched the requested checkpoint.
Six untouched protected files match starting SHA-256 hashes; the original README
Node requirement and Dockerfile CA-install edit remain integrated in the two
shared files. No other pre-existing change was edited.

Temporary test PostgreSQL and the owned production frontend were stopped after
verification; the database container was removed only after checking its ownership
label and confirming zero remaining random test schemas. The development database
was left stopped. Private evidence remains ignored under
`backend/data/odds_runs/feature10/`; it is not part of the public portfolio.
