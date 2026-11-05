# PropPulse Agent Instructions

## Fast Development Mode

Prioritize working user-facing functionality quickly while following the safety,
security, and data-integrity requirements below. The goal is a polished, reliable
portfolio project, not an enterprise sports-data platform.

- Implement the smallest maintainable, complete solution for the user-visible goal.
  Reuse existing services, models, importers, statistics calculations, API endpoints,
  and UI components. Avoid unrelated refactoring and unnecessary abstractions.
- Do not introduce frameworks, databases, queues, or evidence systems without a
  concrete need. Favor completing the feature over infrastructure preparation.
- Do not add provider-audit, participation-certification, or historical-reconciliation
  systems unless a concrete feature requires them.
- Run focused tests during implementation. Run full regression tests once at the
  final checkpoint when warranted by the changes.
- Fix confirmed defects within the active task. Implement and verify normal code
  changes in one task, without separate review-only or commit-only milestones.
- Keep milestone documentation concise: changes, tests, limitations, and next steps.
- Do not repeat authorization requests for actions explicitly approved within their
  scope. Never silently expand provider request budgets, database-write scopes, or
  deployment permissions.
- Preserve exact Player/Prop/Event identities, odds correctness, authentication,
  and saved/slip data. Never treat synthetic or incomplete data as verified live
  coverage.
- When explicitly authorized to commit, create one local commit after testing.
  Otherwise leave changes uncommitted; do not automatically push.
- For external provider calls, development database writes, schema migrations, or
  deployment, obtain approval for the exact scope not already authorized.
- Finish with a concise report covering what works, what changed, tests passed,
  and remaining blockers. Identify checks not run and any necessary next steps.

## Scope and Architecture

This directory is the application Git root. Run Git commands here and application
commands in the indicated subdirectory. Applicable parent instructions still apply.
Treat current code and package manifests as the source of truth; parts of README.md
describe legacy demo workflows that conflict with the current live research app.

- Frontend: Next.js App Router, React, TypeScript, Tailwind CSS, Recharts, Zustand,
  and Lucide. Routes are in frontend/src/app, reusable UI in components, API/types
  in lib, and saved/slip state in store.
- Backend: Python FastAPI; routers in backend/app/routers, reusable business logic
  in backend/app/services, SQLAlchemy models in models.py, contracts in schemas.py.
- PostgreSQL stores players, props, current PropBook offers, PropBookSnapshot
  history, PlayerGameLog records, users, interactions, saved props, and slips.
- Redis is configured in settings/Compose but is not integrated into application
  caching. Current odds caching uses database offers and snapshots.
- The Odds API supplies NBA, WNBA, MLB, NFL, and NHL odds. MLB Stats API and ESPN
  supply rosters/history; market and historical coverage vary by sport.
- backend/scripts contains ingestion and additive migration scripts. Alembic is
  installed, but there is no versioned Alembic migration workflow yet. create_all
  creates missing tables; it does not upgrade existing columns.
- backend/ml contains an experimental NBA XGBoost/SHAP demo. Discover and current
  multi-sport workload scores are heuristics, not validated betting probabilities.

## Engineering and Data Integrity

- Inspect relevant implementations and callers before editing. Preserve existing
  architecture and favor small, incremental changes with explicit justification
  for schema changes, dependencies, or broader refactors.
- Put shared business logic in reusable services rather than duplicating it across
  routers. Keep API response contracts, backend schemas, frontend types, and callers
  aligned, including null prices and unavailable-data states.
- Preserve prop IDs, historical records, saved props, watchlists, and slip choices.
  An unavailable price should disable an action, not erase a user's selection or
  silently replace its sportsbook, line, or side.
- Never fabricate sportsbook-backed props, offers, prices, or historical results.
  Missing provider coverage must remain unavailable. Research surfaces must exclude
  synthetic rows and expired offers.
- Compare best Over/Under prices only for equivalent player/market/event and the
  same betting line. Different lines may be shown separately, never ranked as an
  equivalent best-price comparison.
- Respect the current freshness policy: live through 30 minutes, last-known until
  the six-hour TTL, and no actionable offers once the game starts. Distinguish
  provider observation, ingestion time, and response time; use consistent UTC
  storage/serialization and Eastern time for user-facing game times.
- Use explicit transaction boundaries and idempotent ingestion. Preserve valid
  offers on failed/incomplete refreshes and scope stale cleanup to trustworthy
  provider coverage. Do not assume HTTP 200 means every market was returned.
- Keep frontend/src/app/layout.tsx a server component; do not add "use client".
  Preserve saved/slip hydration and persistence when changing frontend workflows.

## Safety

- Never print, commit, or embed credentials or .env contents. Keep generated status,
  logs, and model artifacts out of Git according to .gitignore.
- Tests must not call paid APIs or real sports providers. Mock provider clients and
  use isolated database fixtures; never point tests at the user's application data.
- Seed, migration, ingestion, demo refresh, and ML training scripts are not routine
  verification commands. Review their effects before running them. Destructive DB
  commands, reseeding, resets, or volume deletion require explicit user approval.
- Do not run seed.py, refresh_demo_data.py, or update_line_movement.py against
  provider-backed data. Legacy tools can delete data or synthesize real rows' lines
  and game timestamps. Use a separate demo database if explicitly requested.
- Backend startup calls create_all and can launch paid provider refresh subprocesses
  when LIVE_REFRESH_ENABLED is true. For tests or read-only checks, avoid the real
  application lifespan; inspect settings before starting services. The code defaults
  refresh off, but .env.example enables it.
- Do not change production configuration without an explicit justification tied to
  the task. Do not deploy, purchase API credits, or upgrade provider plans implicitly.

## Development and Verification

Use Windows PowerShell and the existing project environment. The normal local setup
runs only PostgreSQL/Redis through Docker, the backend locally with Uvicorn, and the
frontend with npm run dev. Compose also defines an optional backend container.

| Working directory | Command | Purpose |
| --- | --- | --- |
| Repository root | docker compose up -d db redis | Start local services when needed |
| backend | .\venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000 | Start backend after checking refresh settings |
| frontend | npm run dev | Start frontend |
| backend | .\venv\Scripts\python.exe -m unittest discover -s tests | Backend test suite |
| backend | .\venv\Scripts\python.exe -m unittest discover -s tests -p test_trend_service.py | Example focused backend checks |
| frontend | npm test | Node test runner tests in tests/*.test.cjs |
| frontend | npx tsc --noEmit | TypeScript checks |
| frontend | npm run build | Production build check when relevant |

Existing backend tests use unittest, provider/session mocks, isolated FastAPI apps,
and some in-memory SQLite fixtures. Frontend tests use Node's test runner with
TypeScript transpilation, mocked requests, and static React rendering. There is no
checked-in browser E2E suite or CI workflow. npm run lint exists, but no ESLint
configuration was found; report configuration/tool failures rather than claiming
lint passed. Builds and type checks can create generated artifacts.

- Add focused regression tests for bug fixes, especially odds freshness, equivalent
  lines, ingestion failure/cleanup, analytics denominators, and user persistence.
- Run focused checks first, then relevant suites/type/build checks for the affected
  surface. Verify related workflows; static rendering alone does not verify browser
  interactions or real PostgreSQL transaction behavior.
- Preserve existing uncommitted work and keep unrelated files untouched. Explain
  significant implementation decisions and coordinate bounded file ownership when
  parallel work is useful, following parent guidance.
- Finish with changed files, verification results, outstanding risks, and follow-up
  work. State which checks were not run and why. Never claim checks passed without
  a successful execution. Do not automatically commit or push changes.
