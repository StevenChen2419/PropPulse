# Milestone 3G: security remediation and deployment hardening

Started October 16, 2026 at verified HEAD
`aa591b843c30acd35669b0dc4d1d1ba0a5b7002e`. The working tree was clean before
generated evidence. Reviewed application instructions, Phase 3B schema, Phase 3C
ingestion/bounded linkage, Phase 3D APIs, Phase 3E navigation, and both Phase 3F
integration/security reports. Some AGENTS architecture notes predate the checked-in
Alembic workflow; actual migrations are the source of truth.

## Security findings and implementation

Production and staging now require an explicit PostgreSQL URL, a non-default JWT
secret of at least 32 bytes with basic diversity/default checks, and explicit HTTPS
CORS origins. Generate a cryptographically random secret with at least 32 random
bytes; validation cannot prove entropy. Configuration errors expose field names
only. Settings representations hide database URLs, JWT secrets and provider keys.
HS256 is the only supported signing algorithm; tokens require exp/sub and a valid
UUID subject before querying PostgreSQL. Expired, malformed, wrongly signed and
unknown-user tokens fail authentication. Optional public personalization continues
to treat invalid credentials as anonymous.

Passwords retain bcrypt (existing hashes remain usable). New passwords require at
least eight characters and at most 72 UTF-8 bytes; verification rejects inputs over
72 bytes instead of silently truncating. Unknown emails incur bcrypt verification
against a dummy hash. Validation responses omit Pydantic input/context to avoid
echoing submitted credentials. User-specific APIs retain current-user ownership
filters; no identity provider or session architecture redesign was introduced.

Updated python-jose 3.3.0 to 3.5.0 within the existing major. The
[maintainer changelog](https://github.com/mpdavis/python-jose/blob/master/CHANGELOG.md)
records CVE-2024-33663/33664 fixes in 3.4.0 and sensitive key exception fixes in
3.5.0. HS256 application usage does not establish exploitability of every historical
JOSE issue; retaining the old security dependency was unnecessary.

Public liveness no longer returns retained refresh artifacts. Status-file read
failures and background refresh exceptions no longer interpolate raw exception
text/tracebacks into these surfaces. Framework debug mode stays explicitly off.
Ingestion status remains a research endpoint; this is not a complete audit of
all retained historical status artifacts or every Python dependency.

## Dependency evidence and outstanding advisories

Fresh `npm audit` reproduced nine vulnerable entries: seven high, two moderate,
zero critical. `npm audit --omit=dev` found zero. `npm ls --all` inspected the
installed graph, including extraneous optional platform binaries from the prior
installation. Removed unused eslint/eslint-config-next and the unconfigured
`next lint` script. No ESLint configuration or functional lint gate existed;
TypeScript and the existing tests remain the executable checks. This removes the
independent Next ESLint glob chain. No lint pass is claimed.

After removal: **seven entries: five high, two moderate; zero critical and zero
production-only findings**. No audit force-fix, incompatible override, Tailwind
migration, or PostCSS override removal. Next 15.5.28, React/React DOM 19.0.9,
PostCSS 8.5.30 and Tailwind 3.4.19 are retained.

| Outstanding entry | Installed | Severity | Reason retained |
| --- | --- | --- | --- |
| braces | 3.0.3 | high | No published patch; transitive Tailwind glob dependency |
| micromatch | 4.0.8 | high | Propagates braces finding; compatible version still depends on braces |
| fast-glob | 3.3.3 | high | Propagates micromatch/braces; required by Tailwind 3 |
| chokidar | 3.6.0 | high | Propagates braces; Tailwind watch tooling |
| tailwindcss | 3.4.19 | high | Upstream v3-lts; removing breaks the existing CSS build |
| postcss-selector-parser | 6.1.4 | moderate | Fix >=7.1.6 is outside declared major ranges |
| postcss-nested | 6.2.0 | moderate | Propagates selector-parser; Tailwind declares ^6.2.0 |

The [braces advisory](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm)
lists no patch for <=3.0.3. The
[selector advisory](https://github.com/advisories/GHSA-rj75-hqrm-r3gf) identifies
CPU exhaustion below 7.1.6. Registry metadata still labels Tailwind 3.4.19
`v3-lts`; latest is 4.3.3. Its
[supported upgrade guide](https://tailwindcss.com/docs/upgrade-guide) describes
breaking build/style/browser changes. A visual-parity Tailwind migration should
be a separate milestone; no major parser override is justified here.

Execution paths were inspected in installed code: Tailwind `lib/lib/content.js`
calls fast-glob/micromatch on repository content globs, and its selector utilities,
generateRules and expandApplyAtRules invoke selector-parser on classes/CSS.
The nesting wrapper requires postcss-nested when used; chokidar is used for watch
mode. `postcss.config.js` activates Tailwind/autoprefixer during Next builds.
Installation resolves these packages; use `npm ci --ignore-scripts` so dependency
lifecycle scripts do not execute. Next's own platform binaries must be verified
on the release platform. Production `next start` serves compiled assets; it does
not accept user CSS/globs through these build tools. A build still executes
repository code/configuration and must not run untrusted changes with secrets.

Required restriction until remediation: ephemeral unprivileged builders; reviewed
source/configuration; no production secrets, provider keys, database/network
access or Docker socket; CPU/memory/time quotas; read-only source and bounded
scratch space. Untrusted PR builds receive no privileged caches or publish tokens.
Allow registry/font downloads only through controlled build egress, then disable
egress for compilation where feasible (existing next/font downloads Google Fonts).
Promote the reviewed compiled artifact into a runtime image installed with
`npm ci --omit=dev --ignore-scripts`. Do not build after omitting Tailwind. Isolation
is a deployment requirement to review, not blanket acceptance of these findings.

## Startup, liveness and readiness

`/health` returns process liveness only. `/ready` returns 200 `ready` or 503 with
one bounded reason: configuration, database_unavailable, schema_revision or
schema_prerequisites. Responses are not cached and contain no driver messages,
URLs or credentials. Each check opens a pooled connection, uses a read-only
transaction and catalog queries, and rolls back on close. There are no application
table scans, data writes, provider calls, repairs, migration execution or refresh
starts. PostgreSQL connection timeout is three seconds, pool acquisition five
seconds, per-statement timeout two seconds, lock timeout one second. These are
individual bounds, not a promised total request deadline.

Expected revision is pinned in code to **20261014_02**, rather than accepting an
environment-specified revision that could bypass the gate. Checks cover required
tables/columns, primary/unique/foreign keys, Event column definitions, identity
checks/indexes, the restrictive Event FK, and the complete enabled immutable-link
trigger/function definition. A bounded catalog check also rejects NOT VALID
CHECK/FK constraints, whose definitions alone cannot establish integrity of older
rows. The deployment validator intentionally freezes the
current migration contract; future migrations must explicitly revise this contract.
No readiness path calls the migration's install-or-validate helper.

Production/staging lifespan refuses startup on invalid configuration or unavailable
schema. No environment runs `create_all()` at startup now. Development schema
bootstrap must use the reviewed migration workflow explicitly. Readiness rechecks
on every request, so failures are not permanently latched and restored databases
can recover without a probe cache expiry. If startup itself fails, the process
supervisor must retry after prerequisites recover. Refresh remains false by default
and in `.env.example`; lifespan calls start only when explicitly enabled. Existing
advisory locking, rate limits, credit floors, quotas and ingestion code are retained.

## Production settings example (placeholders only)

Supply through the hosting secret manager, not source files:

```dotenv
ENVIRONMENT=production
DATABASE_URL=postgresql://APP_USER:URL_ENCODED_PASSWORD@DB_HOST:5432/DB_NAME?sslmode=verify-full
JWT_SECRET=REPLACE_WITH_CRYPTOGRAPHICALLY_RANDOM_SECRET
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=60
CORS_ORIGINS=["https://FRONTEND_HOST"]
LIVE_REFRESH_ENABLED=false
NEXT_PUBLIC_API_URL=https://API_HOST
```

Placeholder values intentionally do not pass secret validation. CORS_ORIGINS is a
JSON array of exact origins, with no slash/path, credentials, wildcard, query or
fragment. Production requires HTTPS. Local defaults allow localhost/127.0.0.1:3000.
Use `ENVIRONMENT=test`, `_env_file=None`, explicit disposable DATABASE_URL and no
provider keys for tests. Provider credentials are unnecessary for serving stored
research. Never inject secrets into NEXT_PUBLIC variables. Build the frontend with
its actual public API URL; changing that value at runtime does not rebuild assets.

## Deployment, monitoring and recovery checklist

- Host Next with a supported Node runtime satisfying >=20.9 and FastAPI separately
  on supported Python; verify native packages on the target OS/architecture. No
  development reload flags, bind-mounted source or development Compose credentials.
- PostgreSQL 15, persistent encrypted storage, TLS certificate verification,
  least-privilege application role without DDL/ownership, restricted network ingress;
  separate migration role. Redis is not an application cache or rate limiter here.
- Take a consistent backup and record revision before an explicitly approved
  migration. Review the actual database adoption prerequisites; rehearse the
  existing Alembic upgrade in a restored disposable staging database. Run migrations
  as a separate release step, never from an API worker or readiness probe.
- Order startup: database healthy, reviewed schema migration completed, backend
  `/ready` succeeds, frontend configured against that backend, then route traffic.
  Use `/health` for liveness and `/ready` for startup/readiness with bounded probe
  frequency (for example every 30 seconds) and thresholds allowing transient failures.
- Terminate TLS at a trusted proxy; exact frontend origin allowlist, HTTPS redirects,
  secure host/proxy settings, HSTS after TLS validation, request/body/header size
  limits and connection/time limits. Strip Authorization and credentials from logs.
- Require distributed gateway/WAF limits on login/register and expensive research
  APIs, plus per-account/IP controls and operational alert thresholds. No fragile
  per-worker in-memory limiter was introduced. Public registration can still reveal
  email membership by success versus duplicate failure; suppressing that completely
  requires a separately reviewed verification/registration flow. Login errors stay
  generic and unknown-user password verification now incurs bcrypt cost.
- Alert on 5xx/readiness failures, auth failures/abuse, pool exhaustion, query latency,
  memory, worker restarts, disk, backup age and provider quota status. Restrict raw
  exception/ingestion log access and redact credentials in the logging pipeline.
- Keep provider refresh off during serving/staging probes. Separately authorize any
  scheduler, fund quotas, assign one owner, configure existing request/credit caps,
  monitor advisory-lock contention and missing/stale market coverage.
- Backups: encrypted scheduled snapshots plus WAL/PITR if required by the chosen
  RPO/RTO; separate access credentials and retention. Restore into a new isolated
  database, verify revision/constraints/trigger, counts/identities, saved/slip
  selections and representative APIs, and record actual recovery duration. A backup
  existing is insufficient; no production backup or restore was performed here.
- Rotate JWT and database/provider secrets via the secret manager. Current JWT
  rotation invalidates existing tokens; plan reauthentication and rollback access.
  No multi-key grace period was added. Do not revert to a default secret.
- Roll back application artifacts to a reviewed schema-compatible release while
  retaining additive Event schema/data; the migrations explicitly reject destructive
  downgrades. If corruption requires restore, stop writes/schedulers and rehearse
  the restore/cutover procedure. Retain previous image/configuration references.

## Representative performance measurements

`backend/tests/profile_inventory.py` creates only a guarded, random disposable
schema. Fixtures: 120 Events, 240 players, 6,000 props (100 unlinked, including
conflicting legacy namespaces), 12,000 offers including expired and alternate-line
offers, 12,000 snapshots, 4,800 game logs, one synthetic user, 20 saved selections
and 10 slip items. This resembles inventory size/relationships, not a copy of
private development inventory or provider data. Both profiles assert legacy
ambiguity rejection and block all external HTTP (zero attempts).

Timing uses actual API serialization/authentication through ASGI TestClient, three
sequential requests per endpoint; median is shown. These are local single-client
measurements with warm database caches, not network latency, concurrent load or
capacity certification. Other verification ran concurrently, so before/after wall
times include machine contention; query-count reduction is deterministic.

| API | Before median ms | After median ms | After SQL queries | SQL rows returned | Plan scan visits* | Python peak MiB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Upcoming Games, limit 20 | 1,411.89 | 1,380.21 | 3 | 17,520 | 37,200 | 67.15 |
| Event Detail, 50 props | 99.71 | 55.89 | 7 | 143 | 934 | 1.32 |
| Feed, page 1 | 8,529.12 | 1,184.34 | 5 | 11,481 | 30,881 | 58.30 |
| Feed, offset 20 | 5,976.41 | 1,180.05 | 5 | 11,481 | 30,881 | 58.30 |
| Discover, page 1 | 5,856.17 | 5,711.61 | 2 | 15,960 | 35,520 | 111.02 |
| Discover, offset 20 | 5,785.66 | 5,666.54 | 2 | 15,960 | 35,520 | 111.38 |
| Player Research | 28.11 | 31.75 | 7 | 76 | 6,656 | 0.41 |
| Ingestion Status | 1,377.41 | 1,360.08 | 1 | 11,400 | 30,360 | 58.28 |
| Saved hydration, 20 items | 127.55 | 120.19 | 102 | 121 | 7,341 | 0.34 |
| Slip hydration, 10 items | 63.15 | 68.36 | 53 | 62 | 3,672 | 0.22 |

SQL query counts include authenticated user lookup; SQL rows returned count raw
joined/duplicate rows transferred, not distinct props. Separate tracemalloc requests
measure peak traced Python allocations, excluding PostgreSQL/native allocations,
total RSS and process lifetime peaks. A separate timing pass excludes tracing.

*Scan visits are a representative replay estimate: EXPLAIN (ANALYZE, BUFFERS,
FORMAT JSON) executes each unique captured SELECT with its first captured bind
values, then weights scan-node actual rows plus removed-by-filter rows by loops
and occurrence count. Index/heap visits can count the same row twice; plans for
later varying per-item binds can differ. These are not exact distinct physical
rows scanned for every original request. Complete SQL/plans and all three times
are retained in ignored profile-before/after JSON; the metric avoids pretending
that a SQL result row count measures work performed.

Plans show sequential scans of the 6,000-prop inventory and 12,000-offer table
for broad browsing, appropriate to retrieving most rows but expensive in Python.
Discover reads 4,560 eligible-player logs before scoring 5,700 eligible candidates.
Research still scans props to find one player's 25 candidates, then uses the
snapshot composite index and game-log player index. Saved/slip repeatedly look up
individual props, players, Events and fatigue. Their N+1 pattern remains visible.

Implemented one small optimization: ranking loads the existing unique per-player
fatigue rows in one query and reuses them for each candidate. Feed drops from
**5,704 to 5 SQL statements** and Event Detail from **56 to 7**. Existing weights,
reasons, scoring, stable ordering and fatigue calculations are unchanged; focused
regressions cover scored/missing fatigue, repeated players and empty candidates.
No schema/index migration was introduced.

Both Feed and Discover return 20 of 5,700 eligible results on pages 1 and 2,
but offsets do not bound inventory work. Event-specific Feed remains deliberately
unpaginated; the fixture Event returns all 50. Upcoming Games returns its 20-card
limit only after inventory/collision resolution. No pagination or ambiguity rule
was weakened. A subsequent performance milestone should design indexed identity
resolution, bounded history/scoring work, a props.player_id access path and eager
saved/slip hydration with identity/price/sample regression coverage. Discover's
~5.7 seconds/111 MiB and broad inventory scans remain release capacity concerns.
Redis and ranking/model redesign are not proposed as shortcuts.

## Verification

Ignored local evidence lives in `backend/data/odds_runs/m3g/`.

| Executed check | Final result |
| --- | --- |
| Full backend, external HTTP blocked | **528 passed**, including **140 genuine PostgreSQL** cases; 0 failures/errors/skips; 88.009 seconds; exit 0 |
| External backend HTTP attempts | **0** |
| Frontend Node tests | **59 passed**, 0 failures/cancellations/skips; exit 0 |
| TypeScript `npx tsc --noEmit` | Passed; exit 0 |
| Production `npm run build` | Passed; Next 15.5.28; ten static pages; exit 0 |
| Existing mocked Chrome desktop | **18 passed**; 11.4 seconds |
| Existing mocked Chrome mobile | **18 passed**; 10.2 seconds |
| Final real-backend Chrome desktop/mobile | **24 passed**; 19.8 seconds |
| Final real-backend Edge desktop/mobile | **24 passed**; 21.1 seconds |
| Browser preservation | All 13 application tables unchanged; external provider HTTP attempts 0 |
| Complete `npm audit` | Exit 1: **7 entries**, 5 high / 2 moderate / 0 critical |
| `npm audit --omit=dev` | Exit 0: **zero findings** |
| `npm ls`, `npm ls --all` | Passed; no invalid required dependencies; optional platform/peer omissions are not failures |
| Python compileall: app/scripts/tests/alembic | Passed; exit 0 |
| Git tracked whitespace and changed/new text whitespace | Passed; no trailing whitespace in all 22 changed/new text files |

Final browser matrix: **84 passing executions** (36 mocked + 48 integrated),
zero skipped. Earlier reruns are not added to this matrix total. Edge is another
Chromium channel, not evidence of an independent browser engine. No standalone
ESLint run is claimed after removal of the unconfigured tooling.

PostgreSQL **15.18** ran in `proppulse-test-m3g-20261016`, loopback port 58973,
with tmpfs storage and no development volume/bind mounts. Backend test and profile
schemas were random and removed after each fixture. Browser fixtures used separate
empty `proppulse_test_m3g_browser` and `proppulse_test_m3g_browser_final` databases.
Their application role was SELECT-only. Neither profiling nor tests used the
development database. Only disposable fixture migrations ran; no operational
migration, backfill, ingestion or restore was performed.

Cleanup verified zero remaining random test schemas and zero advisory locks before
removing only the exact container created for this task. Both local test-server
ports (8000 and 3199) were clear afterward. HEAD remains the expected 3F commit;
all 22 implementation/documentation files remain uncommitted for review.

Browser integration retains Phase 3F's test-only wrapper: normal lifespan is off,
application sessions have a PostgreSQL SELECT-only role, HTTP transports are
blocked, and scenario mutation uses a separate fixture administrator. Production
startup/readiness is tested independently against migrated random PostgreSQL
schemas; browser fixture setup is not a production migration/readiness exercise.
Final full-row fingerprints for all thirteen browser application tables remained
identical, including saved/slip identities, prices, timestamps and lines.

Earlier attempts are retained in ignored logs: an initial backend run failed a
new configuration test because it inherited the deliberately supplied test URL;
the test now clears its environment explicitly. A new login test initially used
the email-validator-reserved `.invalid` TLD; it now uses a syntactically valid
synthetic example.com address without making any network request. The already
running suite retained the old fixture until its next process start. These test
fixture errors are distinct from application behavior; final results below refer
to the corrected sources. No failed run is counted as passing.

## Changed files

Independent read-only review found one readiness gap: SQLAlchemy's reflected
constraint definition can match even when PostgreSQL has not validated older rows.
The catalog check and two disposable regressions address that finding without
changing the frozen migration. No other confirmed review finding remained.

| Area | Files |
| --- | --- |
| Configuration/startup | `.env.example`, `backend/app/config.py`, `backend/app/database.py`, `backend/app/main.py` |
| Readiness | `backend/app/services/readiness_service.py`, `backend/app/services/schema_readiness.py` |
| Authentication | `backend/app/auth.py`, `backend/app/routers/users.py`, `backend/app/schemas.py`, `backend/requirements.txt` |
| Exception exposure | `backend/app/routers/props.py`, `backend/app/routers/rankings.py`, `backend/app/services/live_refresh_service.py` |
| Measured optimization | `backend/app/services/ranking_service.py` |
| Isolated checks/profile | `backend/tests/test_security_hardening.py`, `backend/tests/test_readiness_postgres.py`, `backend/tests/test_ranking_batch.py`, `backend/tests/profile_inventory.py` |
| Development tooling | `frontend/package.json`, `frontend/package-lock.json` |
| Documentation | `docs/security-3f-audit.md`, `docs/milestone-3g-security-hardening.md` |

Lockfile comparison shows zero changes to surviving package versions, zero added
package entries and 271 removed package entries. npm also normalizes retained
lockfile metadata; the large textual diff is not a framework/style migration.

## Release assessment

Engineering review can assess the hardened startup/authentication gates and the
measured performance evidence. This does **not** establish production readiness.
Remaining release decisions/blockers: explicit isolated-build controls for the
seven development findings; inventory/Discover capacity limits; gateway abuse
controls and registration enumeration policy; staging migration/startup rehearsal;
target-platform/native dependency verification; broader Python supply-chain review;
TLS/origin/secret configuration; production monitoring and a timed backup restore.
Independent Firefox/WebKit, accessibility audits, live-provider freshness, load
testing and production deployment/restore checks were not run. No operational
migration was applied. A separate staging deployment review is warranted before
traffic or any funded provider scheduler is enabled.

The implementation stage did not authorize deployment, operational migrations,
Event backfill, development database access, provider requests, refresh enablement,
commits or pushes. The subsequent user-authorized local checkpoint is recorded below.
Production readiness requires a separate staging/deployment review, dependency
isolation acceptance, abuse protection and backup/restore evidence.

## Final review and authorized local checkpoint

The checkpoint began at expected HEAD
`aa591b843c30acd35669b0dc4d1d1ba0a5b7002e` with the same 22 implementation,
test, dependency and documentation files. Applicable parent/application instructions,
all changed/untracked source and documentation, complete tracked diff and the full
lockfile graph were reviewed. Independent read-only review confirmed the previous
NOT VALID constraint fix and found one additional readiness defect.

A failed concurrent rebuild of the unique users.email index leaves an index that
SQLAlchemy reflects as unique despite PostgreSQL marking it unusable. The new
disposable regression reproduced readiness incorrectly returning ready. Readiness
now reads `pg_index.indisvalid`, `indisready` and `indislive`, rejects unusable named
prerequisites, and excludes unusable indexes from uniqueness validation. The test
also renames the failed index to verify that its name cannot bypass validation.
This is a catalog-only check; frozen migrations, production data, authentication
flow, scoring and schema are unchanged. Independent re-review found no remaining
actionable defect. All 13 focused PostgreSQL readiness cases pass.

The lockfile review confirmed zero surviving package version changes, zero added
entries and 271 removals. Retained metadata changes are limited to the root
development dependencies and one optional/devOptional flag normalization. The
Next PostCSS override remains unchanged. No package install, force audit fix,
unsupported override or Tailwind migration was performed at this checkpoint.

Fresh checkpoint results supersede the implementation-stage totals above:

| Check | Actual final checkpoint result |
| --- | --- |
| Full backend with blocked external HTTP | **529 passed**, 0 failures/errors/skips; **83.183 seconds**; exit 0 |
| Genuine PostgreSQL cases included above | **141 passed**, PostgreSQL **15.18** |
| Backend external HTTP attempts | **0** |
| Frontend Node tests | **59 passed**, 0 failures/cancellations/skips; exit 0 |
| TypeScript | Passed; exit 0 |
| Production Next.js build | Passed; Next 15.5.28; ten static pages; exit 0 |
| Mocked Chrome desktop | **18 passed**, 9.0 seconds |
| Mocked Chrome mobile | **18 passed**, 8.3 seconds |
| Real-backend Chrome desktop/mobile | **24 passed**, 18.2 seconds |
| Real-backend Edge desktop/mobile | **24 passed**, 18.1 seconds |
| Total browser matrix | **84 passed**, 0 failures/skips; 36 mocked + 48 integrated |
| Complete npm audit | **7 development entries: 5 high, 2 moderate, 0 critical**; expected exit 1 |
| Production-only npm audit | **Zero findings**; exit 0 |
| Installed dependency graph, npm ls --all | Passed; exit 0 |
| Python compilation and Git whitespace | Passed |
| Browser full-row preservation | All thirteen tables unchanged; external HTTP attempts 0 |

This run used cached PostgreSQL 15.18 in
`proppulse-test-m3g-checkpoint-20261016`, loopback port 58974, temporary test-only
trust and tmpfs storage without development bind/named-volume mounts. Backend
fixtures used random schemas in `proppulse_test_m3g_checkpoint`; browsers used a
separate empty `proppulse_test_m3g_checkpoint_browser` database with SELECT-only
application sessions. Zero random test schemas and advisory locks remained.
Only synthetic disposable fixture migrations/scenarios ran; no development
connection, operational migration, Event backfill, ingestion or provider call ran.
Ignored evidence is under `backend/data/odds_runs/m3g-checkpoint/`.

Representative performance was not repeated: the only checkpoint implementation
change concerns readiness catalogs. The earlier 6,000-prop synthetic measurements
remain observations: Feed 5,704 to 5 statements and median 8.53 to 1.18 seconds;
Discover about 5.7 seconds and 111 MiB, with inventory work still preceding paging.
No new capacity claim or performance optimization is introduced here.

The user authorized exactly one local commit:
`feat: harden security, database readiness and feed performance`.
Its 22 files exclude environment secrets, provider responses, local evidence,
backups, disposable data, screenshots/traces, dependencies, build output and
caches. No push, deployment, history rewrite or next milestone is authorized.
Outstanding release blockers above remain applicable; recommended next work is a
separately scoped staging-readiness review and bounded-inventory performance plan.
