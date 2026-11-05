# Milestone 2: PostgreSQL verification

## Environment and isolation

Verified on October 14, 2026 using Docker Engine 29.8.2, the existing cached
postgres:15-alpine image, and PostgreSQL 15.18. Docker Desktop was initially stopped
and was started for this task. No existing containers were running when the engine
became available. Only the disposable test container was started; Compose services,
the backend lifespan, and all provider refresh jobs remained stopped.

Disposable container: `proppulse-test-m2-20261014`.
Disposable database: `proppulse_test_milestone2`.
Host endpoint: loopback `127.0.0.1:57937`, independent of development port 5432.
Storage: tmpfs at /var/lib/postgresql/data; no bind mounts or named volumes.
Authentication is temporary test-only trust; no application credentials are used.
No database URLs or credentials are included in this report.

The normal configured application target was inspected without connecting:
PostgreSQL, localhost:5432, database proppulse; configured refresh is disabled.
Existing Docker volumes proppulse_pgdata and proppulse_redisdata were not mounted
by the test container. No normal DATABASE_URL was supplied to integration tests.
The opt-in PROPPULSE_TEST_POSTGRES_URL was set only in the test-command process.

Tests enforce a PostgreSQL target with database name starting proppulse_test_.
Per-test reconciliation/migration schemas use generated UUID names and a scoped
search_path. Only those test schemas are removed by tests. Worker-process tests
use advisory locks in the same dedicated disposable database and no application data.

## Results

All PostgreSQL checks below were actually executed against PostgreSQL 15.18.

| From backend | Result |
| --- | --- |
| `.\venv\Scripts\python.exe -m unittest discover -s tests -p test_ingestion_postgres.py -v` | 9 passed, 0 skipped, 0 failures/errors |
| `.\venv\Scripts\python.exe -m unittest discover -s tests -p test_ingestion_process_postgres.py -v` | 2 passed, 0 skipped, 0 failures/errors |
| `.\venv\Scripts\python.exe -m unittest discover -s tests` with the explicit test URL | 167 passed, 0 skipped, 0 failures/errors |

The full suite includes all 11 real PostgreSQL tests plus 156 other backend tests.
The first four original optional PostgreSQL tests also passed before expansion.
Compile check from root: `backend\venv\Scripts\python.exe -m compileall -q backend/app backend/scripts backend/tests` passed.
`git -c safe.directory=<repository-root> diff --check` passed.
The test URL was injected through process environment only; no environment file was changed.

Existing datetime/Pydantic deprecation warnings remain. AnyIO TestClient memory-stream
ResourceWarnings appeared despite context-managed clients; all assertions passed.
No dependency upgrade or warning suppression was performed. Frontend/browser checks
were not rerun for this backend-verification-only change.

## Migration and data-preservation findings

- Fresh Alembic upgrade created all model tables and revision 20261014_01 on an empty
  isolated schema. Alembic compare_metadata with compare_type=True found zero diffs.
- A full representative legacy schema was copied from the checkpoint-compatible model
  metadata without the four provenance columns, and populated with real PostgreSQL
  UUID/foreign-key fixture relationships. Upgrade head successfully adopted the
  unversioned schema, and a repeated head upgrade was a no-op.
- Both new String columns and both DateTime columns were nullable. Offers retained
  IDs, lines, side prices and updated_at. Only ingested_at received the legacy local
  write timestamp; provider observation, provider key and provider title stayed null.
- Snapshots, players, users, saved props, slips and exact side/book/line choices were
  preserved. Legacy observations remained unavailable to research and payouts while
  saved and slip selections stayed accessible.
- Snapshot capture timestamps were not repurposed as provider observations.

No migration/runtime code changes were required by PostgreSQL execution. The initial
Alembic adoption is intended for a complete checkpoint-compatible schema. It does
not repair arbitrary older partial schemas: a nonempty schema without prop_books
is refused; missing unrelated legacy columns/tables are outside this additive
revision. Fresh bootstrap depends on current metadata, so future schema changes
must use new revisions. Never stamp an existing database to skip these additions.
The actual development schema has not been inspected through a database connection
or upgraded, so fixture success is not a claim that every possible local schema is identical.

## Transactions, process coordination, and application compatibility

Actual PostgreSQL flushing followed by rollback preserved previous offer/prop values,
snapshots and user choices. An injected real unique-constraint failure during one
sport commit aborted that transaction, reported IntegrityError with zero committed
write counts, and did not prevent the next sport from committing. Repeated
reconciliation produced one current offer and no duplicate unchanged snapshots.

Advisory-lock tests used separate PostgreSQL connections and separate Python worker
processes. A second connection/process could not acquire the shared dataset lock
while owned, including across unrelated commits. Locks became available after normal
exit, raised exceptions, and forced process termination. This verifies the shared
primitive; no live automatic-refresh scheduler/provider subprocess was launched.

Isolated FastAPI apps used real PostgreSQL fixture sessions and dependency overrides,
with no production lifespan. Actual Alembic-initialized schemas supported feed and
player research, saved props, exact slip selections, and independent payout estimates.
Expired observations disappeared from actionable research but remained saved/in-slip;
payouts became unavailable without changing selections. No historical results were fabricated.

Before container cleanup, direct checks found zero test schemas and zero advisory
locks remaining in the disposable database. The exact disposable container was then removed; its tmpfs database was discarded.
Both original named volumes remained present, and no application container was started.
Docker Desktop was stopped afterward, restoring its initial stopped state.

## Changes made during verification

- Expanded `backend/tests/test_ingestion_postgres.py` from four to nine tests.
- Added `backend/tests/test_ingestion_process_postgres.py` with two process tests.
- Added this report and linked it from the implementation report and migration README.
- No production implementation, migration revision, Compose, environment file, or
  dependency changes were needed. Existing uncommitted Milestone 2 work was preserved.

## Remaining risks and readiness

Milestone 2 is ready for a reviewed Git commit and a backed-up, explicitly authorized
development migration, assuming the existing schema matches the supported legacy
baseline. Neither operation was performed. Existing database contents, named Docker
volumes, environment files, and sportsbook history were left untouched.

Browser E2E, live-provider behavior, complete scheduler orchestration, unusual older
schema remediation and a development-backup restore drill remain outside this check.
Omitted provider markets still cannot prove withdrawal; legacy offers without actual
provider observations remain unavailable after migration. These are documented
behavior/coverage limitations, not PostgreSQL test failures.

## Recommended development backup and migration procedure (not executed)

The following is a future operator procedure. It is not authorization to migrate.
First stop local Uvicorn, optional backend containers, background refresh workers,
and any manual ingestion processes. Keep the database running for backup. Do not
run a provider refresh as a migration check. Preserve existing environment files.

From the repository root, create a unique binary-safe backup outside Git:

```powershell
$backupName = 'proppulse-before-m2-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.dump'
$backupDirectory = Join-Path $env:USERPROFILE 'Documents\PropPulseBackups'
New-Item -ItemType Directory -Path $backupDirectory -Force | Out-Null
$remoteBackup = '/tmp/' + $backupName
$localBackup = Join-Path $backupDirectory $backupName

docker compose exec -T db sh -c 'pg_dump --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --format=custom --file="$1"' sh $remoteBackup
if ($LASTEXITCODE -ne 0) { throw 'Backup failed; do not migrate.' }
docker compose exec -T db pg_restore --list $remoteBackup | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Backup archive validation failed; do not migrate.' }
docker compose cp "db:$remoteBackup" $localBackup
if ($LASTEXITCODE -ne 0 -or !(Test-Path -LiteralPath $localBackup)) { throw 'Backup copy failed; do not migrate.' }
if ((Get-Item -LiteralPath $localBackup).Length -eq 0) { throw 'Backup is empty; do not migrate.' }
Get-FileHash -LiteralPath $localBackup -Algorithm SHA256
```

This uses the database container's existing environment without displaying credentials.
It avoids redirecting a binary pg_dump stream through Windows PowerShell. Retain the
backup outside the repository. Backup archive readability is not a full restore drill;
a rehearsal restore should target another disposable database, never the application.

After explicit user authorization, verify the private backend settings select the
intended existing development target, then from backend run:

```powershell
.\venv\Scripts\python.exe -m alembic -c alembic.ini current
if ($LASTEXITCODE -ne 0) { throw 'Revision inspection failed.' }
.\venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head
if ($LASTEXITCODE -ne 0) { throw 'Migration failed; inspect before restarting.' }
.\venv\Scripts\python.exe -m alembic -c alembic.ini current
if ($LASTEXITCODE -ne 0) { throw 'Revision verification failed.' }
.\venv\Scripts\python.exe -m alembic -c alembic.ini check
if ($LASTEXITCODE -ne 0) { throw 'Schema drift detected; inspect before restarting.' }
```

Expected head is 20261014_01. An unversioned legacy database initially reports no
revision; use upgrade head directly, not stamp head. No provider observations are
backfilled. Existing rows without provider observations remain stored but unavailable
until an explicitly authorized provider refresh supplies trustworthy observations.

Application rollback retains additive nullable columns and their data. Automatic
Alembic downgrade deliberately refuses destructive column removal. Do not restore
the backup over newer application data without a separate reviewed restoration plan.
