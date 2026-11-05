# Security Stage 3: production-path verification

October 23, 2026. Local verification only. No hosting provider is selected or
provisioned, no public deployment is authorized, and no development PostgreSQL or
sports-provider requests belong to this stage. Stage 2's cookie/CSRF/API contract
remains the application contract. The [current deployment guide](milestone-3h-staging-recovery.md#current-deployment-guide)
supersedes historical platform and authentication instructions.

**October 24 container-image follow-up:** the [container remediation report](container-image-remediation.md)
records the subsequent image comparison, primary advisory review and final
verification. The Stage 3 counts/digests below remain historical evidence; do not
read them as the later remediation result or public deployment approval.
The selected backend now has 67 OS advisory rows / 38 IDs (six high, zero
critical); the selected PostgreSQL 15.19 derivative removes gosu and scans with
zero findings. Both retain verified non-root/runtime/database behavior. Use the
follow-up report for current immutable identities and remaining release gates.

## Release matrix

“Verified” means an actual completed check, bounded to its recorded environment.
“Requires hosting” needs the chosen host/domain/account. “Blocked” is an unfinished
release gate. “Deferred risk” is an explicitly retained limitation, not a passed
security check. These results describe the local Linux/HTTPS checkpoint, not a
deployed service.

| Control | Classification | Evidence or remaining gate |
| --- | --- | --- |
| Linux backend image and native imports | Verified | Actual final image runs UID 10001; all 62 installed application distributions match active constraints and dependency metadata. NumPy/pandas/SciPy/scikit-learn/XGBoost/SHAP fit/explanation, bcrypt and three invalid JWT cases pass. |
| Image Python dependency findings | Verified | pip-audit 2.10.1 on all 62 final runtime distributions and Trivy Python scan both report zero known vulnerabilities. This does not include a claim of zero OS findings. |
| Backend OS findings | Deferred risk | 166 package/advisory rows, 71 distinct IDs; 44 high, 60 medium, 61 low, 1 unknown, zero critical. No reported fixed versions. Reachability limits and mitigations below do not fix these packages. |
| Gateway image | Verified | Compatible Brotli update 1.2.0 → 1.2.1 removes the high finding; final Trivy scan reports zero findings. Affected HTTPS/body/rate checks rerun successfully. |
| PostgreSQL image residual | Blocked | Current PostgreSQL 15 image has zero OS findings but 61 Go advisory rows in startup helper `gosu`, including one critical. Requires explicit upstream-binary/hosting disposition; see below. |
| Production startup, migrations and probes | Verified | Actual production lifespan starts against revision `20261022_05`; `/health` and `/ready` return 200. Weak JWT secret, HTTP origin and false gateway acknowledgement fail closed before DB work. |
| Private DB and least-privilege application role | Verified | Separate migration owner; app role has no ownership, role membership or elevated attributes. CREATE/ALTER/schema/role and provider-table DELETE challenges denied. Real account/saved/slip writes succeed. |
| HTTPS cookie/CORS/CSRF browser behavior | Verified | Actual gateway/API/PostgreSQL Chrome desktop/mobile checks 2/2 pass in 9.3s; disposable self-signed certificate explicitly accepted in test browser only. No public certificate claim. |
| Gateway and multiple backend replicas | Verified | Two gateway workers share rate zones across two private backend replicas. Changed forwarding headers do not evade limits; actual 429/Retry-After, 413 body limit and log-sentinel checks pass. |
| Backup/restore and selection preservation | Verified | Current PostgreSQL 15.19 restore: all persisted rows across 15 tables plus revision match; restored cookie login/me/saved/slip/readiness pass, logout gives 401, five privilege challenges denied. Actual restore flags/limits below. |
| Fresh bootstrap on current DB image | Verified | Final backend image's fresh Alembic bootstrap on a second empty database of PostgreSQL 15.19 passed at revision `20261022_05`. |
| Public DNS, certificates and remote DB TLS | Requires hosting | Validate hostname/chain/renewal, managed PostgreSQL `sslmode=verify-full`, private routing and real browser behavior at chosen origins. Local certificates cannot certify these. |
| Secret management and operations | Requires hosting | Private secret injection/rotation/backup, encrypted storage and retained backups, alerts/log retention, recovery ownership and tested host restore. |
| Tailwind/PostCSS tooling advisory | Deferred risk | Current npm production audit zero; full audit three moderate package entries for one development-only `GHSA-rj75-hqrm-r3gf`. No Tailwind major migration or unverified override. |
| Stateless session limitations | Deferred risk | No copied-token revocation before expiry, refresh-token system, password recovery or verified-email flow. HttpOnly cookies do not prevent XSS-driven actions. |
| Sports-data completeness and availability | Deferred risk | Synthetic offline fixtures do not certify current provider availability, complete multi-sport history or historical odds-movement coverage. Missing/expired prices remain unavailable; no provider requests or sportsbook credits were used. |

## Local verification scope

Actual stack: Linux backend image built from the repository Dockerfile; two
backend replicas reachable only on an internal Docker network; Nginx HTTPS gateway
for `app.proppulse.test:3443` and `api.proppulse.test:3443`; separate PostgreSQL
migration owner and application role; synthetic offline fixtures only. The browser
test explicitly accepts this run's self-signed certificate with
`ignoreHTTPSErrors=true`; no host trust-store change is made. A separate Python
HTTPS probe supplies that certificate as its explicit trust input and successfully
verifies hostname/SNI. Neither check proves a publicly trusted chain or renewal.
Gateway rate state is shared across its workers; the application's process-local
limits remain a backstop.

The build must exclude developer env files, backups, provider data and approval
artifacts. Test fixtures remain isolated from the application image. No provider
key is needed, and `LIVE_REFRESH_ENABLED=false` is explicit. Private generated
certificates, credentials, dumps, scan output and recordings stay outside Git.

## Images, scans and remaining findings

The application source build context came from a clean Git archive of the starting
checkpoint with the reviewed Stage 3 Dockerfile overlaid; unrelated working changes
were excluded. Final backend image index digest:
`sha256:af7fa6592e37a7bde72eda49f735dee9f797dd3319cda233e192bc30fe4e0a76`;
Linux platform manifest:
`sha256:0df11b0a1f6efd8c89eeab890cb78785d7fa07d783acc301a91a9588ee5c23a9`.
The Python base is digest-pinned. Native wheels replace runtime compiler/header
packages; `libgomp1` and `libstdc++6` support the existing ML imports. Package
resolution is checked during build. Then pip, setuptools and wheel are removed
from the runtime image, including pip's vulnerable vendored components. The pinned
installer remains in the constraints for reproducible builds; application package
versions were not changed. Eleven image layers/94 app entries were inspected:
zero forbidden private paths, embedded dummy secrets or private environment values.

Trivy **0.76.1** scanned the exported actual images. An initial Docker Scout attempt
required login and was not counted as a completed scan. Removing compiler/header
and installer packages reduced the initial Debian scan's 1,680 package/advisory
rows/1,001 distinct IDs to the matrix above, eliminating its critical kernel-header
finding. Remaining
high IDs include util-linux mount/nsenter `CVE-2026-76642`, `CVE-2026-78408`,
`CVE-2026-78409`, `CVE-2026-78410`; libacl `CVE-2026-54369`; ncurses
`CVE-2025-69720`; libsystemd `CVE-2026-16742`; and Perl Archive::Tar
`CVE-2026-9538`. The API does not invoke mount/nsenter, a systemd/homed daemon or
external archive extraction. UID 10001, dropped capabilities, read-only root,
no-new-privileges, noexec temporary mounts and private ingress reduce exposure;
they do not remediate installed packages. No fixed version was reported for the
166 retained rows. Re-scan and review distro updates before any public release.

Scans ran October 23 locally (October 24 UTC), using the Trivy database updated
`2026-10-24T01:18:19Z` and downloaded `2026-10-24T03:34:56Z`. These are dated
findings, not a guarantee about future image rebuilds or newly published advisories.

Debian's primary tracker confirms the selected trixie util-linux and ncurses
packages remain affected, marked `no-dsa`/minor; fixes recorded for unstable are
util-linux 2.42.3-1 and ncurses 6.6+20251231-1. These are not available compatible
stable updates to silently mix into this image. The ncurses issue is specifically
the `infocmp` CLI, which the API does not invoke. See the
[util-linux tracker](https://security-tracker.debian.org/tracker/CVE-2026-76642)
and [ncurses tracker](https://security-tracker.debian.org/tracker/CVE-2025-69720).
The distro's urgency and scanner's severity differ; neither erases the finding.

Final gateway image digest:
`sha256:519274f050691b4340e4bf75fb72065165f806c083b70fa739a3c856f305d671`.
Its pinned base plus compatible `brotli-libs` 1.2.1 update resolves
`CVE-2026-111497`; final scan has zero findings. The serving Windows frontend uses
Node **24.22.1**, whose official binary SHA-256 matched the installed executable.
Although its Brotli version string remains 1.2.0, the fix is backported in the
[official security release](https://nodejs.org/en/blog/release/v24.22.1) and
[Brotli commit](https://github.com/nodejs/node/commit/49dff6f57a); it was not treated
as the unpatched gateway library. No protected Node-version file was changed.

Current PostgreSQL 15 image digest:
`sha256:a8e042598834300dfaa17a54f695b87b7f25d3490433bbbe2ef3bffbb9747f24`.
Its OS findings are zero, compared with 60 on the older cached image. Its `gosu`
startup helper retains 61 Go standard-library advisory rows: 1 critical, 25 high,
31 medium, 3 low, 1 unknown, with reported fixes including Go 1.24.13. This helper
changes startup user identity; it is not the PostgreSQL network protocol handler.
That reachability distinction is not a safe-package certification. Upstream helper
review/rebuild or an independently assessed managed-database runtime remains a
public-release gate. Do not silently substitute an unverified privileged binary.

Raw scans, runtime/package checks and private evidence are retained under ignored
`backend/data/odds_runs/security-stage3/`; advisory rows can repeat the same ID for
multiple installed packages and are not counted as independent vulnerabilities.

## Actual functional and gateway checks

Chrome desktop/mobile exercise production Secure/HttpOnly/host-only `__Host-`
cookies, no JWT in JavaScript storage, CSRF proof and Origin/Referer rejection,
credentialed CORS and denied untrusted preflight, real saved CRUD/exact Unsave,
slip edit and reload, cross-user 404 denial, login/logout, Discover/research,
expired offers and actual browser-cookie expiry. No app API response is mocked;
traces, screenshots and videos are disabled. Ten focused frontend checks,
TypeScript and the final HTTPS production build also pass. This stage does not
claim another full backend/frontend regression run; Stage 2's full suites remain
separate historical evidence.

Final gateway rerun: login attempts with changed X-Forwarded-For produced ten 403
CSRF rejections, then two 429 responses with Retry-After 60. A 150-request concurrent
API probe produced 64 successful/86 throttled responses; counts depend on timing,
not a promised sustained capacity. Shared quotas are auth 10/minute with burst 9
and API 30/second with burst 60. An internal untrusted-socket probe independently
verified the app backstop: twenty 403 then 429 with Retry-After 900 despite spoofed
forwarding headers. Oversized body returned 413; a slow HTTPS body connection
closed after 15.02 seconds (no 408 response was asserted). Supplied credential-log sentinels
were absent from gateway/backend logs. No backend or DB host port is published;
two backend replicas use only the internal network. These are bounded abuse checks,
not fleet-wide load/capacity certification or durable log-retention verification.

## Actual recovery result

A 38,175-byte custom-format fixture dump was restored onto a separate fresh
PostgreSQL **15.19** container using the current pinned image. Dump SHA-256:
`8f8a79396be273251eeebc5d4d1812ea503c46c8963aa8db6bc62ee2edfd77e0`.
The restore database was newly created and verified empty. The actual invocation
used `--clean --if-exists`; it did **not** verify a single-transaction restore.
No pre-existing application data was overwritten. Future normal instructions below
prefer an empty target without cleanup flags and an atomic restore.

All 41 actual rows across 15 public tables (including `alembic_version`) and the
migration revision match the source,
including 5 users, 3 slips, 1 saved selection and 1 slip item. The final production
image's genuine lifespan/readiness and restored-account Secure/HttpOnly cookie
login, `/users/me`, saved and slip reads returned 200; logout was followed by 401.
Five app-role DDL/provider-DML challenges were denied. A second empty database on
PostgreSQL 15.19 also passed fresh Alembic bootstrap from the final image at revision
`20261022_05`. Six fixture routing guard checks and three control/cleanup guard
checks passed without live provider/development DB access. Independent review found
and fixed cleanup aborting on missing resources after partial startup; cleanup now
validates every present resource's ownership before removing any. No other
actionable defect remained in the reviewed Dockerfiles/control/gateway/probes.
Startup/authentication changed
no rows, and the external HTTP guard recorded zero attempts. Browser writes also
left source Event/offer/snapshot/game-log immutable fingerprints unchanged.

The restore server runs directly as UID 70 with read-only root and dropped
capabilities, so its bundled `gosu` helper is not executed in this tested command.
The image still contains that helper and retains the documented findings. This
fixture recovery is not measured end-to-end RTO/RPO: a resumed step's timing was
not counted as complete recovery time. Managed backups, PITR, failover, encrypted
retention and the selected host's recovery process remain unverified.

## Provider-independent release checklist

1. Choose a maintained Node frontend service, reviewed Linux backend runtime,
   private managed PostgreSQL and a trusted TLS gateway. Price compute/replicas,
   DB/storage, backup retention, network egress, domain/TLS, logs/alerts and any
   separately authorized data subscriptions. No free-tier durability or capacity
   assumption is made. Redis and a scheduler are not serving requirements.
2. Build from reviewed source and lockfiles without developer secrets or data.
   `NEXT_PUBLIC_API_URL` is a public build-time origin; rebuild for the actual API
   hostname. Record image identities and retain the reviewed release artifact.
3. Inject `ENVIRONMENT`, private `DATABASE_URL`, random `JWT_SECRET`, explicit
   `JWT_EXPIRE_MINUTES`, `AUTH_COOKIE_SAMESITE` and exact HTTPS `CORS_ORIGINS` at
   runtime. Never put secrets in `NEXT_PUBLIC_*`, build arguments, logs or source.
   Keep signing keys consistent between replicas and normal recovery. Rotation
   intentionally invalidates sessions and requires an operator plan.
4. Configure private DB routing, verified remote TLS and separate owner/runtime
   roles. The app needs normal DML/SELECT and no schema ownership, DDL, superuser
   or public schema CREATE. Scope any approved migration to the intended target;
   verify a fresh backup before modifying an existing database.
5. Run the release migration job as the owner: inspect `alembic current`, upgrade
   to reviewed `20261022_05`, inspect current again. API startup never migrates.
   Gate traffic on `/ready` 200; `/health` is liveness only. Configure restart/backoff
   and bounded probes, including recovery after database unavailability.
6. Terminate HTTPS at the trusted gateway, restrict backend ingress and configure
   shared auth/research/request quotas before acknowledging
   `GATEWAY_RATE_LIMIT_ENABLED=true`. Bind quota identity to trustworthy socket
   clients; ignore or replace untrusted forwarding headers. Keep Uvicorn proxy
   trust disabled unless its exact gateway addresses are reviewed. A single
   gateway's shared state does not coordinate independent gateway hosts.
7. Verify real frontend/API cookies and CORS at chosen origins: Secure/HttpOnly,
   host-only `__Host-` names, SameSite=Lax for same-site domains, credentialed
   requests and session-bound CSRF on unsafe methods. Exercise login/logout,
   reload, expiry, saved/exact/slip writes and cross-user denial. Cross-site
   SameSite=None needs additional browser-policy verification.
8. Configure bounded, redacted logs and alerts for readiness, errors, quota stops
   and backup failure. Exclude auth bodies and Cookie/Set-Cookie/Authorization/CSRF
   headers; avoid raw secret-bearing URLs and request queries. Local stdout is
   not managed log retention or alert delivery.
9. Test a fresh encrypted-backup restore into a separate database, recreate roles,
   grants and secrets, then verify readiness, authentication, UUIDs and exact
   sportsbook/line/side/original-observation preservation. Record recovery time,
   retention and acceptable data-loss objectives. A logical fixture restore is
   not failover, PITR, concurrent-write recovery or a cross-major DB test.
10. Prefer a compatible code rollback against the additive schema. Revision 05
    downgrade deletes exact selections; do not use it as routine rollback. Public
    release requires its own explicit authorization after the actual host gates.

## Reproduce locally

Use Windows PowerShell, Docker Desktop's local Linux engine, the existing backend
Python environment and installed Chrome. The gateway's `host.docker.internal`
frontend route is scoped to this setup; another host needs its own reviewed route.
Use a clean reviewed source export with the Stage 3 Dockerfile, not an unchecked
working-tree build. Keep the exact image digests above with the evidence: package
repositories/scanner databases can change on a later rebuild. Existing private
state is intentionally not overwritten; preserve it before preparing a new run.
These commands create disposable resources, never the development Compose stack.
The reproduction commands now use the follow-up images and helper defaults.
Reproducing the original Stage 3 image requires its original checkpoint source,
not the current hardened Dockerfile. The separate follow-up regression also
supports a fresh evidence directory without changing retained Stage 3 artifacts.

```powershell
$py = '.\backend\venv\Scripts\python.exe'
$localEngine = 'npipe:////./pipe/docker_engine'
$state = 'backend/data/odds_runs/security-stage3'
$fixture = (Resolve-Path backend/tests/production_stack_fixture.py).Path
docker --host $localEngine build -t proppulse-backend:hardened backend
Get-Content -Raw backend/docker/postgres.Dockerfile | docker --host $localEngine build -t proppulse-postgres:nonroot -
docker --host $localEngine build -t proppulse-security-stage3-gateway:final -f backend/tests/production_gateway.Dockerfile backend/tests
& $py backend/tests/production_stack_control.py prepare
& $py backend/tests/production_stack_control.py start-networks
& $py backend/tests/production_stack_control.py start-db
& $py backend/tests/production_stack_control.py provision
docker --host $localEngine run --rm --network pp-stage3-private --env-file "$state/owner.env" --mount "type=bind,source=$fixture,target=/tmp/production_stack_fixture.py,readonly" proppulse-backend:hardened python /tmp/production_stack_fixture.py bootstrap
Get-Content -Raw "$state/grant-app.sql" | docker --host $localEngine exec -i pp-stage3-db psql -U stage3_admin -d proppulse_test_stage3 -v ON_ERROR_STOP=1
docker --host $localEngine run --rm --network pp-stage3-private --env-file "$state/app-check.env" --mount "type=bind,source=$fixture,target=/tmp/production_stack_fixture.py,readonly" proppulse-backend:hardened python /tmp/production_stack_fixture.py verify-app-role
& $py backend/tests/production_stack_control.py start-api
& $py backend/tests/production_stack_control.py start-gateway
```

Build the frontend with `NEXT_PUBLIC_API_URL=https://api.proppulse.test:3443`,
then start Next on host port 3199, accessible to the local gateway. From `frontend`,
run `npm test`, `npx tsc --noEmit`, `npm run build`, then
`node node_modules/next/dist/bin/next start --hostname 127.0.0.1 --port 3199` in its
own terminal. Set the production-browser fixture variables from `bootstrap`'s
synthetic IDs; retain the default FanDuel/20.5 offer. From `frontend`:

```powershell
$env:PRODUCTION_TEST_PROP_ID = '00000000-0000-0000-0000-00000000012c'
$env:PRODUCTION_TEST_PLAYER_ID = '00000000-0000-0000-0000-0000000000c8'
$env:PRODUCTION_TEST_EXPIRED_PROP_ID = '00000000-0000-0000-0000-000000000137'
$env:PRODUCTION_TEST_PLAYER_NAME = 'Fixture Stack Player'
npx playwright test --config playwright.production-security.config.cjs
```

Do not substitute retained provider data or credentials.

Run `backend/tests/production_gateway_probe.py` from the repository root after
browser flows; it restarts only the labelled gateway and consumes test quotas.
Use `--gateway-only` when retesting its patch without consuming the app backstop
again. Mount `production_image_probe.py` read-only into the final backend image
with `--network none` and the private synthetic `api.env` to check the actual
installed/native runtime. Scan exported exact images rather than source manifests;
retain scanner version/database time and distinguish package rows from distinct IDs.

For recovery, use the exact labelled disposable DB container and a custom-format
dump of `proppulse_test_stage3`, excluding owner/ACL. Restore with exit-on-error and
a single transaction into the separately created, empty
`proppulse_test_stage3_restore`; recreate reviewed app grants. Compare fixture
`fingerprint` results before/after and execute the real app's readiness/auth/saved
checks on the restored database. Never use `--clean`, development URLs or an
existing restore target. Signing secrets require separate preservation.

Stop only the frontend process started for this run, then invoke the tracked
control helper's `cleanup`. It verifies ownership labels and targets only the
named `pp-stage3-*` resources; it does not delete images, volumes or private
evidence. Verify no test listeners/containers remain. Private state, certificates,
dumps, backups and approval artifacts must not be committed.

## Checkpoint limits and release decision

Local production-path verification is complete, including final-image fresh
bootstrap and recovery on the current PostgreSQL image. No public deployment
readiness is claimed. Public hosting configuration, current DB helper
advisory disposition, OS residual review, managed restore/retention and operational
ownership remain release gates. Full fleet load, cold starts, PITR/failover,
cross-major DB recovery, Firefox/WebKit and sports-provider coverage were not tested.

Current provider availability, source/history completeness and historical odds
movement remain bounded by the existing real data. A fixture snapshot test does
not create or certify genuine market history. No new provider collection, data
repair, synthetic production rows or availability claims were introduced.

Final `/health` and `/ready` returned 200 before cleanup. The tracked helper then
removed only five exact task-labelled containers (two APIs, gateway, source DB,
restore DB) and two task-labelled networks; label-filtered inventories are empty.
The owned frontend process was stopped and ports 3199/3443 have no listener.
Images and private certificates/env files/dumps/scans remain retained and ignored.
Stage 3 changes Docker packaging, test harnesses and documentation, without
application feature or authentication-contract changes.
