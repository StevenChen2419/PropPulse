# PropPulse

PropPulse is a multi-sport player research workspace for **NBA, WNBA, NFL, NHL and MLB**. It connects recorded player performance with exact sportsbook lines so a researcher can inspect the evidence behind a selection, compare equivalent prices, and keep a personal research library and draft slip.

This portfolio project demonstrates full-stack engineering with real, imperfect sports data. It is a research tool; it does not place bets or provide validated win probabilities. Supported sports do not imply complete or current provider coverage.

## Explore the application

- **Discover:** server-side player/team search, sport/market/book/side filters, sorting and pagination with shareable URL state.
- **Player Research:** sport-specific recorded L5/L10 summaries, season selection, exact-line hit rates, charts and source coverage, including research without a current offer.
- **Sportsbook comparison:** Over/Under prices grouped by the same player, market, event and line. Alternative lines remain separate.
- **Saved Props:** generic bookmarks and exact sportsbook/line/side selections with original price observations.
- **Research slips:** edit selections in place, preserve unavailable picks, reload persisted choices, and view explicitly experimental payout/correlation estimates.
- **Account preferences and My Players:** authenticated preferences, saved research and followed players. Public research can be browsed without signing in.
- **Responsive workspace:** desktop and mobile navigation, charts, accessible form labels, keyboard focus and recoverable loading/error states.

## Engineering highlights

Multi-source ingestion normalizes provider identities, competitions, game dates and sport-specific metrics into PostgreSQL relational models. Reviewed player mappings and event identity checks prevent ambiguous matches. Transactional imports, idempotency guards and Alembic migrations protect historical records and user selections. Refresh tools enforce bounded requests, quota reserves and explicit execution scopes.

Odds freshness is enforced on the server using provider observation time, never a newly generated response timestamp. Exact-line research retains pushes and valid sample denominators rather than presenting missing games as losses. Server-side search and pagination use retained eligible inventory. Automated backend, frontend and browser tests cover identity, freshness, ingestion failures, authorization and persistence.

The workload indices and Discover rankings are heuristics. The experimental NBA XGBoost/SHAP code is a legacy experiment, not a validated prediction product or a required setup step.

## Stack and architecture

| Layer | Implementation |
| --- | --- |
| Frontend | Next.js 15 App Router, React 19, TypeScript, Tailwind CSS, Recharts, Zustand, Lucide |
| API | FastAPI, Pydantic, SQLAlchemy, Python |
| Persistence | PostgreSQL; versioned Alembic migrations |
| Authentication | bcrypt password hashes, expiring HS256 JWTs in HttpOnly cookies with CSRF protection |
| Verification | unittest, isolated SQLite/PostgreSQL fixtures, Node test runner, Playwright |
| Optional infrastructure | Redis is configured but not used by application caching |

Next.js calls FastAPI, which reads PostgreSQL. Separate ingestion commands collect The Odds API sportsbook markets and real statistics from NBA.com, wehoop, nflverse, NHL Web API, MLB StatsAPI and legacy ESPN paths. The API does not fetch provider data on ordinary research requests. See [architecture and data contracts](docs/architecture.md).

## Data reliability and limitations

Prices are current/actionable for 30 minutes after provider observation. From 30 minutes through six hours they are labeled last-known and are not actionable. After six hours, at game start, or without trustworthy observation/identity/price, the offer is unavailable. Stored selections keep their original book, line and side when pricing disappears. Historical snapshots are observations, not verified continuous sportsbook movement.

Known retained-data limitations:

- NBA 2026–27 provider access has not been verified successfully; historical NBA.com records are retained.
- WNBA retained player records end **July 22, 2026**.
- NFL coverage is limited to the retained dataset; missing appearances do not establish DNP or complete weekly coverage.
- MLB legacy exclusions remain, including unreviewed legacy overlaps/season metadata; they are not silently certified as complete current-season statistics.
- The **Liam Hicks identity conflict** remains excluded pending reliable resolution.
- Source completeness is unknown; recorded L5/L10 means recorded appearances, not a certified complete schedule.
- Historical sportsbook movement is unverified. Development sportsbook prices may be expired and must not be described as live.

No benchmarks, active-user counts, model accuracy or public deployment are claimed. See [multi-sport source notes](docs/phase-8-multi-sport.md) and the [bounded unified refresh guide](docs/phase-9-unified-refresh.md). Provider calls/imports require separately approved scopes; they are not part of setup or the demo.

## Local setup (Windows PowerShell)

Prerequisites: Node.js **24.22.1 or later within major 24** (the tested development runtime; this public snapshot does not include a machine-specific Node version pin), Python 3.11 or later with compatible wheels, Docker Desktop, Git. Run from the repository root. Do not overwrite an existing environment file.

```powershell
# New checkout only; these files are ignored.
Copy-Item .env.example backend/.env
Copy-Item .env.example .env
python -m venv backend/venv
backend/venv/Scripts/python.exe -m pip install -r backend/requirements.txt
Push-Location frontend
npm ci
Pop-Location
docker compose up -d db redis
```

The example backend URL uses `localhost:5432/proppulse` for the normal local backend. Compose overrides the backend service's host to `db`. The frontend needs its own public API setting:

```powershell
Set-Content frontend/.env.local 'NEXT_PUBLIC_API_URL=http://localhost:8000'
```

Generate a private signing secret with Python's `secrets.token_urlsafe(48)` and put it in `backend/.env`; never publish it. Keep `LIVE_REFRESH_ENABLED=false` and provider keys empty for retained-data research. Settings read `.env` relative to the backend working directory; root `.env` is for Compose. [Deployment/environment guidance](docs/milestone-3h-staging-recovery.md#current-deployment-guide) lists required and optional settings.

**New, empty local database only:** after deliberately selecting the database, initialize the schema:

```powershell
Push-Location backend
.\venv\Scripts\python.exe -m alembic upgrade head
Pop-Location
```

An existing database requires a reviewed backup and explicit migration approval. Current head is `20261022_05`; startup never migrates or seeds. See [migration instructions](backend/alembic/README.md). An empty checkout contains no private provider dataset or user accounts. Do not run legacy seed/refresh/ML tools to populate the research database.

Start in separate terminals:

```powershell
# Root, if local services are not already running:
docker compose up -d db redis
# Terminal 2:
cd backend
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
# Terminal 3 (from repository root):
cd frontend
npm run dev
```

Open [PropPulse](http://localhost:3000), [API liveness](http://localhost:8000/health), [database readiness](http://localhost:8000/ready) and [API contracts](http://localhost:8000/docs). Health alone does not prove database readiness. Stop app terminals with Ctrl+C; `docker compose down` stops services without removing data volumes.

## Portfolio demonstration

Follow the [3–5 minute demo script and offline replay](docs/portfolio-demo.md). Show retained real statistics read-only, explain unavailable/expired offers, then explicitly switch to **invented offline fixtures** for reproducible available-price, authentication-state and editing scenarios. Fixtures neither call providers nor mutate the development database. No shared demo credentials are advertised. Existing accounts are environment-specific; account creation and persistence demonstrations must use isolated fixtures or an explicitly authorized separate database.

## Verification

Historical milestone reports describe the original private development environment. Provider collections, database backups, local player mappings, approval records, raw security scans and generated screenshots are deliberately excluded from this source snapshot. Paths to those artifacts are provenance notes or input/output examples, not downloadable public fixtures. Reproduce checks with the committed invented fixtures and newly created disposable resources; optional provider workflows require separately prepared, reviewed inputs and credentials.


From `backend`, use the HTTP-blocking runner (no application lifespan):

```powershell
$env:DATABASE_URL='sqlite:///:memory:'
$env:LIVE_REFRESH_ENABLED='false'
.\venv\Scripts\python.exe tests/run_no_provider_http.py
```

PostgreSQL cases require `PROPPULSE_TEST_POSTGRES_URL` pointing to an **isolated** `proppulse_test_...` database; they skip when unset. Never use the application database for tests. From `frontend`:

```powershell
npm test
npx tsc --noEmit
npm run build
npm run test:e2e
npx playwright test --config playwright.mobile.config.cjs
```

Browser suites use mocked HTTP for mutations; retained-data checks are separate. See the [Feature 10 verification report](docs/phase-9-feature-10-readiness.md) for actual results and checks not run. There is no configured lint script/gate. Do not confuse static rendering with browser or real PostgreSQL verification.

## Deployment

Minimum: a maintained Next.js Node service, the reviewed FastAPI container, private PostgreSQL and a trusted HTTPS gateway with shared abuse limits. No hosting platform is selected. Redis and a refresh scheduler are unnecessary for retained-data research; keep refresh disabled. Costs include compute, database/storage/backups, network, domain and monitoring, with provider subscriptions separately authorized. See the [provider-independent deployment guide](docs/milestone-3h-staging-recovery.md#current-deployment-guide) and [Stage 3 release matrix](docs/security-stage3-production-verification.md). Local Linux/HTTPS/recovery checks passed; image findings and hosting/operations gates remain. Public deployment is unapproved.
