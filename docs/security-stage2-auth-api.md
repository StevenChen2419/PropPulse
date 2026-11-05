# Security Stage 2: browser sessions and API boundaries

October 23, 2026. Starting HEAD `6973ca08b30924f56715154d68382bad1bd16dd7`.
Stage 2 was implemented uncommitted; a subsequent owner instruction authorizes
exactly one local Stage 2 commit. No development database changes/migrations,
provider calls, deployment, push or Stage 3 work.

## Session and JWT contract

- Login/register now return only `{ "ok": true }`, with the JWT only in an
  HttpOnly session cookie. There is no browser token-return endpoint. `/users/me`
  restores identity on reload. Password hashing remains passlib/bcrypt.
- Host-only cookies omit Domain. Path `/` is necessary because authenticated
  routes span `/auth`, `/users`, `/players` and `/interactions`. Development names
  are `proppulse_session` / `proppulse_csrf`; production/staging use `__Host-`
  prefixes, Secure and HttpOnly. SameSite defaults to `lax`.
- `JWT_EXPIRE_MINUTES` defaults to 120: absolute expiry, no silent refresh.
  Cookie Max-Age matches signed expiration. Production/staging reject values over
  1440; existing longer development settings remain loadable. Logout validates
  CSRF and deletes both cookies with matching attributes. Failed logout stays
  visibly failed; it does not falsely clear an active session.
- PyJWT **2.15.1** replaces python-jose. Only HS256 is accepted; signed expiration
  and subject are required, expiry checked, subject validated as a UUID before
  account lookup. `none`, RSA, HS384, bad signatures and malformed subjects fail.
  An independently constructed legacy HS256 UUID/exp token still verifies.
  No password/account/schema migration is needed.
- Explicit bearer headers remain supported for existing nonbrowser tooling, but
  session cookies always take precedence, including invalid cookies. Auth routes
  never return bearer credentials. Frontend never reads/stores/transports a JWT;
  startup removes the obsolete localStorage token without reading its value.
  Existing browser users sign in again once; their server-side saved/slip rows
  are preserved. Legacy nonbrowser HS256 tokens remain compatible until expiry.
- Stateless limitation: logout cannot revoke a copied cookie/bearer token before
  expiry. No revocation database, password reset/recovery, verification email or
  refresh-token machinery is claimed. Register has an API but no existing UI.

## CSRF and browser deployment

`GET /auth/csrf` returns a non-JWT HMAC proof bound to a random HttpOnly nonce
cookie and the session token digest. Proof is kept only in JavaScript memory;
the JWT is never disclosed. All cookie-authenticated unsafe methods require
`X-CSRF-Token` plus an exact configured trusted Origin. Referer origin is used
only if Origin is absent; null/untrusted origins, userinfo, missing/invalid proof
or another session's proof fail 403. Login, registration and logout always require
this protection, including anonymous sessions. Current-user dependencies cover
saved bookmarks, exact selections, slips, preferences and player follows.

Credentialed fetches use `credentials: include` and no-store. CSRF bootstrap is
shared for concurrent writes; successful login/register/logout invalidate cached
proof. A rejected proof invalidates cache so a user retry can obtain a new proof;
mutations are not automatically replayed. CORS allows credentials only for exact
configured origins and explicitly admits the CSRF header. CORS alone is not the
CSRF control. Design follows [OWASP's signed/session-bound proof and origin
guidance](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html).

Prefer HTTPS same-site domains (`app.example.com` and `api.example.com`) with lax
cookies. Separate sites require `AUTH_COOKIE_SAMESITE=none`, HTTPS/Secure and the
same CSRF defenses. Nonproduction HTTP with `none` is rejected. Third-party cookie
blocking can still prevent cross-site sessions: use same-site custom domains or
a same-origin gateway in that case. For local HTTP, use the same hostname on both
ports (both localhost or both 127.0.0.1). Real browser checks here use separate
ports on 127.0.0.1; they do not prove public HTTPS/cross-site hosting behavior.

## Abuse controls and proxy assumptions

Built-in sliding-window backstop, keyed by ASGI client address and a hash of
trimmed/casefolded email. Passwords, raw email keys, cookies and forwarding headers
are not stored in limit state. The state has at most 4096 keys, expired windows
are reclaimed, and capacity exhaustion fails closed without evicting live limits.

| Operation | Client limit | Account limit |
| --- | --- | --- |
| Login | 20 / 15 minutes | 10 / 15 minutes |
| Registration | 5 / hour | 3 / hour |
| Research/feed/props/rankings/fatigue/game-log | 120 / minute | N/A |
| Other API operations (except probes/OPTIONS) | 300 / minute | N/A |

Limits return generic 429 and Retry-After before password hashing/database work.
Account limits span different clients; spoofed X-Forwarded-For/Forwarded values
do not change identity. Login has generic errors and equal bcrypt verification
work for missing accounts. Duplicate and concurrent registration failures have
the same generic message, without submitted email/driver diagnostics. Successful
registration still reveals that a new account was created; no verified-email
flow is claimed. Account throttling can temporarily affect the targeted account.

Process-local limits reset on restart and do not coordinate workers/instances.
**An actual trusted gateway must enforce fleet-wide auth and API quotas before
public deployment.** Production startup requires explicit
`GATEWAY_RATE_LIMIT_ENABLED=true` acknowledgement; the flag does not provision or
verify a gateway. Do not enable it without that deployment control.

Docker defaults to `--no-proxy-headers --no-access-log`. Middleware never parses
forwarding headers. If the selected host needs proxy-derived client IPs, explicitly
configure Uvicorn `--proxy-headers --forwarded-allow-ips=<actual trusted gateway
addresses/CIDRs>` and prevent direct ingress around that gateway. Never trust `*`
on a publicly reachable listener. Without trusted forwarding, users behind a
gateway share its socket-address backstop. Uvicorn's existing proxy middleware
must be configured, rather than trusting headers again inside the application.

## API and authorization

- Request bodies are limited to 1 MiB by default (`API_MAX_BODY_BYTES`, bounded
  configuration), checked against both Content-Length and streamed bytes before
  parsers/routers. Body read has a total 15-second deadline. Current mutation
  contracts require JSON when a body is supplied; no production upload route
  exists. Download/PDF response sizes are not limited. Isolated upload compatibility
  tests remain intact; a future upload route must explicitly review its limits.
- Query strings max 4096 bytes; feed/games/discover page sizes have positive bounds,
  offsets 0..1,000,000, text filters bounded, research line inputs finite. Existing
  player search has 80-character text and 1..50 result bounds. Authentication,
  usernames and preference arrays/values are bounded before costly work.
- Saved/selections/slip ownership stays enforced in SQL against the verified
  current user, including negative edit/delete/copy tests. Profile/preference and
  watchlist operations resolve the current user, not a submitted owner ID. No
  administrative application endpoints exist. Test fixture routes are not mounted
  in production and remain excluded from Docker.
- Unexpected exceptions return generic 500 with a constant log message, without
  raw exception/payload/header/query data. Validation errors omit submitted input.
  Responses are no-store with nosniff and strict-origin referrer policy. Health
  exposes liveness only; readiness exposes bounded prerequisite status codes,
  never credentials or driver exceptions.
- Keep gateway logs free of Cookie/Set-Cookie/Authorization/CSRF headers and auth
  bodies. No request-body logging was added. Local test fixtures use synthetic
  credentials only; traces are disabled in the security browser configuration.

## Dependency and verification evidence

The existing single requirements/constraints mechanism is retained. jose, ecdsa,
rsa and pyasn1 are absent from the fresh graph. PyJWT is pinned; all other locked
versions are unchanged. cryptography 50.0.0 remains available for the asymmetric
rejection regression; no additional crypto upgrade. See the
[PyJWT maintained release](https://pypi.org/project/PyJWT/) and
[validation options](https://pyjwt.readthedocs.io/en/stable/usage.html).

Fresh Windows Python environment: 63 packages, exact lock match, pip check passed;
installed-graph audit **zero known Python vulnerabilities**. Final audit and
checkpoint results follow. npm's one deferred development-only
Tailwind/parser advisory remains as [documented in Stage 1](security-stage1-npm.md);
no frontend dependency update was made.

| Check | Actual result |
| --- | --- |
| Final Python audit / resolution | Zero known vulnerabilities, exit 0; pip check passed; all 63 installed packages exactly match active constraints. jose/ecdsa/rsa/pyasn1 absent. No ignored advisories. |
| Final npm audits | Production zero (exit 0); full audit three moderate package entries for one development-only advisory (expected exit 1). |
| Focused backend checks | 44 auth/CSRF/JWT/registration checks plus 8 API security checks passed; external HTTP blocked. |
| One full backend checkpoint | **1,135 run: 1,133 passed, 2 skipped**, zero failures/errors; 188.595 seconds. 282 discovered PostgreSQL scenarios, including ownership, bootstrap/repeated migrations, health/readiness. Skips require an actual-statistics artifact. Zero external HTTP attempts and zero out-of-scope PostgreSQL connections. |
| Frontend Node tests | 121 passed; five focused auth checks passed after the recovery/cache refinements. |
| TypeScript / production build | Both passed after final source changes, built against the isolated API on port 8199. API origin is build-time configuration; build separately for the deployment origin. |
| Existing offline browser regression | Initial 44/45; found and fixed slip retry unnecessarily rechecking unavailable identity despite an authenticated session. Corrected case rerun passed on final build. Not claimed as an uninterrupted 45/45 run. |
| Actual API/PostgreSQL Chrome checks | **2/2 passed**, desktop 1440x900 and touch/mobile 390x844, 25.4 seconds: real registration, UI login/logout, cookie refresh/expiry, no JS/storage JWT, CSRF rejection, profile mutation rejection, bookmarks/exact save, slip add/edit/persistence and cross-account edit/delete/copy denial. No mocked app API responses. |
| Browser test repair | First real-browser attempt reached login but failed its observer reading the response body after full-page navigation. Repaired observer, restarted on a fresh isolated browser DB and reran successfully; no application change for that failure. |
| Independent review | No actionable defects in session/CSRF/JWT, middleware/configuration or frontend auth integration. |
| Final Git checks | HEAD unchanged; index empty; diff whitespace passed (line-ending warnings only). Five untouched protected files match starting hashes; original certifi requirement retained. |

All state-changing checks used PostgreSQL 15 in a task-labeled disposable container
on a random loopback port with tmpfs, resource limits and no development mounts.
Separate explicit `proppulse_test_` databases isolated browser fixtures from suite
schemas. No leftover suite schemas; both browser servers stopped and owned
container removed after ownership verification. Browser HTTP guard recorded zero
provider/external attempts. A failed automatic approval-review invocation during
wrap-up did not execute its command; it was successfully retried after continuation.

Not run: public HTTPS/SameSite=None browser behavior, Firefox/WebKit, a configured
live gateway/fleet-wide load test, full new Linux image/native/OS audit, retained
development-data walkthrough, provider checks, or the unrelated full browser suite.
No public deployment or development migration was attempted. The release rehearsal
consumer was updated for cookie login but its infrastructure rehearsal was not run.

**Stage 2 is ready for a scoped local commit.** Public deployment remains blocked
on the actual gateway/TLS/target-platform and operations controls above. No Stage 3
work was started.

## Git preservation and limits

Starting complete diff, six protected-file copies and SHA-256 manifest are private
under ignored `backend/data/odds_runs/security-stage2/baseline/`. certifi's
pre-existing requirements addition is preserved while JWT requirements change.
The other five protected files remain untouched. The authorized commit checkpoint
includes only the 49 reviewed Stage 2 files/hunks. The pre-existing certifi addition
remains unstaged; the lock retains its reviewed resolved version. No push or deployment
is authorized.

Remaining release requirements: actual gateway/TLS/proxy configuration and tests,
production secret/DB roles, target image/native/OS audit and deployment operations.
HttpOnly reduces JWT theft through JavaScript but does not prevent XSS from issuing
authenticated actions. There is no claim of public deployment readiness, server
revocation, multi-instance built-in rate coordination, or current provider coverage.

## Stage 2 file inventory

Shared `backend/requirements.txt` also retains the unrelated starting certifi addition. Excluded protected paths: `backend/scripts/fetch_odds.py`, `backend/tests/test_milestone2_ingestion.py`, `frontend/.node-version`, `docs/milestone-4a4-espn-collection-plan.md`, and `docs/phase-5a-simplification-audit.md`.

- `.env.example`
- `README.md`
- `backend/Dockerfile`
- `backend/app/auth.py`
- `backend/app/config.py`
- `backend/app/main.py`
- `backend/app/routers/players.py`
- `backend/app/routers/props.py`
- `backend/app/routers/users.py`
- `backend/app/schemas.py`
- `backend/requirements.lock.txt`
- `backend/requirements.txt`
- `backend/tests/rehearse_release.py`
- `backend/tests/test_dependency_compatibility.py`
- `backend/tests/test_registration_failures.py`
- `backend/tests/test_security_hardening.py`
- `docs/architecture.md`
- `docs/milestone-3h-staging-recovery.md`
- `docs/phase-9-feature-10-readiness.md`
- `docs/security-stage1-dependencies.md`
- `frontend/e2e/data-status.spec.cjs`
- `frontend/e2e/discover-filters.spec.cjs`
- `frontend/e2e/exact-line-research.spec.cjs`
- `frontend/e2e/multi-sport-research.spec.cjs`
- `frontend/e2e/navigation.spec.cjs`
- `frontend/e2e/saved-selections.spec.cjs`
- `frontend/e2e/ui-polish.spec.cjs`
- `frontend/src/app/login/page.tsx`
- `frontend/src/app/page.tsx`
- `frontend/src/app/profile/page.tsx`
- `frontend/src/app/saved/page.tsx`
- `frontend/src/components/AppInit.tsx`
- `frontend/src/components/NavBar.tsx`
- `frontend/src/components/PropCard.tsx`
- `frontend/src/components/SaveExactSelection.tsx`
- `frontend/src/components/SlipDrawer.tsx`
- `frontend/src/lib/api.ts`
- `frontend/tests/saved-selections.test.cjs`
- `frontend/tests/sportsbook-selection.test.cjs`
- `backend/app/services/api_security.py`
- `backend/app/services/session_security.py`
- `backend/tests/security_browser_server.py`
- `backend/tests/test_api_security.py`
- `backend/tests/test_cookie_auth.py`
- `docs/security-stage2-auth-api.md`
- `frontend/e2e-real/auth-security.spec.cjs`
- `frontend/playwright.security.config.cjs`
- `frontend/src/store/auth.ts`
- `frontend/tests/auth-session.test.cjs`
