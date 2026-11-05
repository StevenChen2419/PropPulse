# Phase 3C: Bounded verified Event linkage

Implemented from clean HEAD `af5d2365e0df5d2bff9d7d696962482b975cbf5f`.
Authorization covers implementation and isolated testing only. **No development
execution, Event creation or prop linkage is authorized by this document.**
Parent/application AGENTS and Phase 3A matching/history/PostgreSQL, Phase 3B Event
schema, Phase 3C ingestion and retained preflight documentation were reviewed.

## Exact scope and pinned evidence

This is a separate operational tool, not an ingestion or generic backfill path.
The only supported provider identity is `the_odds_api / basketball_nba /
26b036ff107f3c658258eaf4a6f26228`: Boston Celtics away at Detroit Pistons home,
October 20, 2026 at exactly 19:00 UTC. Participants and schedules cannot change.
The ten explicit UUIDs are frozen in `verified_linkage_scope.PROP_IDS`. Missing,
extra, substituted or duplicate manifest UUIDs reject the entire operation. No
database query can expand this allowlist. Related identity rows are read only
to detect unexpected scope expansion and cause rejection.

Pinned inputs, relative to backend:

- `data/odds_runs/verification/phase3c-preflight-6fd947b2291442b8a5ab93647a716179/phase3c-proposed-links.json`
  — file SHA-256 `ac101a3d765a982b84d59d08f8cd6de5dcd2fbd8e3fea79684d4adf1f6eac461`.
- `data/odds_runs/<private-run-id>.json`
  — file SHA-256 `b3be5e25a0322f86414c8ed45ed87170dd997e31707d9d698c207316401882f1`.

The loader has no path/hash override arguments. It bounds each file to 1 MB,
checks exact bytes before parsing, rejects duplicate JSON keys, malformed UTF-8,
nonfinite numbers and unexpected document shapes, and checks canonical manifest
and evidence digests. Event metadata passes retained-report and Event validation.
Candidate stored fields, player fingerprints, participant sides, exact UTC time,
sport/provider IDs, null original Event references, and evidence provenance must
agree. Player.team is a change fingerprint, never authoritative event evidence.
The pinned files are reread before connecting, under the shared lock, and again
immediately before committing. They are never regenerated or modified by this tool.

The retained report is historically partial and points-only: one processed Event,
two updated props and four saved offers, with three unmatched outcomes. Its Event
metadata supports these ten candidate relationships under the existing policy;
it does not independently verify all ten markets' odds or present-day coverage.
Hashes establish integrity, not arbitrary report authenticity.

## Interface and authorization boundary

From backend, the default interface is:

```powershell
.\venv\Scripts\python.exe scripts/link_verified_event.py `
  --report data/odds_runs/verification/<protected-new-directory>/dry-run.json
```

The input paths/event/prop set are fixed. There are no `--manifest`, `--event-id`,
`--database-url`, bulk-selection or schedule-correction options. `--report` must
be a new JSON file within the existing gitignored verification subtree and is
exclusive-created before database work. Protect the directory's Windows ACL
before use; POSIX creation requests owner-only permissions. Do not reuse any
previous report/manifest filename. The tool updates only the report it reserved.

Future write interface, **not run against development in this implementation**:

```powershell
# Only after separate explicit operational authorization and reviewed dry-run.
.\venv\Scripts\python.exe scripts/link_verified_event.py `
  --execute --approve LINK-VERIFIED-CELTICS-PISTONS-10 `
  --report data/odds_runs/verification/<protected-new-directory>/execution.json
```

Both execution flag and exact approval phrase are required. The phrase is a
deliberate operator confirmation, not cryptographic proof of approval. A valid
manifest, this implementation authorization, or this example never authorizes a
development write. Development environment and disabled automatic refresh are
required both by the CLI and production service entry point.

## Target and schema checks

The CLI accepts only the configured PostgreSQL localhost:5432/proppulse URL.
All URL query parameters reject, preventing libpq host/dbname overrides. Before
any writable transaction, a READ ONLY connection checks live driver DSN database,
host, port and any hostaddr, plus actual current_database(), server port, public
schema, PostgreSQL 15.18 and revision 20261014_02. A nonloopback hostaddr rejects.
Docker's server-side address can be private; it is not mistaken for the client
connection's localhost endpoint.

The complete current table/model schema, Event constraints, prop foreign key,
and enabled known-link trigger must be compatible. No tables or revisions are
created, repaired, stamped or upgraded by the operational tool. Tests install
the existing migration/trigger only in their isolated fixture schemas.

`run_isolated_linkage` is a separate test entry point, not a CLI mode. Before
connecting it requires an exact match to explicit PROPPULSE_TEST_POSTGRES_URL,
a `proppulse_test_` database and, after connection, an isolated test schema. The
production entry point has no test-mode override argument. Tests cannot use the
development name or public application schema through the isolated entry point.

## Dry-run, transactions and locking

Every preview connection, including the advisory-lock session, is read-only.
The CLI sets default_transaction_read_only=on before the first driver query;
service transactions explicitly use REPEATABLE READ, READ ONLY. Preview performs
no INSERT/UPDATE/DELETE, FOR UPDATE, or table write locks. It validates current
records and reports planned actions, then rolls back its read-only transaction.

Both modes take the existing dataset lock 734901227 using the shared
`odds_ingestion_lock` helper. Acquisition is one nonblocking attempt: contention
rejects without writes. The dedicated session remains pinned across the data
transaction, commit, and post-commit checks. Finally blocks release it on success,
exceptions and KeyboardInterrupt; abrupt process death closes the session and
PostgreSQL releases the lock, as covered by existing process-lock tests.

Only explicit write mode sets READ WRITE. It acquires SHARE ROW EXCLUSIVE locks
on the preflight-validated application tables and revision table **before any
SELECT establishes its repeatable-read snapshot**. This prevents ingestion and
other application DML from racing the preservation baseline or in-transaction
checks. Table locks use a three-second timeout; statements use thirty seconds;
idle transactions use sixty seconds. This deliberately requires a quiet
maintenance window and can briefly block other writers.

Under those locks the tool rechecks target/schema, both pinned files, exactly ten
candidate rows, their players and expected stored values, related identity scope,
Event inventory and existing links. Any discrepancy aborts all work. The only DML
is one new validated Event insert if needed, and initial `props.event_id` updates
through the guarded helper for the allowlisted records. New Event plus all links
commit together. No upsert path capable of schedule correction is used.

## Existing state and idempotency

Without `--expected-existing-event-id`, require zero Events and zero linked props.
An existing Event is never silently adopted. An explicitly reviewed existing UUID
may be supplied with that option in either mode. It requires exactly one Event,
that exact UUID and metadata, and either all ten props unlinked or all ten linked
correctly to it. Partial, conflicting, unrelated or additional Event/link states
reject and require new review. No known link is reassigned or cleared.

An approved all-correct repeat performs zero writes: it reuses the Event and ten
relationships without altering Event.updated_at. Reusing an explicitly reviewed
but unlinked correct Event creates only the ten FK references. The original
immutable manifest remains unchanged; only its historical null-FK expectation is
normalized for the separately validated approved existing state. All other
manifest expected values must still agree exactly.

## Preservation, reports and recovery

Before and after fingerprints include ordered full-row SHA-256 and counts for
every application table plus alembic_version. A second complete props projection
excludes only event_id. All unrelated table fingerprints must match; all original
prop columns/counts must match. Existing Events must remain byte-for-byte equal.
After mutations, exact Event metadata, UUID and ten-link set are revalidated
before commit. A new READ ONLY transaction verifies the committed state and full
fingerprints afterward. After releasing the shared lock, the report checks the
remaining database advisory-lock count.

No legacy prop columns, prices, offer observation/ingestion timestamps, snapshots,
player/history/user/saved/slip/fatigue records, schedules, participants or selections
may change. No deletes, merges, provider calls, history refresh or migrations occur.

Reports contain pinned paths/digests, sanitized target/revision, Event UUID/action,
exact candidate IDs, reused links, write_attempts, attempted prepared results,
committed results, before/after/post-commit counts/hashes, reason codes, transaction
outcome, post-commit verification, and lock-release/count information. They never
contain credentials, raw provider payloads or raw user rows. Fixed scope errors
have reason codes; unexpected driver errors expose only their class.

`write_attempts` counts mutation attempts, including one that fails before flush;
`attempted` counts successfully prepared/flushed changes. `committed` is populated
only after commit acknowledgement. Before-commit errors roll back all changes.
A lost commit acknowledgement yields `commit_unknown`, `requires_review`, and
`committed=null`; a test proves the server may already have committed. A
post-commit verification failure retains committed counts and reports failure.
Neither condition authorizes automatic retry or reversing known links.

A reserved report left at `started/not_yet_reported` after a crash also means
unknown outcome. If final report persistence fails, console diagnostics retain
known transaction outcome/counts. Preserve the report and perform separate
read-only verification. Do not clear links, delete the Event, blindly rerun, or
restore a backup automatically. Recovery needs a separately reviewed operation.
Table locks end at commit; a concurrent writer after commit can cause the fresh
verification to fail. Keep writers stopped until the operational report is reviewed.

## Isolated verification and implementation safety

Disposable container `proppulse-test-bounded-linkage-20261015`, PostgreSQL 15.18,
loopback port 49290, database `proppulse_test_bounded_linkage`, temporary test trust,
tmpfs-only storage, and no volume/bind mounts were used. Every test owns a random
schema behind the existing disposable-name guards. No production CLI execution
or development connection occurred. The exact real pinned files passed offline
validation without creating a database engine or invoking the executor.

Tests cover fixed ten-prop scope, altered/missing/duplicate inputs, evidence
changes, target/query/DSN and revision rejection, missing/changed candidate/player
values, unexpected related rows, existing Event conflicts, explicit UUID reuse,
advisory contention, atomic success, failure after three links, interruption,
write-lock/snapshot ordering, real FK/trigger protection, full preservation,
read-only dry-run, commit uncertainty and post-commit failure. CLI tests mock all
engines/executor calls, including deliberate flag dispatch; they never connect
to development. Synthetic reviewed inputs are injected only by unittest mocks;
the production loader has no override interface.

Independent review found and verified fixes for URL target overrides and snapshot
ordering before table locks. Final regression results:

| Check | Result |
| --- | --- |
| Full backend discovery, external HTTP transports blocked | **399 passed, 0 failures/errors/skips**, 52.266 seconds |
| Real PostgreSQL tests included above | **81 passed**: 54 existing plus 27 new executor cases |
| New bounded-linkage cases included above | **59 passed**: 18 scope, 9 mocked CLI, 27 PostgreSQL, 5 target guards |
| Offline exact real manifest/evidence loader | Passed, ten candidates; no DB engine/executor invoked |
| External HTTP transport attempts | **0** |
| Python compileall of app/scripts/tests | Passed, exit 0 |
| Git diff whitespace check, plus new-file trailing-whitespace check | Passed |
| Effective automatic refresh | False |

Focused execution first exercised the new PostgreSQL and CLI/scope checks. A test
for lost commit acknowledgement initially patched the raw driver identity rather
than SQLAlchemy's pooled wrapper, so its intended exception was not injected.
The fixture was corrected to compare the wrapped driver; its focused rerun and
the final complete suite passed, including actual server-committed/unknown-client
outcome coverage. No safety assertion was weakened.

Cleanup verified zero leftover test schemas and zero advisory locks, then stopped
and removed only the disposable container. Development PostgreSQL/backend/Redis
remained stopped, and existing volumes/backups were untouched.
Existing datetime/AnyIO warnings are not suppressed.
No frontend/API contract changed, so frontend/build/browser checks are omitted.
No development recount is claimed: development remained stopped and its previously
verified zero Event/zero-link baseline was untouched. No backup, existing manifest,
evidence file, configuration, migration, commit or push was changed.

## Later operational procedure — separate authorization required

1. Review this code, exact scope, pinned files and a recoverable existing backup;
   protect a new report directory. Obtain explicit execution authorization.
2. Stop all application/ingestion/history writers; keep automatic refresh disabled.
   Start only necessary PostgreSQL. Do not launch provider ingestion or the backend.
3. Run the default read-only command and inspect every proposed relationship and
   preservation report. Stop on any target, file, schema or stored-value difference.
4. Only under that separate approval, run the explicit write command above. For
   a repeat/pre-existing Event, independently review its UUID and supply it with
   `--expected-existing-event-id`; never derive approval from the manifest alone.
5. Inspect acknowledged commit, one exact Event/ten exact links, unchanged hashes,
   revision, zero remaining locks and the post-commit result. Preserve artifacts.
   Stop on unknown/failed outcomes; do not retry or repair automatically.

No part of that development execution procedure was performed in this task.

## Final source review and authorized local checkpoint

The checkpoint review started on `master` at the expected
`af5d2365e0df5d2bff9d7d696962482b975cbf5f`, with only these seven new files.
Source, tests and documentation were reviewed independently. One additional
reporting defect was reproduced in isolated PostgreSQL: when commit raised with
an active transaction and rollback cleanup also raised, cleanup could escape
before the outcome was classified, leaving `not_started` and zero committed
counts. The executor now classifies uncertainty before cleanup, records only the
rollback error class, and invalidates the broken connection. The regression
failed before the correction and passed afterward. No operation scope expanded.

Final complete discovery with external HTTP transports blocked:

| Check | Result |
| --- | --- |
| Full backend suite | **400 passed, zero failures/errors/skips**, 55.057 seconds |
| Real PostgreSQL 15.18 tests included above | **82 passed**, including all **28 bounded-linkage PostgreSQL tests** |
| New bounded-linkage tests included above | **60 passed**: 18 scope, 9 mocked CLI, 28 PostgreSQL, 5 target guards |
| External HTTP transport attempts | **0** |
| Python compilation | Passed, exit 0 |
| Git staged whitespace check and new-file whitespace inspection | Passed |
| Automatic refresh | False |

Disposable `proppulse-test-bounded-checkpoint-20261015` used loopback port 52398,
database `proppulse_test_bounded_checkpoint`, temporary test-only trust and tmpfs
without volume/bind mounts. Cleanup verified zero remaining test schemas and
advisory locks, then removed only that container. Development services stayed
stopped; no development connection, manifest generation, Event/link write,
provider request, backup access, new migration, or Phase 3D work occurred.

The seven reviewed files alone are intended for the explicitly authorized local
commit `feat: add guarded verified event linkage operation`. Existing evidence,
manifests, reports, credentials and generated artifacts remain excluded. The
earlier no-commit statement describes the implementation phase. No push or prior
history rewrite is authorized or performed. A development dry-run remains a
separately authorized operational step, and has not been executed here.
