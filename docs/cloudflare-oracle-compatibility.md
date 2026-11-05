# Cloudflare Free + Oracle Always Free compatibility

Assessment date: November 4, 2026 (America/Toronto). No cloud resources, billing, deployments, provider requests, or development database changes were authorized or performed.

Evidence labels: **Execution** = verified by local execution; **Official** = verified from official documentation; **Estimated** = engineering estimate; **Unverified** = not yet verified. Local ARM64 execution uses Docker Desktop emulation on AMD64, not an Ampere capacity benchmark.

## Verdict

**Compatible with changes, with $0 sustainability not yet proven.** The proposed split is plausible for a low-traffic portfolio, but a guarantee of permanent, reliable $0 hosting is unjustified. Static Pages cannot preserve the current routes. Workers requires a compatibility patch and has a tight SSR CPU allowance. Oracle allocation and reclamation remain external risks. The two-subdomain cookie design also requires an existing domain or a domain purchase.

## Repository isolation

**Execution:** Fresh HTTPS clone of public `master`, initially clean at `9b84a1f948e4f7fa2fddca26ce36315bf5c3aa2d`; `git rev-list --count HEAD` = 2. Clone is in the assessment workspace's `public-assessment` directory. No local clone, reference repository, object alternates, private-history import, commit, push, reset, or history rewrite. The original project checkout was inspected read-only for identification and left unchanged. All compatibility work is uncommitted in this independent public clone.

## Current free allowances

**Official:** These are ongoing allowances, not promises that plans will never change. Pages static requests are free and unlimited; Functions share Workers request limits ([Pages pricing](https://developers.cloudflare.com/pages/functions/pricing/)). Pages static hosting cannot execute SSR; Workers/OpenNext can.

| Service | Current free allowance / constraint | Source |
| --- | --- | --- |
| Pages | 500 builds/month, one concurrent build, 20-minute timeout; 20,000 files, 25 MiB/file; 100 custom domains/project | [Pages limits](https://developers.cloudflare.com/pages/platform/limits/) |
| Workers runtime | 100,000 script requests/day, 10 ms CPU/request, 128 MB/isolate, 50 subrequests/request, six concurrent outgoing connections, one-second startup; current table says 64 MiB Worker size | [Workers limits](https://developers.cloudflare.com/workers/platform/limits/) |
| Workers static assets | Free unlimited asset requests/storage; script invocation uses Workers quota | [Assets billing](https://developers.cloudflare.com/workers/static-assets/billing-and-limitations/) |
| Workers Builds | 3,000 build minutes/month, one build at a time, 20-minute timeout, 2 vCPU/8 GB RAM/20 GB disk | [Build limits](https://developers.cloudflare.com/workers/ci-cd/builds/limits-and-pricing/) |
| Oracle A1 | 1,500 OCPU-hours and 9,000 GB-hours/month: 2 OCPU + 12 GB continuously, shared across A1 instances, home region only | [Always Free](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm) |
| Oracle storage/network | 200 GB combined boot/block storage; five volume backups; 10 TB monthly outbound transfer. Budget a 50 GB boot volume (the same page inconsistently also mentions 47 GB minimum) | [Always Free](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm) |

**Official:** A1 is ARM. Capacity can be unavailable. Idle instances can be reclaimed when, over seven days, CPU p95, network and A1 memory utilization are each below 20%. This is particularly relevant to a quiet portfolio; do not manufacture load to evade it. These conditions come from [Oracle Always Free](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).

**Official:** Oracle's $300/30-day trial is temporary. Signup generally requires a phone and card; the card is not charged unless the account is upgraded. Trial-only resources do not become permanently free. Stay within Always Free totals before trial expiry. See [Free Tier lifecycle](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier.htm) and [identity/card requirements](https://www.oracle.com/cloud/free/faq/).

**Official / Unverified:** OCI documents ephemeral and reserved IPv4; ephemeral assignment requires a public subnet/VNIC, route and ingress rules. General limits are not a guarantee of a new free tenancy's allocation. Use one attached public address; confirm the console's entitlement and cost before provisioning. Oracle's [networking article](https://blogs.oracle.com/developers/setting-up-a-virtual-cloud-network-vcn-in-oracle-cloud-infrastructure) says public addresses are uncharged, but is dated 2020; the current [IP documentation](https://docs.oracle.com/en-us/iaas/Content/Network/Tasks/managingpublicIPs.htm) explains assignment, not pricing. No tenancy-specific IPv4 availability was verified.

**Estimated:** Paid shapes, extra compute hours/RAM/storage/backups, out-of-home-region volumes, excessive transfer and optional paid services can create charges after a PAYG upgrade. Avoid managed database/load-balancer add-ons unless explicitly reviewed. Domain registration, provider subscriptions and Cloudflare Images are separate costs. Workers Paid starts at $5/month ([pricing](https://developers.cloudflare.com/workers/platform/pricing/)); no paid binding is needed by the current frontend.

## Frontend

**Execution / source inspection:** Next.js 15.5.28, React 19.0.9, App Router. Empty `next.config.ts`. Layout remains a server component. Route screens fetch FastAPI data in the browser. Fixed routes `/`, `/discover`, `/players`, `/analytics`, `/login`, `/profile`, `/saved` can be prerendered. `/player/[id]` and `/games/[gameKey]` require runtime route handling; no `generateStaticParams`. No API route handlers, middleware, Server Actions, `next/image`, server-cookie reads or direct Node runtime imports were found in application source. Browser APIs are used in client code. Next itself still needs an adapter for dynamic requests.

**Execution:** An actual `output: 'export'` production build failed: `/player/[id]` lacks `generateStaticParams()`. Temporary export configuration was restored byte-for-byte. Enumerating today's IDs would break future identities; SPA fallback tricks do not provide normal Next navigation/RSC behavior. Pages is therefore rejected for the unchanged functionality, consistent with [Next static export restrictions](https://nextjs.org/docs/app/guides/static-exports) and [Cloudflare's static Pages guide](https://developers.cloudflare.com/pages/framework-guides/nextjs/deploy-a-static-nextjs-site/).

**Official:** Cloudflare currently recommends beta vinext for new Next.js 16 migration work; OpenNext remains documented. For this Next.js 15 app, test OpenNext rather than change the framework/toolchain: [current recommendation](https://developers.cloudflare.com/workers/framework-guides/web-apps/nextjs/), [manual OpenNext configuration](https://developers.cloudflare.com/workers/framework-guides/web-apps/opennext/). `nodejs_compat` and a compatibility date >= 2024-09-23 are required.

**Execution:** Adapter 1.20.16 refuses Next 15.5.28; peer range starts at 15.5.29. Minimum patch applied in this clone; no forced peer override. Wrangler 4.157.0 and adapter pinned. Native Windows target build reached compilation/type checks, then failed creating standalone output with EPERM. The Linux retry built the actual OpenNext Worker successfully. Wrangler dry-run read 47 static assets and reported 5,068.01 KiB raw / 1,034.91 KiB gzip upload; only ASSETS is bound. This fits even the older 3 MiB free bundle guidance; current official limits list 64 MiB. Local workerd startup needed a public CA bundle absent from the disposable slim Node test image. All 121 frontend Node tests passed, including credential inclusion, CSRF rotation, session restoration and retained saved/slip state.

**Execution / inspection:** `NEXT_PUBLIC_API_URL` is the sole frontend environment reference and is embedded at build time; set `https://api.example.com` before building. Runtime environment changes do not update shipped JS. Default localhost must never reach a public build. `api.ts` sends `credentials: 'include'` and `cache: 'no-store'`, bootstraps `/auth/csrf`, and adds `X-CSRF-Token` to mutations. `AppInit` restores `/users/me` before saved/slip hydration. The actual Worker passed Chrome direct-route checks for Discover, Players, player/game identities, Saved, Profile and Login, a client-side Players link, offline successful session/saved/slip hydration, rejected login and the CSRF header. Every external request was intercepted; no browser exceptions or unexpected origins occurred. This verifies the configured API URL in the shipped bundle, not hosted cookie issuance or real cross-subdomain browser security. Safari/Firefox remain untested.

## Backend, native dependencies and PostgreSQL

**Execution:** Unchanged backend Buildx command: `docker buildx build --platform linux/arm64 --load -t proppulse-assessment-backend:arm64 -f backend/Dockerfile backend`. Both digest-pinned Python 3.11 slim and distroless Debian 13 bases resolved for ARM64. The Dockerfile mandates binary wheels; no source fallback is permitted. Full lock is unchanged. Assembly derives `MULTIARCH` via `sysconfig`, not an x86 path. Final image build succeeded (1,064,529,912 bytes), pip check passed, and runtime inventory matched the entire lock. No native source compilation or Dockerfile/lock change was needed.

**Execution:** Hardened PostgreSQL derivative built unchanged for ARM64 from its pinned PostgreSQL 15 Alpine digest. It reports PostgreSQL 15.19/aarch64, starts as UID/GID 70, has no gosu, and initializes successfully with UID70-owned PGDATA/socket tmpfs. `pg_isready`, SQL, empty custom-format `pg_dump` and `pg_restore` passed. Image size is 407,784,583 bytes as reported by Docker. Initial observed memory was 113 MiB under emulation, including a tmpfs database; this is not a disk-backed A1 estimate.

**Execution / Unverified:** A separately created UID70-owned named volume initialized under a read-only root with dropped capabilities. Revision-05 logical restore and restart retained the revision and one disposable test account. OCI block-volume mounting, reboot and crash recovery still require a hosted rehearsal. Precreate/chown only the new deployment PGDATA and socket paths for 70:70, with PGDATA mode 0700; root entrypoint ownership repair fails closed because gosu was removed. Publish no 5432 port. Use a private Docker network and a separate application database role. Never attach the development volume. Migrate through `20261022_05` explicitly; readiness validates it and never repairs schemas. Current public lifespan does not call `create_all` (the root instructions describe older behavior). Refresh must remain disabled.

**Estimated:** Transfer PostgreSQL across architectures with logical `pg_dump -Fc --no-owner --no-acl` and `pg_restore --exit-on-error --no-owner --no-acl` into a separately initialized database; recreate restricted roles deliberately. Do not copy an AMD64 PGDATA directory. Restore checks must include revision, constraints, row identity and authentication/saved/slip behavior. [PostgreSQL dump documentation](https://www.postgresql.org/docs/15/app-pgdump.html).

## Resources and sustainability

**Estimated, not measured A1 capacity:** One backend worker and 2 OCPU/12 GB A1 should leave useful headroom for a small demo. Start conservatively; do not run model training or ingestion in request handlers.

| Component | Planning budget |
| --- | --- |
| Backend idle | 150–350 MiB, without eager ML loading |
| Ordinary research query | Additional 50–250 MiB, sensitive to database size/results |
| Scientific stack + small ML execution | 0.5–2 GiB; larger training/SHAP can exceed this substantially |
| PostgreSQL | 300 MiB–1 GiB with bounded connections and modest buffers |
| Nginx | 20–80 MiB |
| OS + Docker | 0.7–1.5 GiB |
| Combined small-demo target | Roughly 2–5 GiB; reserve several GiB for spikes/cache |

**Estimated:** Two physical A1 cores are suitable for light traffic, not an established concurrency guarantee. Cap BLAS/OpenMP threads at one or two and begin with one Uvicorn worker; each additional worker duplicates memory and connection pools. ML/JIT cold starts can take seconds or longer. A 1–2 GiB swap file is an emergency buffer, not capacity; alert on swap/oom. No load test or A1 latency/concurrency benchmark was performed.

**Estimated:** Budget 10–15 GB OS, 10–20 GB images/update rollback, 5–10 GB build cache if building on-host, 1–10 GB small demo database/WAL and 5–20 GB rotated backups; roughly 35–75 GB initially. Prefer externally built ARM images, a 50 GB boot plus a modest separate data volume within 200 GB, bounded logs and retained backups. Database growth cannot be inferred from an empty fixture; snapshots/game logs can dominate. Keep free space alerts and an independently recoverable encrypted backup; same-VM backups alone do not survive VM loss. A1 availability and idle reclamation prevent treating this as reliable unattended permanent hosting.

## HTTPS, cookies and gateway

**Official / source inspection:** Use `https://app.example.com` (Workers) and `https://api.example.com` (Oracle gateway). They are same-site HTTPS siblings but distinct origins. Host-only `__Host-proppulse_session` and `__Host-proppulse_csrf` cookies belong to API only: Secure, HttpOnly, Path=/, SameSite=Lax, no Domain. The existing CSRF proof is returned in JSON; frontend does not need to read HttpOnly cookies. See [browser cookie rules](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Set-Cookie).

**Estimated configuration:** Set backend `ENVIRONMENT=production`, a generated private JWT secret, a private PostgreSQL `DATABASE_URL`, `LIVE_REFRESH_ENABLED=false`, `AUTH_COOKIE_SAMESITE=lax`, and `CORS_ORIGINS=["https://app.example.com"]`. Permit credentials and the existing JSON/CSRF headers. Origin must match exactly; Referer fallback is checked if Origin is absent. Do not wildcard origins or allow preview origins implicitly. Test session reload, logout, CSRF rejection, unavailable offers and selection persistence through real HTTPS.

**Official / recommended:** Cloudflare Free provides [Universal SSL](https://developers.cloudflare.com/ssl/edge-certificates/universal-ssl/). Use [Full (strict)](https://developers.cloudflare.com/ssl/origin-configuration/ssl-modes/full-strict/) to an Nginx TLS origin with a valid certificate. No Flexible TLS. Disable API caching, retain Set-Cookie/no-store and OPTIONS/CORS behavior. Restrict ingress to Cloudflare networks on 443 and operator SSH; reject unknown Host/SNI and prevent direct API:8000/DB:5432 exposure. An IP allowlist alone does not authenticate your Cloudflare zone: add authenticated origin access (reviewed secret header or authenticated tunnel/origin pull) and test bypass resistance.

**Execution (source inspection) / Unverified:** Existing `production_gateway.conf` is a local two-backend test gateway, not deploy-ready configuration. It implements shared Nginx quotas (10 auth POST/minute, 30 API requests/second with bounded bursts); `GATEWAY_RATE_LIMIT_ENABLED=true` merely acknowledges an actual gateway. Configure and test real quotas before enabling it. Trust `CF-Connecting-IP` only from validated Cloudflare ingress, replace client forwarding headers, and never accept arbitrary X-Forwarded-For. See [Cloudflare header behavior](https://developers.cloudflare.com/fundamentals/reference/http-headers/).

**Execution (source inspection):** Hardened Uvicorn defaults to `--no-proxy-headers`, so app backstop quotas see the gateway IP and can aggregate unrelated users. Keep conservative aggregation or explicitly enable proxy parsing only from a fixed trusted gateway address after it replaces forwarding headers; never `forwarded-allow-ips=*`. Gateway quotas must still use validated client identity. Spoofing and cross-zone Worker requests need hosted verification.

**Estimated verdict on domains:** The requested sibling-host design needs control of a registrable domain. Hosting/certificates can be free; buying/renewing a domain is not. Therefore the total is not strictly $0 unless a suitable domain is already owned. `pages.dev`/`workers.dev` frontend plus an unrelated Oracle/free-DNS API hostname is cross-site: SameSite=Lax cannot support fetch authentication. Do not switch to insecure or third-party-cookie-dependent behavior.

**Unverified no-domain alternative:** Serve frontend and `/api/*` from a single `workers.dev` hostname, proxying API requests through a small Worker to a stable authenticated HTTPS Oracle origin. Build with `NEXT_PUBLIC_API_URL=/api`, preserve Origin/CSRF/cookies/no-store, and prevent origin bypass. Browser cookies then remain first-party without altering their flags. Requires a stable free origin hostname/certificate or another supported secure ingress, proxy implementation, trustworthy rate identity and quota/CPU tests; not implemented here. Quick tunnels are not a production availability solution.

## Security and operations

**Execution (source inspection) / Unverified hosted:** Existing images support backend UID10001, read-only root, dropped capabilities, no-new-privileges, writable size-bounded /tmp and /app/data only as needed; PostgreSQL UID70 requires writable PGDATA/socket. These can be preserved on Docker on A1. Current development Compose publishes DB/Redis, binds code, uses reload and an env file: do not deploy it. Redis is not required by current application caching. Use a reviewed production manifest, internal DB network, secret injection outside Git, restart-unless-stopped, health/readiness, log rotation/redaction and external uptime/disk/memory alerts. Readiness must not mutate schema. Do not ship tests or package installers in the runtime image.

**Unverified hosted:** TLS issuance/renewal, OCI firewall behavior, actual edge quotas, secret permissions, persistent mount recovery, external monitoring and backup recovery are not verified by local tests. Image updates should pin reviewed multiarch digests, run binary/native/auth/migration probes, retain rollback images, and take/test logical backups before schema upgrades. Never blindly pull mutable latest tags or rewrite existing DB state on container startup.

## Portfolio data

**Execution (source inspection) / recommendation:** An empty, explicitly migrated database can show honest empty/unavailable research states and real user authentication/persistence. Existing offline Playwright fixtures and `docs/portfolio-demo.md` can demonstrate populated interactions without importing private data. Prefer an explicitly labeled offline replay/video alongside the empty real app. A public interactive synthetic mode would need a deliberately separate fixture data path and visible labels: existing research services exclude synthetic odds, so seeding invented sportsbook offers is not an acceptable shortcut. No provider data or sports fixture import was performed; no recurring paid collection is needed for this presentation strategy.

## Alternatives (assessment only)

| Alternative | Assessment |
| --- | --- |
| Cloudflare + Cloud Run + Neon Free | **Official / Estimated:** Linux AMD64 containers support the native Python stack. Request-based Run allowance: 180k vCPU-seconds, 360k GiB-seconds and 2M requests/month (regional pricing basis); requires billing and charges above allowance. Scale-to-zero means cold starts; min instances, egress, registry/builds and gateway controls can cost extra. Neon currently gives 100 CU-hours/project/month and 1 GB/project, no card, scales down after five idle minutes. Persistent PostgreSQL is separate; cannot assume the exact UID/capability/network controls of an OCI VM. Possible $0 light usage, not a hard spending cap. |
| Cloudflare + Koyeb Free + Neon | **Official / Estimated:** Docker/FastAPI supported; one free instance, 512 MB RAM/0.1 vCPU/2 GB disk, no persistent volume, sleeps after one hour. Too little margin for the full scientific stack and gateway; no proven full-app compatibility. Current pricing FAQ requires card verification and warns selected Pro plan is charged at signup. No unconditional $0 recommendation. |

Sources: [Cloud Run prices](https://cloud.google.com/run/pricing), [billing requirement](https://docs.cloud.google.com/free/docs/free-cloud-features), [runtime ABI](https://docs.cloud.google.com/run/docs/container-contract), [Neon current pricing](https://neon.com/pricing), [Koyeb free limits](https://www.koyeb.com/docs/reference/instances), [Koyeb signup charges](https://www.koyeb.com/docs/faqs/pricing). Hugging Face Docker Spaces is not a genuinely free fallback for a new free personal account: current [Spaces documentation](https://huggingface.co/docs/hub/spaces-overview) requires a paid plan to create compute Spaces. Render excluded. No alternative implemented.

## Final execution evidence and next milestone

**Execution:** ARM64 native probes passed under `--network none --read-only --cap-drop ALL --security-opt no-new-privileges`, with bounded /tmp. No installer/admin binaries, no setuid files, working CA roots/timezones/stdlib shared libraries. Native results:

| Locked component | Result |
| --- | --- |
| Python 3.11 / FastAPI 0.135.4 / Uvicorn 0.29.0 | Final image and application lifespan execute on aarch64 |
| psycopg2-binary 2.9.9 / SQLAlchemy 2.0.30 / Alembic 1.13.1 | Actual PostgreSQL connection and revision-05 migration passed |
| NumPy 1.26.4 / pandas 2.2.2 / SciPy 1.17.1 | ARM wheels install, runtime import and array/data-frame operations passed |
| scikit-learn 1.5.2 | RandomForest fit/predict passed |
| XGBoost 2.0.3 / SHAP 0.45.0 | XGBRegressor fit + finite TreeExplainer SHAP values passed |
| Numba 0.68.0 / llvmlite 0.50.0 | Actual parallel JIT reduction passed using OpenMP; optional TBB not needed |
| bcrypt 4.0.1 / passlib 1.7.4 / PyJWT 2.15.1 | Hash/verify and valid/expired/wrong-algorithm rejection passed |
| Other locked dependencies | Binary/pure-Python resolution and pip/metadata dependency checks passed; not every optional code path exercised |

**Execution:** Disposable ARM64 PostgreSQL + backend passed `/health`, `/ready`, empty `/players/search`, empty `/props/discover`, registration, secure host-only cookie attributes, `/users/me`, Saved/Slip reads, invalid-CSRF rejection and valid logout. Both final images are ARM64; no AMD64 data volume was copied. Actual final-command Uvicorn startup passed health/readiness on the isolated network, using 126.5 MiB idle in Docker stats. API/auth probe peak process RSS was 167,640 KiB (~164 MiB); complete native probe peak was 511,344 KiB (~499 MiB). These emulated small-fixture observations do not establish A1 performance or real-data query capacity. Read-only-root PostgreSQL after restart used ~44 MiB in Docker stats, with no meaningful data workload.

**Execution:** TypeScript no-emit passed; frontend Node tests 121/121 passed; Chrome Worker probe passed. Full ARM64 backend run: 1,145 tests, 862 passed, 282 opt-in PostgreSQL tests skipped, one failed; zero external HTTP transport attempts. Failure: `test_successful_write_of_stale_observation_reports_last_known` in `test_milestone2_ingestion.IsolatedPersistenceTests`. Existing ingestion code collects only actionable decisions, then tries to derive last-known status from that collection; last-known is non-actionable. This unchanged source mismatch is not an ARM wheel failure. Do not claim the full backend suite passes. Broader PostgreSQL opt-in suites were not run; the disposable actual-image migration/auth/restore probes were run instead. Lint/security scanners, live provider checks, hosted deployments, gateway load tests and real A1 benchmarks were not run.

**Unverified / next milestone:** Prepare a production-only Compose/gateway manifest and local real-HTTPS sibling-domain rehearsal, with no deployment. Check quota enforcement/spoof resistance, actual cookie restoration and saved/slip persistence, least-privilege DB credentials and recovery. After separate deployment approval: confirm OCI A1/IPv4 allocation, domain ownership and cost, then test Workers Free CPU/startup and native A1 memory/latency before promising $0 hosting. Local workerd does not enforce/prove the hosted 10 ms CPU allowance. If dynamic route SSR exceeds it, Workers Paid would violate $0; consider a separately scoped routing change only with that evidence.

Changed files: `.gitignore`; `frontend/package.json`; `frontend/package-lock.json`; `frontend/open-next.config.ts`; `frontend/wrangler.jsonc`; `frontend/playwright.cloudflare.config.cjs`; `frontend/e2e/cloudflare-compatibility.spec.cjs`; `backend/tests/cloud_arm64_assessment.py`; this report. No application features, Python lock, Dockerfiles, data models or existing history changed. Build/probe logs and disposable dumps are kept outside Git in the sibling `assessment-evidence` directory.

Final Git checkpoint: public HEAD remains `9b84a1f948e4f7fa2fddca26ce36315bf5c3aa2d`, two commits, all nine listed files uncommitted. `git diff --check` passed. Build logs are generated evidence, not source changes. The existing unrelated ingestion-status regression remains a release-quality blocker to resolve before deployment; it does not prevent ARM64 builds/native execution.

Reproduction: from `frontend`, run `npm ci`, set `NEXT_PUBLIC_API_URL=https://api.example.com`, then `npm run build:cloudflare` on Linux. Preview with `npm run preview:cloudflare`; run `npx playwright test --config playwright.cloudflare.config.cjs` from another terminal (offline API intercepts). Use `wrangler deploy --dry-run` only to measure the bundle. Backend: build the unchanged Dockerfile with `--platform linux/arm64`, mount existing `backend/tests` read-only at `/fixture`, and run `python /fixture/container_runtime_probe.py` with test-only production settings, no network and bounded /tmp. The new `cloud_arm64_assessment.py` requires the exact disposable `pp-assess-pg/assessment` target and an empty database; it migrates/registers a dummy user and must not be pointed at a retained database. Full regression used `tests/run_no_provider_http.py` in an ARM64 network-none container with source mounted read-only; no development environment file was loaded.
**Execution:** Assessment containers, the internal assessment network and all three task-created disposable volumes were removed successfully. Built images and local build/evidence files remain for review. Original private checkout HEAD/status matched the initial checkpoint at handoff. No commits or pushes.

## Local commit review

The Next.js patch and pinned OpenNext/Wrangler tools are intentional compatibility changes. The retained Worker output contains the example HTTPS API origin and no localhost:8000 API origin; generated output is ignored and excluded from the commit. Deployment must rebuild with the actual approved HTTPS API origin. The assessment script now rejects optimized Python, alternate URL query routing, unexpected ports/targets and effective configuration mismatch; it verifies physical database/role and ARM64 before migration. Only the nine listed source/documentation files are in scope. Existing ingestion-status behavior remains unchanged. The uncommitted Git checkpoints above describe the original assessment handoff, before the separately authorized local commit. No hosting limitations have been resolved by committing these files.
