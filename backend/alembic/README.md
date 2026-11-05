# Versioned database migrations

Current head is `20261022_05` (exact saved selections and original observations).
Readiness expects this revision. Feature 10 fixes fresh bootstrap adoption of
already-present selection columns; existing values are never backfilled or reset.
Revision 05 accepts compatible nullable columns and refuses incompatible shapes.
No development migration was executed by Feature 10.

The chain includes offer provenance (01), authoritative Events (02), append-only
NBA evidence (03), NBA.com namespace (04), and saved-selection evidence (05).
See the [architecture](../../docs/architecture.md) and
[deployment update](../../docs/milestone-3h-staging-recovery.md#current-deployment-guide).
Application startup never runs migrations or create_all. A fresh empty database
is bootstrapped by the initial migration, then each reviewed revision is applied.

Existing databases require explicit migration approval, stopped writers and a
verified backup. Do not use `stamp head` to bypass prerequisites. The commands
below are operator instructions, not authorization to migrate development.
Revision 05 downgrade deletes exact saved selections; do not use it as a routine
rollback. Prefer a compatible code rollback or an explicitly reviewed restore.

## Revision 20261014_01: offer provenance

This is the initial adoption of Alembic for the existing `create_all` schema.
It adds nullable `provider_bookmaker_key`, `provider_title`,
`provider_observed_at`, and `ingested_at` columns to `prop_books`. It introduces
no uniqueness constraints and does not delete or relabel offers or selections.
`updated_at` remains unchanged. Its legacy local ingestion value is copied to
`ingested_at` only when the latter is NULL. No legacy provider observation or
bookmaker identity is guessed. All timestamps retain the application's naive
UTC storage convention.

Stop refresh workers/manual ingestion, take a database backup, review the target
database configured by `DATABASE_URL`, and run explicitly from `backend`:

```powershell
.\venv\Scripts\python.exe -m alembic -c alembic.ini current
.\venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head
.\venv\Scripts\python.exe -m alembic -c alembic.ini current
```

These commands are operator instructions, not verification commands to run against
the user's current database. The migration does not launch FastAPI or providers.
Do not use `stamp head` as a substitute for upgrading an existing database.
On a completely empty PostgreSQL database, this first revision bootstraps the
current application's complete metadata before recording its version. This
one-time legacy adoption depends on current models; future schema changes must
have their own versioned revisions. A nonempty database missing `prop_books`
is refused for manual inspection. Earlier missing legacy columns or malformed
data require inspection/remediation; this revision does not repair or delete them.

The migration inspects existing columns so it also accepts databases on which
`create_all` already created the new schema. Schema introspection requires an
online connection; `--sql` is refused explicitly. A successful repeated
`upgrade head` does nothing. PostgreSQL DDL runs within Alembic's transaction.
Do not run migrations concurrently with ingestion.

For rollback, revert application code and leave the additive nullable columns
and version marker in place. Automatic `downgrade` deliberately refuses to drop
provenance or application tables. A physical schema rollback requires a reviewed
backup/restoration plan. Restoring a backup can lose post-backup data, so it is
not an automatic rollback action.

Migration unit tests use isolated in-memory SQLite tables. Real PostgreSQL 15.18
verification has also passed: fresh initialization, legacy adoption/preservation,
model consistency, transactions, isolated API compatibility and process locking.
See [the PostgreSQL verification report](../../docs/milestone-2-postgresql-verification.md)
for the environment, exact results and development backup/migration procedure.
Optional PostgreSQL tests require an explicit disposable PROPPULSE_TEST_POSTGRES_URL;
they must never target the normal application database.
