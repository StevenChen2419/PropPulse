# Milestone 3H gateway and authentication review

Reviewed October 16, 2026 against the actual configuration, auth, schemas,
database/session lifecycle, user/prop/player routers, frontend fetch client, and
Phase 3F integration/security and Phase 3G hardening reports. This supporting
review does not certify a hosting gateway, TLS deployment or distributed limit.

## Focused application fix

Registration first checks the email and then inserts a user. Two concurrent
requests can both pass the lookup; the database unique constraint remains the
authority. `users.register` now catches an `IntegrityError` during commit, rolls
back explicitly, and returns HTTP 400 with `Unable to register account`.
It neither interpolates SQL/driver details nor mints a token after failed commit.
It does not interpret every integrity failure as a duplicate email. Successful
registration still returns a bearer token; the existing duplicate lookup still
returns `Email already registered`. The response contract is preserved.

Three isolated-router tests cover the commit race/error path, duplicate precheck
without writes and successful token issuance. Sessions are mocks, the production
lifespan is not invoked, and no application database is opened. The production
lifespan and real PostgreSQL restore checks belong to the main 3H rehearsal.

## Required hosting controls

These controls need a trusted gateway/shared enforcement layer and an operational
owner. Redis is configured but no distributed application limiter exists. Do not
expose Uvicorn directly or add a per-worker dictionary limiter as a substitute.

| Surface | Release requirement | Suggested initial acceptance check |
| --- | --- | --- |
| Login and registration | Shared per-client and aggregate request/burst limits; login account-key controls resistant to account-lockout abuse; progressive challenges/abuse monitoring; stricter registration quota | Across two workers, repeated attempts reach a bounded 429 with Retry-After; valid traffic recovers after the window; origin/IP spoofing cannot bypass it |
| Research APIs | Route-specific rate and in-flight limits for Discover, Feed, Upcoming Games, ingestion status and player research; bound the aggregate upstream worker queue | Exercise concurrent synthetic inventory traffic; demonstrate bounded queue, memory and latency with overload rejection rather than worker exhaustion |
| Requests | Enforce decoded body/header/URI size, connection count, slow-body/header deadlines, idle time and request deadlines at the edge | Reject oversized bodies for both Content-Length and streamed/chunked transfer; prevent slow uploads from occupying all workers |
| TLS/proxy trust | Public HTTPS, verified certificates, explicit allowed hosts, HTTP redirect, HSTS after TLS validation; strip untrusted forwarded headers and trust only gateway addresses | Forged X-Forwarded-For/Proto/Host cannot affect abuse identity, canonical host or redirect/security decisions; direct backend ingress is blocked |
| Logging | Redact Authorization, passwords, tokens, cookies and database/provider secrets in gateway, app and error collection; restrict log access/retention | Synthetic secret markers do not appear in request/error/access logs; retain request ID, route template, status, duration and safe error class |
| Timeouts and errors | Explicit upstream/connect/response limits; PostgreSQL connect/pool/query bounds for research, cancellation and consistent safe 5xx/429 responses | An unavailable database and a deliberately slow query do not leak diagnostics or hold workers indefinitely; errors preserve CORS for allowed clients |

An initial endpoint-specific authentication JSON body cap of 16 KiB is sufficient
for the current small auth contract; validate it with clients before adoption.
Choose research/body/rate/deadline numbers from representative staging load and
the bounded-inventory targets, rather than treating these examples as deployed
configuration. Page limits currently bound response pagination, not all ranking
or history work. Event-specific Feed intentionally returns all matching props.

The app enforces exact configured CORS origins, generic failed-login messages,
bcrypt verification for unknown emails, bounded new-password UTF-8 length,
HS256 signatures with required expiry/UUID subject, and current-user ownership.
Validation errors omit submitted input/context. Debug is disabled. These are
application protections, not distributed abuse controls. CORS does not restrict
non-browser clients. FastAPI OpenAPI/docs routes remain exposed by default;
decide whether gateway policy restricts them and `/ready` outside trusted probes.

Readiness sets transaction-local statement (2s) and lock (1s) timeouts. Database
connections have a 3s connect bound and 5s pool acquisition bound. The research
session does not install the readiness statement limit, and the frontend's shared
fetch wrapper does not apply a default request deadline. A proxy timeout alone
does not prove cancellation of synchronous database work. Test worker and query
timeouts together with connection recovery before public release.

## Registration and session decisions still open

Public registration reveals membership through success versus duplicate failure,
including HTTP status and automatic token issuance. Merely replacing the error
text would not remove enumeration. A separate product/security decision must
choose restricted registration/invitations or a verification flow with a uniform
accepted response and no account token until verified. No email infrastructure,
new response contract or artificial delay is introduced here. The commit-race fix
does not resolve enumeration or registration abuse.

JWT lifetime defaults to 10,080 minutes (seven days); set an explicitly reviewed
shorter staging/production lifetime (the prior example uses 60 minutes). Tokens
are held in browser localStorage. Existing token rotation invalidates sessions;
there is no refresh/revocation store, multi-key rotation grace period or verified
email workflow. Review CSP/XSS protection, token lifetime, reauthentication and
incident invalidation with the chosen deployment. Backups preserving bcrypt
hashes and a stable signing key preserve compatibility; backups and JWT secret
storage must have independent access controls. Do not place secrets in frontend
public build variables or log request bodies to diagnose authentication failures.

## Executed verification

- `backend/venv/Scripts/python.exe tests/run_no_provider_http.py test_registration_failures.py`:
  3 passed, zero external HTTP attempts; 0.040 seconds.
- `backend/venv/Scripts/python.exe tests/run_no_provider_http.py test_security_hardening.py`:
  18 passed, zero external HTTP attempts; 0.624 seconds.

No gateway/WAF, TLS termination, distributed limit, real registration race,
concurrent load or external identity/email service was exercised by these focused
tests. Those remain release acceptance work; the main rehearsal records actual
startup, database preservation and broader regressions separately.

The final checkpoint reran the full blocked-HTTP suite with disposable PostgreSQL:
537 tests passed, including these three registration regressions and five added
rehearsal target/process guard regressions in the same test file. The combined
eight focused cases also passed separately (0.049s), with zero external HTTP
attempts. These additions do not claim a real concurrent registration race test.
