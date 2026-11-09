# Oracle ARM64 production deployment preparation

Prepared November 9, 2026. Work is confined to the isolated public checkout at
`8c681267327f0c57eaea1d4d5b78be445a95c1b0`; changes remain uncommitted.
No cloud resources, public deployment, real provider requests or development DB
changes. Evidence is labeled **Executed locally**, **Official documentation**,
**Estimated**, or **Not verified**. ARM64 runs below use Docker Desktop emulation,
not an Ampere performance benchmark.

## Result and regression fix

**Executed locally:** The original stale-observation test failed exactly as
reported. Ingestion collected only actionable decisions, so its later search for
non-actionable `last_known` decisions was unreachable. The fix retains live and
last-known observations in the status collection while adding only actionable
offers to the eligible-ID collection. Expired/missing/game-started offers remain
unavailable; the shared offer policy, odds, identities and actionability are
unchanged. Added checks cover fresh status, stale non-actionability and mixed
fresh/stale books.

Focused ingestion: **38 passed**, zero external HTTP attempts. The full guarded
backend run, executed once after the fix and startup-guard tests: **1,151 tests,
869 passed, 282 skipped, zero failures, zero external HTTP attempts**. The skipped
tests are opt-in PostgreSQL cases; they were not silently pointed at the rehearsal
database. Actual PostgreSQL/image checks below supplement those unit tests.

## Domain-controlled architecture

```text
Browser -> app.example.com (Cloudflare Workers / existing OpenNext bundle)
Browser -> api.example.com (Cloudflare proxy, Full strict, custom zone AOP)
          -> Oracle firewall -> Nginx TLS/mTLS gateway :8443
          -> internal API network -> FastAPI UID10001 :8000
          -> separate internal DB network -> PostgreSQL UID70 :5432
```

**Implemented / locally tested:** `deploy/oracle/compose.yml` is independent of
development Compose. Only the gateway has a host port, bound to loopback by
default. PostgreSQL is not on the gateway/edge network. Backend and migration jobs
can reach the private database; only the backend is on the API network.
Gateway/backend addresses are explicitly reserved to prevent Docker auto-address
allocation collisions. Subnets must be checked against the target host's networks.

| Service | Identity and limits |
| --- | --- |
| Backend | UID/GID 10001, one Uvicorn worker, 1 GiB RAM with no additional swap allowance, 1 CPU, 128 PIDs |
| PostgreSQL | UID/GID 70, persistent named volume, 1 GiB RAM, 0.75 CPU, 200 PIDs, 128 MB shared buffers, 40 connections |
| Gateway | UID/GID 101, 128 MiB RAM, 0.25 CPU, 64 PIDs, two Nginx workers |
| Controlled jobs | UID10001 for bootstrap/migrate; explicit root volume-init with only CHOWN capability |

All long-lived services have read-only roots, ALL capabilities dropped,
no-new-privileges, bounded writable tmpfs, restart-unless-stopped and rotated
10 MB x 3 Docker logs. DB data/socket paths are writable only for UID70.
Volume-init acts only on an empty new volume; it refuses existing data.
No source bind mounts, reload server, Redis, provider keys, automatic refresh,
automatic migrations or automatic schema creation appear in the production stack.

**Implemented:** `production_runtime.py` reads file-mounted secrets before importing
application configuration. App and migration URLs must target `db:5432`, the
explicit configured database, the appropriate role, and contain no routing query
parameters. Serve forces refresh off and provider keys empty, validates production
settings, and trusts forwarding from one exact gateway IP. Invalid configuration
fails without printing driver exceptions, SQL or secret values.

The separate bootstrap job receives the administrator secret once, creates
`pp_owner` and `pp_app` without superuser/create-role/create-db/inheritance rights,
and creates an owner-controlled database. It fails on existing roles rather than
resetting credentials. Partial bootstrap failures require deliberate inspection.
Migrate verifies the physical DB/role, transactionally upgrades through
`20261022_05` and grants the app SELECT plus only user-state DML and the existing
prop popularity-column update. The app owns no tables and cannot update provider
offers or create schema objects. Administrator/owner credentials are not mounted
into the backend.

## Gateway security

**Implemented / locally tested:** The production Nginx file requires a TLS origin
certificate, the private CA for **your own zone's** client certificate, and a
trusted Cloudflare TCP peer. A shared Cloudflare client CA would authenticate
other accounts and must not be substituted.

`cloudflare.conf` snapshots the official IPv4/IPv6 ranges checked on this date.
Its geo test uses `$realip_remote_addr`, the original peer, while realip rewriting
accepts `CF-Connecting-IP` only from those ranges. Missing/invalid client-IP
rewriting fails closed. Untrusted requests cannot turn a forged header into a
trusted peer. Replace forwarding chains with the verified client IP and HTTPS;
clear Forwarded, X-Real-IP, X-Forwarded-Host and CF-Connecting-IP before upstream.
Uvicorn trusts only the reserved gateway IP.

Nginx shares 10 auth POST/minute (burst 9) and 30 API requests/second (burst 60)
across workers. OPTIONS does not consume these budgets. Gateway 429 responses
include Retry-After: 60; backend backstop responses may carry a different remaining
window. Backend exact-origin CORS and session-bound CSRF remain authoritative.
No wildcard origin or extra development origin is introduced.

Body limit is 1 MiB; header/body timeouts are 10/15 seconds, upstream read timeout
30 seconds and connect timeout 5 seconds. Authenticated responses are not cached;
Cache-Control is no-store, cookies/Authorization/Origin are preserved. Access logs
contain status and duration only, excluding URLs, query strings, bodies, Cookie,
Authorization and CSRF headers. Nginx error logging is disabled to avoid
request-bearing diagnostics; retain process health, status/latency and restart
alerts as the baseline monitoring. Backend access logging is off and existing
application redaction remains in force.

`/health` and `/ready` traverse the same protected gateway; readiness checks schema
and connectivity without writing. Nginx's separate health listener binds only to
container loopback. API/DB ports are never published.

**Official documentation:** [realip trust and original peer](https://nginx.org/en/docs/http/ngx_http_realip_module.html),
[Cloudflare ranges](https://www.cloudflare.com/ips/),
[AOP availability and account-specific authentication](https://developers.cloudflare.com/ssl/origin-configuration/authenticated-origin-pull/),
[zone-level custom certificates](https://developers.cloudflare.com/ssl/origin-configuration/authenticated-origin-pull/set-up/zone-level/).
AOP is available on Free. Full (strict), uploaded zone-specific client credentials,
certificate renewal and firewall restrictions still require hosted verification.

## Required production setup (not executed on Oracle)

Use a reviewed ARM64 Linux host and externally built images. Build the backend
with the existing hardened Dockerfile and PostgreSQL with
`backend/docker/postgres.Dockerfile`; the latter remains the gosu-free UID70
derivative. Pin the resulting images by digest for an actual release.
The example Nginx digest is multiarch and was executed as ARM64 here; update/scan
it deliberately before public use, rather than silently pulling latest.

Copy `production.env.example` to an **external** private operator directory.
Provide real image digests, exact HTTPS CORS origin, reviewed non-overlapping
addresses and paths. Copy/review the two Nginx files externally and replace the
example API hostname there. Keep deployment secrets, TLS keys and configuration
out of Git:

| File in SECRETS_DIR | Purpose |
| --- | --- |
| db_admin_password | Cluster initialization/bootstrap only |
| db_owner_password / db_app_password | Initial role provisioning |
| migration_database_url | Owner URL: postgresql://pp_owner:URL_ENCODED_PASSWORD@db:5432/DB |
| app_database_url | App URL: postgresql://pp_app:URL_ENCODED_PASSWORD@db:5432/DB |
| jwt_secret | Strong stable random signing secret |
| origin_cert.pem / origin_key.pem | Origin server TLS chain/key |
| cloudflare_client_ca.pem | CA verifying your zone-specific AOP client |

Compose file secrets are bind-mounted files, not an encrypted secret store.
On Linux, protect their parent directories and set host file/group permissions so
only the intended container UID/GID and operator can read each file. Do not rely
on Compose secrets uid/gid/mode remapping for file sources. Windows bind mounts do
not prove Linux permission behavior. Do not print resolved secret values.

From the public repository root on the intended deployment host, after explicit
deployment approval, the controlled sequence would be:

```powershell
# $cfg points to the private nonsecret operator env file.
$cfg = "/srv/proppulse/production.env"
$compose = "deploy/oracle/compose.yml"
docker compose --env-file $cfg -f $compose config --quiet
docker compose --env-file $cfg -f $compose --profile tools run --rm volume-init
docker compose --env-file $cfg -f $compose up -d db
docker compose --env-file $cfg -f $compose --profile tools run --rm bootstrap
docker compose --env-file $cfg -f $compose --profile tools run --rm migrate
docker compose --env-file $cfg -f $compose up -d backend gateway
```

Do not use `--profile tools up`; invoke each one-off job deliberately.
Volume-init/bootstrap are first-use jobs, not update commands. Stop API traffic
before a schema upgrade, take a backup, run migrate explicitly and then restart
the backend. Do not run this sequence against development or an unreviewed volume.
The checked-in loopback bind is safe for local preparation; public binding requires
an explicitly approved OCI NSG/host firewall allowing only current Cloudflare
ingress on 443, restricted SSH, unknown-host rejection and verified origin mTLS.

Workers must be built with the real `NEXT_PUBLIC_API_URL=https://api.example.com`.
Keep HTTPS siblings same-site, host-only Secure/HttpOnly __Host- cookies,
SameSite=Lax, Path=/ and no Domain attribute. No third-party cookie reliance.
Domain purchase/renewal means total cost is not strictly $0 unless already owned.

## No-domain option: supported components, separate unverified path

**Official documentation:** A [workers.dev hostname](https://developers.cloudflare.com/workers/configuration/routing/workers-dev/)
does not require onboarding a custom domain. A same-hostname `/api/*` proxy would
keep cookies first-party. Current [Workers VPC](https://developers.cloudflare.com/workers-vpc/get-started/)
supports private HTTP/HTTPS services through an authenticated, persistent
[Cloudflare Tunnel](https://developers.cloudflare.com/workers-vpc/configuration/tunnel/),
without opening public origin ingress or requiring a public API DNS route.
[Pricing](https://developers.cloudflare.com/workers-vpc/platform/pricing/) is free
during open beta; this is not an Always Free guarantee.

**Documented capability / engineering inference:** This provides a supported
candidate for a stable no-domain route, rather than a rotating Quick Tunnel.
A Worker can bind to one registered private service, strip /api, overwrite
untrusted identity headers, preserve the browser Origin, and forward credentials
and session-bound CSRF. Backend CORS must allow exactly the chosen HTTPS
workers.dev origin; relative API URLs must be embedded at build time.
All proxy invocations consume the Workers request/CPU budgets.

For literal HTTPS all the way to Nginx, the tunnel's
[VPC TLS contract](https://developers.cloudflare.com/workers-vpc/configuration/vpc-services/)
requires a publicly trusted or Cloudflare Origin CA certificate and
`verify_full`; a self-signed CA, disabled verification or hostname-check bypass
is not a production solution. [Let's Encrypt IP certificates](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability)
now support IPv4/IPv6 without domain ownership, but last only 160 hours. A retained
Oracle public IP with a matching IP-SAN certificate and fully automated renewal
is therefore a possible TLS component. Actual VPC IP identity validation, renewal
challenge routing and certificate rotation remain untested here.

AOP is **not** used over Tunnel: connector credentials authenticate that path.
The public-ingress Nginx config in this change cannot simply be reused unchanged
for it. A separate connector-only listener/network, tightly scoped VPC binding,
verified TLS, unforgeable Worker-to-gateway client identity and origin-bypass tests
are required. Never trust client-supplied forwarding headers merely because a
request traversed a Worker. Workers VPC client-IP propagation must be checked in
the real service before relying on per-client quotas.

**Recommendation:** Use the implemented domain-controlled path if a domain is
already available. If no domain and strict $0 are mandatory, the VPC + IP-TLS route
is a documented candidate for a separate authorized prototype, not a verified
deployment configuration. No proxy, tunnel, certificate request or cloud binding
was implemented/created in this task. Quick Tunnels are temporary and unsuitable
for a stable production route ([Cloudflare guidance](https://developers.cloudflare.com/tunnel/concepts/)).

## Local verification and reproduction

The rehearsal uses the production Compose and Nginx files directly, overriding
only local ingress, test CA/peer ranges, fixture services and images. It owns only
the `pp-oracle-rehearsal` project, refuses preexisting project resources/state,
and validates ownership before cleanup. All generated secrets, certificates,
resolved configs, reports and dumps stay under ignored
`backend/data/odds_runs/oracle-deployment-prep`. Nothing is imported from private
provider data.

The local edge emulator replaces client headers and authenticates to Nginx with
the local client certificate. Both example HTTPS hostnames are resolved to
loopback only in Chrome's resolver rules, not global DNS/hosts. Node HTTPS verifies
the local CA and server hostname. Chrome accepts only the fixture server's pinned
SPKI for that private CA. This proves local TLS/cookie behavior, **not public TLS,
Cloudflare network behavior or certificate issuance**.

```powershell
docker buildx build --platform linux/arm64 --load -t proppulse-oracle-backend:arm64 -f backend/Dockerfile backend
docker buildx build --platform linux/arm64 --load -t proppulse-assessment-postgres:arm64 -f backend/docker/postgres.Dockerfile backend
node backend/tests/oracle_deployment_rehearsal.cjs prepare
node backend/tests/oracle_deployment_rehearsal.cjs start
node frontend/tests/oracle-gateway-browser.cjs
node backend/tests/oracle_deployment_rehearsal.cjs backup
node backend/tests/oracle_deployment_rehearsal.cjs cleanup
```

Prerequisites: Docker Desktop/Buildx ARM64 emulation, Node, local Chrome, frontend
`npm ci`, and the existing Cloudflare production bundle built for the example API
origin. If needed, use the prior compatibility report's Linux OpenNext build
instructions; the rehearsal installs Linux tooling into a disposable volume but
does not rebuild or deploy the frontend. Ports 443/3444 and the test subnets must
be unused. Use a fresh rehearsal state directory; archive old ignored evidence
deliberately, never overwrite it automatically.

The backend full run used a network-none, read-only ARM64 container with source
mounted at /source, test-only DATABASE_URL pointing to an unreachable assessment
host, refresh disabled and `python tests/run_no_provider_http.py`. No real .env
was loaded. Provider-looking output in that log comes from mocks; transport
attempts were zero.

**Executed locally:** The updated hardened backend image built successfully for
linux/arm64 with its dependency lock unchanged; PostgreSQL and pinned Nginx also
ran as aarch64. The actual production Compose startup, UID70 persistent ownership,
controlled bootstrap/migration, revision 20261022_05 and readiness passed. SQL role
checks confirmed neither owner nor app is superuser, create-db/create-role,
inheriting, replicating or bypass-RLS; app schema CREATE/provider-offer UPDATE
were denied while user-state INSERT was granted.

The final actual-Chrome + Node HTTPS probe passed: login/logout/session restoration;
Secure HttpOnly host-only __Host- cookies with SameSite=Lax; stale/missing/hostile-origin
CSRF rejection; valid CSRF; saved under/FanDuel/20.5 selection and slip retention;
cross-account edit 404 and isolated reads; CORS/credentialed OPTIONS; PostgreSQL
restart persistence; missing-client-certificate and untrusted-peer origin rejection;
forged forwarding headers unable to evade shared quotas; body limit 413; auth and
API gateway 429/Retry-After 60; header/JWT/DB-secret log-sentinel absence; and runtime
non-root/read-only/capability/resource/port checks. Nginx -t, Compose resolution,
JavaScript syntax and git diff --check passed. Quota probes reset only the disposable
backend/gateway windows, reuse connections and leave production rates unchanged.

Observed post-probe Docker memory: backend 124.7 MiB, PostgreSQL 67.3 MiB, gateway
39.35 MiB under ARM64 emulation and tiny synthetic data. These are observations,
not native A1 capacity promises. Frontend unit tests were not repeated because
frontend application source did not change; the actual Worker bundle was exercised
in Chrome. No additional full backend rerun was needed after the single green run.

## Capacity, backups and remaining hosted checks

**Estimated:** The long-lived service caps total 2.125 GiB and 2 CPUs. Leave OS,
Docker, page cache and operational headroom within the current A1 allowance.
Migration/build/backup jobs consume additional resources; build externally and
avoid overlapping heavy jobs on the VM. Caps are not a concurrency benchmark.
The small synthetic fixture cannot establish production query latency, database
growth or ML memory ceilings.

**Official documentation:** [Oracle Always Free](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)
currently describes 2 OCPU/12 GB A1, 200 GB combined boot/block storage and five
volume backups, home-region restrictions, capacity shortages and idle reclaim
criteria. These differ from temporary trial credits. A quiet portfolio can be
reclaimed. [Workers Free](https://developers.cloudflare.com/workers/platform/limits/)
still has 100,000 script requests/day, 10 ms CPU/request and 128 MB memory.
Local workerd does not establish hosted CPU compliance. Both SSR and a /api proxy
need hosted measurement before promising sustainable $0 operation.

**Estimated:** Start with roughly 35–75 GB for OS, retained images, small DB/WAL
and rotated backups; monitor real growth. Do not retain unbounded snapshots, logs,
build cache or backup copies. Keep data and backup storage within the free
allowance. Domain renewal, overages after upgrading billing, paid image services
and VPC beta pricing changes can break the $0 objective.

Use logical `pg_dump -Fc --no-owner --no-acl` backups, encrypted off-host copies,
separate reviewed roles and actual restore rehearsals. Never copy AMD64 PGDATA
into ARM64. A same-volume backup cannot survive volume loss. Keep the prior image
digest for app rollback; schema rollback requires a reviewed compatible image or
restoration into a separate database, not an automatic downgrade or volume reset.
Do not delete a production volume as part of cleanup/update.

**Not verified in hosting:** OCI allocation/NSG rules and block-volume permissions,
host reboot recovery, real Cloudflare AOP/headers and Workers CPU, public DNS/TLS
issuance/renewal, provider-data capacity, external alerts, off-host backup recovery,
and the no-domain VPC prototype. None of those are claimed by the local results.
Before deployment, review current image vulnerabilities, rotate the example/local
materials, install real certificates and verify least-privilege secret-file
permissions on Linux. No deployment authorization is implied by these files.

## Changed files

- backend/scripts/fetch_odds.py; backend/tests/test_milestone2_ingestion.py
- backend/scripts/production_runtime.py; backend/tests/test_oracle_production.py
- deploy/oracle/compose.yml; deploy/oracle/production.env.example
- deploy/oracle/nginx/nginx.conf; deploy/oracle/nginx/cloudflare.conf
- backend/tests/oracle_deployment_fixture.py; backend/tests/oracle_deployment_rehearsal.cjs
- frontend/tests/oracle-gateway-browser.cjs
- docs/cloudflare-oracle-deployment-prep.md

**Executed locally, final checkpoint:** The synthetic database logical dump was captured as binary and its pg_restore archive catalog validated. A full restore of this new dump was not run; off-host recovery remains a deployment prerequisite. Ownership-checked cleanup removed every rehearsal container/network/volume, and filtered Docker inventories were empty afterward. Ignored private evidence and local images remain for review. Public HEAD is unchanged; 12 source/documentation files are uncommitted. The original private repository's HEAD/status and all seven protected SHA256 hashes are unchanged. No commit, push or deployment was performed.
