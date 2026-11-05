# Milestone 3H: staging readiness and recovery rehearsal

**Historical evidence:** sections before “Current deployment guide” describe the
October 16 rehearsal and its then-current schema, dependencies and authentication.
They are retained for traceability, not current release instructions. Use the
provider-independent guide below and the [Stage 3 verification matrix](security-stage3-production-verification.md)
for the current release requirements and measured results.

October 16, 2026; starting HEAD `1286f50eb25631667783d649fce93ea64c7b1dea`,
initially clean. Reviewed parent/application AGENTS.md, Phase 3F integration and
security reports, Phase 3G hardening report, actual manifests, migrations,
configuration, lifespan, readiness, authentication and browser harness. Older
AGENTS architecture notes predate Alembic; the checked-in workflow is authoritative.
This is disposable local release evidence, not permission to deploy or to migrate
development. The implementation initially remained uncommitted; a subsequent
explicit final-review request authorizes one local checkpoint, never a push.

## Minimum deployment and configuration

Two application processes and PostgreSQL 15 suffice: Next.js `npm start` and
FastAPI/Uvicorn without reload, behind a trusted TLS gateway. Redis is unused by
current serving/cache/abuse controls and is not required. No scheduler is required
to serve stored research; freshness rules still make expired prices unavailable.
The repository Compose file is a development convenience (reload, source mounts,
local credentials), not a production deployment specification. The current backend
Dockerfile runs as root and includes build tooling; it requires a reviewed runtime
image/non-root identity before release. No new deployment platform was introduced.

Frontend: maintained Node satisfying >=20.9, npm lockfile; actual checks used Node
24.15.0/npm 11.12.1, Next 15.5.28. Backend: Python 3.11 is the Dockerfile baseline;
use a supported interpreter with requirements/native wheels verified for the target
platform. Existing local Python/runtime verification does not certify that image.
The local rehearsal used Python 3.12.10. Backend requirements include experimental
ML packages; no dependency pruning or
complete Python advisory audit was performed in 3H.

| Setting | Stage and handling |
| --- | --- |
| `NEXT_PUBLIC_API_URL` | Public build-time API origin, embedded in client JS; rebuild to change it. Never include credentials |
| `NEXT_TELEMETRY_DISABLED=1` | Builder/runtime policy; used in frontend verification |
| `ENVIRONMENT=staging` or `production` | Runtime; enables strict configuration and startup readiness gates |
| `DATABASE_URL` | Runtime secret, explicit PostgreSQL URL; URL-encode credentials; verified TLS outside local rehearsal |
| `JWT_SECRET` | Runtime secret, cryptographically random >=32 random bytes; retain across normal releases/restores, independent secret-manager backup |
| `JWT_ALGORITHM=HS256`, `JWT_EXPIRE_MINUTES=60` | Explicit runtime security policy; expiry example requires owner acceptance; default is seven days |
| `CORS_ORIGINS` | Runtime JSON exact-origin array, HTTPS required in staging/production; no wildcard/path/trailing slash |
| `LIVE_REFRESH_ENABLED=false` | Explicit runtime safety requirement; no provider key required for stored research |
| Provider keys/quota settings | Supply only to separately authorized ingestion owner; absent/empty throughout rehearsal |

Settings normally read `.env` relative to the working directory. Deploy into a clean
runtime directory without developer env files. The rehearsal constructs settings
with `_env_file=None` before application import; it replaces configuration input,
not the lifespan, routes, dependencies, schema gate or refresh implementation.
Its staging origin `https://rehearsal.invalid` is an explicit test-only origin;
local transport is HTTP on loopback. This does **not** verify public TLS or database
TLS. Remote DB connections require `sslmode=verify-full` and trusted CA/hostname;
the code validates PostgreSQL configuration but does not enforce TLS policy itself.

Use encrypted persistent DB storage and backups, restricted network ingress, a
separate migration/owner role, and an application role with necessary DML/SELECT
but no DDL, schema ownership or superuser privileges. Public schema CREATE must
not be granted to the application. The rehearsal's reader role is stricter:
SELECT only and default read-only transactions. It verifies login/read-only
research, not production registration/preferences/saved/slip write privileges.

## Migration, startup and probes

1. Record reviewed source/configuration/artifact digests and current DB revision.
   Stop ingestion and coordinate writes; take and verify a fresh backup before an
   authorized upgrade. Confirm target identity without printing its secret URL.
2. Wait for PostgreSQL TCP readiness. Use the migration role as a separate release
   job from `backend`: `python -m alembic -c alembic.ini current`,
   `python -m alembic -c alembic.ini upgrade 20261014_02`, then `current`.
   These are operator instructions, never commands against development here.
3. On empty databases, revision 01 bootstraps current metadata; revision 02 installs
   or validates Event constraints/linkage/trigger. Initial adoption depends on
   current models, so future schema edits need explicit new revisions and an
   updated readiness contract. No Event backfill occurs. Do not `stamp head` to
   bypass prerequisites; online migrations only. Repeated upgrade is idempotent.
4. Start `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`
   behind the selected gateway, without reload. Restrict trusted proxy addresses
   explicitly in the eventual hosting command; prevent direct public backend ingress.
5. Route traffic only after `/ready` returns 200; start the frontend built for this
   API origin and validate the integrated UI. A supervisor must retry failed startup
   after prerequisites recover. API startup never invokes migrations or `create_all`.

`/health` is process liveness only. `/ready` is uncached (no-store), read-only,
returns 200 ready or 503 configuration/database_unavailable/schema_revision/
schema_prerequisites, and does not expose raw driver diagnostics. Expected revision
is pinned in code at `20261014_02`. Required catalog definitions, validated CHECK/FK
constraints, required usable indexes, Event FK and complete immutable-link trigger
definition must pass. Readiness neither repairs schema nor starts providers.
Use bounded probes (initial proposal: 30s interval and three failure threshold).
Connect/pool/statement/lock limits are separate 3s/5s/2s/1s bounds, not a complete
request deadline. Normal research queries do not inherit the readiness query limit.

## Reproduce the disposable rehearsal

Prerequisites: working Docker engine, **cached** `postgres:15-alpine`, existing
Python venv and frontend dependencies, installed Chrome and Edge. Do not use
Compose or the development DB. The runner never accepts an external database URL.
It creates a random labelled container, publishes PostgreSQL only to a dynamically
assigned loopback port, allocates tmpfs storage, and caps PostgreSQL at one CPU,
512 MiB RAM and 128 PIDs. It uses disposable trust authentication on loopback;
this is not a production credential model. No host bind or named volume is used.
All Docker calls explicitly select the local Windows named pipe (Unix local socket
on that platform), ignoring inherited contexts/remote endpoints. Inherited `PG*`,
`DOCKER_*` and PostgreSQL test URLs are removed before app/subprocess imports;
this prevents libpq host-address/service overrides from redirecting the explicit
loopback target. The private server mode independently validates the container's
ID/name/label, exact published loopback port and tmpfs storage, and allowlists only
the restored reader URL and two deliberate invalid-configuration test targets.
Loopback probe HTTP bypasses inherited proxy configuration.

Build the frontend with `NEXT_PUBLIC_API_URL=http://localhost:8000` and telemetry
disabled; use `npm test`, `npx tsc --noEmit`, `npm run build` from frontend. Then:

```powershell
Set-Location backend
.\venv\Scripts\python.exe tests\rehearse_release.py --browsers
```

Omit `--browsers` for recovery/startup/full-backend checks only. Browser mode
requires ports 8000/3199 free and refuses occupied listeners; it never stops a
preexisting service. Evidence and the synthetic dump are overwritten only inside
ignored `backend/data/odds_runs/m3h/`. Retain a copy elsewhere if comparing runs.
The final report has `completed` and `container_removed` flags; a failed run is
not a successful rehearsal. Process cleanup precedes exact-ID/name/label checked
container removal, with nested cleanup/report finalizers. After an interrupted
host, inspect the recorded random container name, verify its rehearsal label and
resolve its exact ID before manual removal; do not
delete broad names, volumes or other containers.
Timed-out commands kill only their spawned PID tree (`taskkill /PID /T /F` on
Windows), and owned API/browser processes receive the same cleanup. If a Node
parent crashes first and leaves a descendant holding a pipe/listener, the exited
parent's tree cannot reliably be recovered by this PID-based cleanup. Treat that
run as failed, inspect process ancestry before stopping an orphan, and confirm
ports 8000/3199 are free before rerunning. No broad process-name kill is permitted;
a Windows job-object supervisor is not implemented or certified here.

All app imports receive explicit synthetic settings before engine construction.
Source, restore, suite and browser databases are distinct new databases in this
container. The source is initialized through Alembic 01 then 02, never `create_all`
in API startup. Fixtures cover every application table: Event, linked and legacy
props, player, nullable-price offer, snapshot, logs, bcrypt user/preferences,
saved prop, Under/FanDuel/19.5 slip item, interaction, fatigue and ranking. These
are test data only, not claims of provider-backed coverage or scoring validation.

Equivalent backup/restore commands, with the generated container/database names:

```powershell
docker exec CONTAINER pg_dump -U rehearsal -Fc --no-owner --no-acl -f /tmp/m3h.dump proppulse_test_m3h_source
docker cp CONTAINER:/tmp/m3h.dump backend/data/odds_runs/m3h/recovery-fixture.dump
docker exec CONTAINER pg_restore -U rehearsal --exit-on-error --single-transaction --no-owner --no-acl -d proppulse_test_m3h_restore /tmp/m3h.dump
```

Restore target is created empty beforehand. No `--clean`, existing DB overwrite,
development backup, or development credentials are involved. Ordered complete-row
JSON SHA-256 fingerprints and counts cover all 13 application tables plus Alembic
revision, including UUIDs, timestamps, hashes, JSON/arrays and selected book/side/
line. Restored CHECK/FK validation is inspected, immutable Event clearing is
challenged and rejected with SQLSTATE 23514, and readiness validates the contract.
Custom dump excludes ownership/ACL; deployment roles and grants must be separately
recreated/reviewed. Signing secrets, external files, extension/OS dependencies and
WAL/PITR are outside this logical fixture backup. This is same-version single-node
recovery, not a failover, cross-major upgrade, concurrent-write or capacity test.

## Actual production-path verification

The separate rehearsal process loads actual `app.main:app` and Uvicorn with
`lifespan=on`, ENVIRONMENT=staging, explicit synthetic configuration and a genuine
PostgreSQL SELECT-only role. It adds no test routes or dependency overrides.
Outbound HTTP transports, non-loopback Python socket connects and subprocess
creation are blocked; counters and observed SQL verbs are recorded outside the
application. Normal refresh code remains present with refresh explicitly disabled.
The immutable-link/NOT VALID/invalid-index challenges are performed by the
disposable administrator, never the API reader.

Checks cover missing/default secrets, non-PostgreSQL/unavailable DB configuration,
incompatible revision and invalid prerequisites; successful startup follows repair.
While running, `/ready` rejects a NOT VALID Event check, a missing required index
and a genuinely failed concurrent unique email index build, then recovers after
validation/rebuild. Real bcrypt login, retained-key JWT compatibility, identity,
saved/slip hydration, Feed, Discover, Games, Event and player research are checked.
Read-only requests preserve the restored baseline. Test manifest routes return 404.
The browser matrix separately retains its existing lifespan-off fixture/scenario
server; its results must not be confused with this production startup evidence.

## Build, gateway and operational release gates

See [build isolation and exact dependency evidence](milestone-3h-build-security.md)
and [gateway/authentication review](milestone-3h-gateway-review.md). Seven dev
entries (five high/two moderate) remain; isolation does not remediate advisories.
No Tailwind 4 migration, incompatible override or dependency change was made.
The host build is functional evidence, not an ephemeral unprivileged/no-egress
builder certification. A clean lockfile install, target-platform minimal runtime,
resource/egress boundary enforcement, protected PR/publisher separation and
artifact digest/signing/provenance acceptance remain release gates. Do not give
untrusted builds production secrets, database access or Docker socket privileges.

The focused application fix rolls back registration commit integrity errors and
returns a sanitized 400; three regressions cover failure, duplicate and success.
Email enumeration still exists through registration's status/token contract.
Choose restricted registration or a reviewed uniform verification flow before
public release. Shared gateway abuse/rate/in-flight/body/header/timeout controls,
trusted proxy identity, TLS, logging redaction and query cancellation must be
implemented/tested by the hosting owner. No unreliable per-process limiter was added.

Log route/status/duration/request ID and bounded error class, never credentials,
Authorization or request bodies. Restrict retained ingestion/exception logs.
Alert on readiness/5xx, auth abuse, database pool/query latency, RSS/restarts,
disk/backup age/restore failures and provider credit/freshness state. Monitoring
and redaction delivery were reviewed, not deployed. Keep refresh off; any later
ingestion scheduler needs explicit authorization, a single owner, quota floors,
per-run caps and existing advisory locks. No providers or ingestion ran here.

## Performance acceptance for the next bounded-inventory milestone

Phase 3G baseline is carried forward, not remeasured or redesigned: at 6,000
synthetic props Feed ~1.18s, Discover ~5.7s/111 MiB traced Python peak,
Upcoming Games ~1.38s. Saved 20/slip 10 hydration use 102/53 queries. Pagination
currently limits output, not inventory work; Event Feed intentionally remains
unpaginated. No scoring/fatigue/identity/selection semantics changed in 3H.

Proposed acceptance targets for a separately scoped optimization on the same
6,000-prop fixture, fixed machine/resources and warmed DB, at least 30 requests
per endpoint (timing pass separate from tracing):

| Surface | Target |
| --- | --- |
| Feed first/offset page, Upcoming Games 20 | Median <=500ms, p95 <=1s at one client |
| Discover first/offset page | Median <=1s, p95 <=2s; traced peak <=64 MiB |
| Saved 20 / slip 10 | <=10 SQL statements each; statement growth <=2 when item counts double |
| Event detail / player research | p95 <=250ms on existing comparable small responses |
| Bounded inventory work | Explicit query-row/history budgets and plans; increasing inventory 6k to 12k must not double work for fixed-size pages |
| Concurrent acceptance | Five clients for 5 minutes: no 5xx, stable post-warmup RSS (<=10% drift), bounded queue and declared overload response |

These are future release criteria, not achieved performance or capacity promises.
Document candidate-retrieval/ranking equivalence before bounding work. Preserve
exact Event identity and legacy collision safety, offer expiry/equivalent lines,
history denominators, stable ranking order and saved/slip choices. Benchmark at
6k/12k and review query plans/total RSS; tracemalloc alone omits native/DB memory.

## Release checklist and rollback

Require successful reviewed migrations, startup/readiness, recovery preservation,
full regressions, current audits/risk acceptance, isolated artifact packaging,
TLS/gateway abuse and timeout tests, monitoring ownership and a recovery exercise
on the eventual hosting platform. Set operational RPO/RTO: this tiny fixture's
duration is not a production RTO. Use encrypted scheduled backups, retention and
WAL/PITR if the chosen RPO needs it; protect backup and signing-key access separately.

Record previous immutable artifact/configuration references. Roll back application
artifacts only to a schema-compatible release while retaining additive schema and
Events. These migrations deliberately refuse destructive downgrade. For corruption,
stop writes/refresh, restore to a new DB, verify as above, reconcile post-backup
writes and explicitly authorize traffic cutover. Do not overwrite the old DB or
rotate JWT secrets as an incidental rollback; rotation invalidates active tokens.

## Execution results and limits

Final rehearsal completed with `completed=true`, `container_removed=true`.
PostgreSQL **15.18**, cached image ID
`sha256:df7bca0066e6f60cc3dd32faa70caddec20e2c22b58932f79498e5704b23854a`;
final checkpoint container `proppulse-test-m3h-a53f78051af8` is removed.

| Executed verification | Final result |
| --- | --- |
| Empty initialization, explicit 01 then 02 upgrade | Passed; final revision `20261014_02`; prerequisites/trigger valid |
| Backup | **30,808 bytes**, **0.160s** including local copy; custom-format logical dump |
| Restore into second new database | **0.117s** for pg_restore subprocess; exit 0, single transaction |
| Preservation | All 13 application tables plus revision: counts/full-row SHA-256 identical before backup, after restore and after API reads |
| Restored integrity | Validated CHECK/FK constraints, required indexes and trigger/readiness passed; trigger rejects clearing linked Event with 23514 |
| Actual lifespan refusal | Missing/default JWT, SQLite configuration, unreachable PostgreSQL, incompatible revision and NOT VALID prerequisites refused startup |
| Running readiness deterioration/recovery | NOT VALID Event check, missing Event-link index, genuinely failed concurrent unique email index: 503; repaired prerequisites: 200 |
| Liveness and production route surface | `/health` 200; `/ready` 200/no-store; test manifest 404 |
| Restored authentication/research | Bcrypt login and source-key signed JWT accepted; me/saved/slip/feed/discover/games/Event/player research all 200; Under/FanDuel/19.5 retained |
| Production process observation | Zero SQL writes, subprocess attempts, refresh threads, external HTTP/non-loopback socket attempts; refresh false |
| Full backend suite, disposable PostgreSQL | **537 passed**, including **141 PostgreSQL scenarios**, zero failures/errors/skips; unittest **81.794s**, subprocess wall **85.090s** |
| Backend provider HTTP | **0 attempts** |
| Frontend units | **59 passed**, no failures/skips/cancellations; 1.520s |
| TypeScript and production frontend build | Both passed; ten static pages; existing Windows installation |
| Mocked browser Chrome desktop/mobile | **18 + 18 passed**, 8.3s / 7.8s |
| Real-backend browser Chrome desktop/mobile | **24 passed**, 17.2s |
| Real-backend browser Edge desktop/mobile | **24 passed**, 17.4s |
| Browser total/preservation | **84 passed**, zero skips; all fixture tables unchanged, provider HTTP attempts 0; browser cases assert no unexpected external requests |
| Complete / production npm audit | Exit 1: **7 dev entries (5 high, 2 moderate)** / exit 0: **0 production findings** |
| Python compilation | `compileall -q app scripts tests alembic` passed |
| Git/text whitespace | `git diff --check` passed; all six changed/new text files separately checked for trailing whitespace |
| Cleanup | No labelled 3H containers remain; ports 8000/3199 have no listeners |

Fixture counts: one Event, one player, two props (one unlinked), one offer,
one snapshot, twelve game logs, and one each user, saved prop, slip, slip item,
fatigue score, ranking and interaction; one Alembic row. User preferences,
bcrypt hash, Event/Prop UUIDs, nullable Under price, timestamps and all selection
fields are included in full-row fingerprints. SavedProp stores user/prop identity;
book/side/line belong to SlipItem and are additionally checked through its API.
The final backup SHA-256 is
`e79f0b8ec655e69832dc7109f243534cafa5aca90de9ea5323d19ca9284c90e8`.
Restore timing excludes provisioning, post-restore verification and any operator
decision/cutover time; it must not be advertised as a service recovery RTO.

Raw report, ordered hashes, dump, startup failure logs, observed process counters,
suite output and browser preservation evidence remain ignored under
`backend/data/odds_runs/m3h/`. Two preliminary attempts exposed a PostgreSQL
temporary-init-server polling race and an invalid synthetic login email; both
were corrected. The final reviewed harness completed all checks. Earlier successful
runs are not added to the final regression totals. Chrome/Edge are both Chromium;
Firefox/WebKit and independent mobile engines were not tested or downloaded.

### Final review and local checkpoint

The final review confirmed three rehearsal safety gaps: inherited Docker context
and libpq routing overrides, the directly callable private server mode, and
direct-child-only timeout cleanup. These are corrected with local endpoint
pinning/environment sanitization, pre-import ownership/URL validation, and owned
PID-tree cleanup. Five additional guard regressions pass alongside the three
registration tests (eight focused tests, 0.049s, zero HTTP attempts). This raises
the full suite from 532 to 537; PostgreSQL scenario count stays 141. Docker's
tmpfs inspection representation was verified in `HostConfig.Tmpfs`; two guard
development attempts refused before database access and removed their containers.
Independent review found no further required application corrections. The
parent-crash/orphan limitation described above remains explicitly unverified.

The final measured table above supersedes the earlier implementation's timings.
Recovery/backend/browser raw evidence is under `backend/data/odds_runs/m3h/`;
fresh frontend/audit logs and rehearsal console are under the equally ignored
`backend/data/odds_runs/m3h-checkpoint/`. The final source diff and all six new/
changed text files were checked for whitespace and high-confidence credential
patterns. Manual content review confirmed only synthetic fixture values and
generic deployment instructions; no real credentials, environment-specific
deployment DB URL, provider response, backup binary, trace or generated evidence
is included in the six-file checkpoint. Backup/evidence/browser outputs remain
ignored. Final local Docker inspection found no 3H containers; ports 8000/3199
were closed. No broad cleanup command or development connection was used.

Not actually verified: public TLS/proxy/WAF, distributed abuse controls, concurrent
real registration races, production DML grants, clean/isolated/target-platform
release builds, artifact publication/signing, Python dependency security audit,
real-provider coverage, production backup/PITR/failover, concurrent write recovery,
load/capacity or new performance targets. No standalone lint gate exists. These
are explicit follow-up/release gates, not implied successful checks. Recommended
next engineering milestone: bounded-inventory/query optimization against the
performance criteria above, with hosting/build/security acceptance tracked before
any deployment authorization.

No development PostgreSQL connection, schema/data migration, Event backfill, live
provider/ingestion, existing backup restore/overwrite, production configuration
change, deployment, purchase or push is authorized or performed. Only the later
explicitly requested six-file local Git checkpoint is authorized. The runner
uses only freshly created isolated databases and removes only its owned container.
Local synthetic restore success does not remove the hosting/build/gateway,
enumeration, performance and backup-operations blockers above.

## Current deployment guide

October 23, 2026. This provider-independent guide supersedes the historical revision/runtime guidance above. Current Alembic head and readiness expectation are **20261022_05**. The [Stage 2 report](security-stage2-auth-api.md) defines cookie authentication and the [Stage 3 report](security-stage3-production-verification.md) records target-platform evidence and outstanding release gates. Local verification does not authorize public deployment, development migrations or sports-provider requests.

### Hosting requirements

Select hosting only after it meets the following requirements; no provider has been selected or provisioned. Run the frontend as a maintained Node service using the reviewed Next.js production build, the backend as the reviewed Linux container, and PostgreSQL as a private managed database. Place a trusted HTTPS gateway in front of the application, deny direct public backend/database ingress, and enforce auth/research quotas across backend replicas. Prefer same-site application/API domains so Secure, HttpOnly, host-only cookies work with SameSite=Lax. Keep refresh disabled and provider credentials absent. Redis is unused and no scheduler is needed to serve retained research. A separate approved import can later curate genuine data; an empty DB is an honest empty application.

Costs to evaluate at purchase time: two compute services, persistent database/storage, backups/retention, outbound traffic, domain, optional monitoring and separately funded sportsbook subscriptions/credits. No fixed prices or assumptions about free database durability, uptime or sleep behavior are made. Verify current plan terms before choosing a service.

### Build/start and ordering

1. Build from reviewed source/lockfiles in a clean environment. No developer `.env`, provider data, backups, screenshot/trace or approval artifact belongs in a release. Set only public `NEXT_PUBLIC_API_URL=https://<api-host>` and optional `NEXT_TELEMETRY_DISABLED=1` for the frontend build. Frontend directory: `npm ci`, `npm test`, `npx tsc --noEmit`, `npm run build`; runtime: `npm start -- --hostname 0.0.0.0 --port <assigned-port>`. The API URL is embedded at build time; rebuild when it changes. Next output is not configured as standalone or static export.
2. Build the backend from `backend/Dockerfile` and its allowlisted `backend/` context; install only the reviewed requirements and constraints with the pinned installer. Verify the actual target image's native imports, dependency resolution and advisories. The image runs as UID 10001; use its production command, without reload or source mounts. If the selected host assigns a port, supply its documented runtime port explicitly. Keep Uvicorn forwarding disabled unless a reviewed trusted-proxy configuration is required; prevent ingress bypass around the gateway.
3. Wait for PostgreSQL, take/verify a backup for existing data, stop conflicting writers, and run a separately approved release job: `python -m alembic current`, `python -m alembic upgrade 20261022_05`, then `current`. Startup does not create tables or migrate. Do not stamp over a mismatch. Revision 05 now accepts compatible columns created by initial empty bootstrap. Existing selection evidence is not guessed or changed.
4. Start API with `ENVIRONMENT=production` (or staging), then gate traffic on `/ready` 200. `/health` 200 means process liveness only. Configure restart/backoff and bounded health checks; production startup refuses bad configuration/schema. Start the frontend against the configured API origin and verify real cross-origin auth/edit preflights.
5. Before public access, complete the Stage 3 release matrix on the chosen host: current dependency/image audits, gateway abuse controls, TLS/origin/cookie checks, least-privilege DB access, migration/backup restore and operations ownership. A local Linux/TLS rehearsal is useful evidence but cannot certify public DNS, managed services or host recovery. Root Docker Compose remains development-only: known local credentials, published database/cache ports, reload and bind mounts.

### Environment reference

Settings read `backend/.env` when run from backend, or runtime environment variables; do not copy a developer env file into an image. The shared `.env.example` can be copied for local setup; unrelated frontend entries are ignored by backend settings. No real keys are included. For Windows, see README PowerShell commands; use process `$env:NAME='value'` overrides without exposing secrets in recordings or shell history. Save actual secrets through a private editor or the host secret manager.

| Setting | Required/optional and deployment handling |
| --- | --- |
| `DATABASE_URL` | Required; explicit PostgreSQL URL for production. Local example is localhost; Compose overrides host to db. URL-encode credentials; enforce verified TLS remotely. Runtime role needs normal account/research DML, not owner/superuser/DDL. Use a separate migration role. |
| `ENVIRONMENT` | Required production/staging policy; default development is not a production choice. |
| `JWT_SECRET` | Required private cryptographically random secret (generate at least 32 random bytes). Production rejects weak/default placeholders. Persist across releases or intentionally invalidate sessions by rotating it. |
| `JWT_ALGORITHM` | HS256 only. |
| `JWT_EXPIRE_MINUTES` | Default 120 minutes; production/staging maximum 1440. Absolute cookie/JWT expiry, no refresh/revocation/account recovery. |
| `AUTH_COOKIE_SAMESITE` | Default lax for same-site HTTPS frontend/API. Cross-site requires none with Secure; third-party-cookie blocking may still require same-site domains. Always use CSRF proof. |
| `GATEWAY_RATE_LIMIT_ENABLED` | Default false; production/staging requires true only after actual trusted gateway quotas are configured across all workers/instances. Built-in limits are process-local. |
| `API_MAX_BODY_BYTES` | Default 1048576 bytes; current mutation APIs are JSON, with no production upload route. Response/download size is unaffected. |
| `CORS_ORIGINS` | Required explicit JSON HTTPS origins in production/staging, e.g. `["https://<frontend-host>"]`; no wildcard/path/trailing slash. Allowed verbs include PATCH for exact saved/slip edits. CORS is not authentication or rate limiting. |
| `NEXT_PUBLIC_API_URL` | Required frontend build configuration for remote hosting; public, never a credential. Local default is http://localhost:8000. Put frontend local settings in frontend/.env.local. |
| `LIVE_REFRESH_ENABLED` | Keep false for portfolio hosting; enabling runs background provider subprocesses and writes data. Separate request/write approval is required. |
| `THE_ODDS_API_KEY` | Optional, absent for retained/offline demo; only supply for separately approved sportsbook collection. Never expose as NEXT_PUBLIC. |
| `BALLDONTLIE_API_KEY` | Optional legacy ML integration; not needed for current research. |
| `REDIS_URL` | Optional, configured but not used for caching/queues/rate limits. No Redis service needed for initial hosting. |
| Refresh/budget settings | Optional: ODDS_REFRESH_SECONDS=900, HISTORY_REFRESH_SECONDS=21600, ODDS_EVENT_HORIZON_HOURS=48, ODDS_EVENT_FETCH_LIMIT=0, ODDS_MIN_REMAINING_CREDITS=50, ODDS_MAX_REQUESTS_PER_RUN=100, ODDS_MAX_CREDITS_PER_RUN=500. These are ceilings/settings, not authorization to spend or enable refresh. |

### Docker and secret/artifact handling

The backend build context is `backend/`. Its default-deny `.dockerignore` admits runtime app/ingestion source, requirements and Alembic inputs, and excludes tests/ML source, private mappings, env files, venvs, provider artifacts and backups. The runtime uses UID 10001 and trusted CA certificates; `/app/data` is the intended writable status location while refresh stays off. Git ignore does not exclude Docker inputs. Build from the reviewed Dockerfile, record the actual image/base identities, inspect the resulting filesystem and scan that exact image. See Stage 3 for completed checks and unresolved image findings; source review alone is not image verification.

Git now also ignores backend runtime data by default (already-tracked mapping/example inputs remain tracked), private env variants, backup extensions and recording/screenshot directories. Git ignore does not remove previously tracked files; inspect `git ls-files` before publishing. Credentials must never appear in logs, screenshots, source, browser storage exports or build arguments. Keep provider/approval/status artifacts private.

### Operations and recovery

Capture stdout/stderr with bounded retention; redact auth headers, tokens, URLs with credentials and provider keys. `/ready` sanitizes database errors and returns no-store; request validation omits submitted values. Optional ingestion status/logs are local runtime artifacts, not durable monitoring or a verified recovery service. Configure alerts for repeated readiness failures, unavailable DB, failed approved imports and quota stops. No Redis logging/cache recovery exists.

Use managed encrypted backups and test restoration into a separate staging database; back up signing secrets separately. Roll back to compatible application code against the additive schema when possible. Revision 05 downgrade deletes exact selections and is not a safe routine rollback. Never restore over user data without explicit scope and post-backup-loss assessment. Recheck readiness, ownership and exact saved/slip identity after recovery. Historical local recovery evidence above does not certify the current host or current schema.

| Classification | Current status |
| --- | --- |
| Implemented and verified locally | Cookie/CSRF/auth ownership, request boundaries and frontend behavior have Stage 2 evidence. Stage 3 records the Linux/HTTPS/gateway/recovery results separately. |
| Requires configuration | Host/domains, TLS, secret storage, exact origins/public API build URL, DB roles/network/TLS, gateway abuse limits, backup/retention/alerts, curated genuine dataset |
| Not verified | Remote deployment, public DNS/TLS/managed-database connectivity, target-host load/cold starts and backup restore, actual current provider coverage. See Stage 3 for the local target-platform result. |
| Blocked before public release | Unfinished target-host security/configuration and operations gates. Stage 2's installed Python audit was clear; the deferred development-tool advisory and Stage 3 image findings must retain their explicit dispositions. Local portfolio evidence does not imply public deployment readiness. |


## Security Stage 2 deployment requirements

[Stage 2 authentication/API report](security-stage2-auth-api.md) supersedes historical bearer/localStorage and session defaults above. Login/register set HttpOnly cookies and return no JWT. Credentialed frontend requests use a session-bound CSRF proof for mutations, with exact Origin/Referer checks. Prefer HTTPS same-site app/API domains; separate sites require SameSite=None/Secure and can be blocked by browser third-party-cookie policy.

Public deployment still requires an actual gateway enforcing fleet-wide login/register/research quotas, verified TLS/origins and private database roles. The production acknowledgement flag does not create this control. Docker ignores forwarding headers and disables raw access logs by default. If client IP forwarding is needed, explicitly enable Uvicorn proxy headers with only the actual trusted gateway addresses/CIDRs and deny direct ingress bypass; never use a publicly reachable trust-all proxy setting. Gateway logs must redact auth bodies and Cookie/Set-Cookie/Authorization/CSRF headers. No public gateway, deployment or development migration was performed during Stage 2.
