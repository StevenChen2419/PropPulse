# Phase 3A: PostgreSQL verification and local checkpoint

Verified October 14, 2026, following the implementation report and architecture
audit. Starting HEAD was `7ef957ddc35f99126db01dddba48125316a8dc96` on `master`.
All starting changes belonged to the reviewed Phase 3A implementation. Parent and
application AGENTS instructions and the implementation report were reread.

## Isolation and safeguards

Effective automatic refresh was `False` before and after verification. Docker
Desktop and all containers were initially stopped. Only the existing development
PostgreSQL container and one disposable PostgreSQL test container were started.
Backend, Redis, application lifespan, refresh workers, and provider requests were
not started. No development migration, backfill, or database write was performed.

Development access used explicit PostgreSQL read-only transactions. Every public
table was fingerprinted before and after the checks using ordered full-row SHA256
hashes and counts, without exposing row contents. All 13 table fingerprints and
the column-schema fingerprint matched; revision remained `20261014_01`.

Disposable test container: `proppulse-test-m3a-20261014`, cached `postgres:15-alpine`,
PostgreSQL 15.18, loopback port 49944. Its database was
`proppulse_test_milestone3a`, with temporary test-only trust authentication. Data
used tmpfs, with no bind mounts or named volumes. The test URL was supplied only
to test command processes through `PROPPULSE_TEST_POSTGRES_URL`; environment files
and application credentials were unchanged. Existing name-prefix/random-schema
safeguards remained active.

Before cleanup, the disposable database had zero leftover test schemas and zero
advisory locks. The exact disposable container was stopped and removed. Existing
PostgreSQL was restored to its initially stopped state. Existing `proppulse_pgdata`
and `proppulse_redisdata` volumes and all backups were preserved.

## Actual event classification

Executed from `backend`:

```powershell
.\venv\Scripts\python.exe -B scripts/classify_event_backfill.py
```

Result: **6,064 props**, **5,743 populated provider relationships**, and **93 distinct
provider sport/event identities**.

| Classification | Known event groups | Prop rows |
| --- | ---: | ---: |
| Verified retained authoritative metadata | 1 | 10 |
| Requires independent verification | 66 | 3,598 |
| Conflicting metadata | 26 | 2,135 |
| Missing provider identity | Unknown | 321 |
| Explicit legacy/unsupported origin | 0 | 0 |

The classifier's total of 414 classification groups is **not** a count of actual
events: it includes 93 known identities plus one group per identity-missing prop.
No relationship was persisted. Only ten event-to-prop relationships have sufficient
retained evidence for a later reviewed backfill. Another 5,733 provider-linked
props remain unverified/conflicting. Missing-identity origins remain uncertain;
zero explicitly legacy groups does not prove all legacy/synthetic data is absent.

One trusted controlled-smoke JSON supplied the verified event:
`basketball_nba / 26b036ff107f3c658258eaf4a6f26228`, Boston Celtics at Detroit
Pistons, October 20, 2026 at 19:00 UTC. Three unrelated JSON reports were ignored.
Temporary integrity manifests were kept in an ignored subdirectory, outside the
classifier's nonrecursive metadata glob. Player-derived teams supplied no
authoritative participant evidence.

All 26 conflicting groups have inconsistent player-derived keys. One also has
conflicting stored times: MLB event `62d92e8ecf4bb3be97f03a09925eaec3`, 96 props,
August 5, 2026 at 18:10:00 versus 18:10:03 UTC. No rounding, repair, or reassignment
was attempted. No duplicate player/market/sport/event prop groups were found.

The counts match the earlier architecture audit: 6,064 props, 93 populated event
identities, 26 splits, 321 missing identities, and one schedule conflict. This
verification additionally quantifies the evidence-supported versus unresolved
relationship classes. No unexpected schema or data-integrity discrepancy occurred.

### Read-only enforcement

A SQLAlchemy observation hook on the classifier's actual development inventory
connection checked `SHOW transaction_read_only` immediately before its SELECT:
the value was `on`.

A new real-PostgreSQL test used that same classifier connection/code path in an
isolated schema, verified `read only` plus `repeatable read`, and challenged it
with a zero-row UPDATE. PostgreSQL rejected the statement with SQLSTATE `25006`.
A savepoint recovered the test transaction and the inventory SELECT succeeded.
No write challenge was attempted against development data.

## Historical research against stored development observations

Both service calculations and HTTP research responses were exercised through an
isolated FastAPI app, dependency-overridden to read-only development sessions.
No real application lifespan or provider client ran; no clock or timestamp changed.

| Player | Exact line | Eligible logs | L5 Over | L10 Over | Selected 2027 season |
| --- | ---: | ---: | ---: | ---: | ---: |
| Jayson Tatum | 26.5 | 22 | 1/5 (20%) | 1/10 (10%) | 0 games, null rate |
| Cade Cunningham | 24.5 | 81 | 2/5 (40%) | 6/10 (60%) | 0 games, null rate |

Both recent windows identify season 2026 and `previous_seasons`; every loaded row
had a valid points value and remained eligible, with no exclusions or duplicates.
Latest included dates were May 1 and May 18, 2026 respectively, strictly before
the October 20 props. No future observations entered the samples.

Both research endpoints returned HTTP 200 and selected the expected existing
points prop UUIDs. During verification their offers were actionable `last_known`,
with current prices present independently of the zero-game current-season window.
These availability labels are evaluation-time observations, not permanent claims
about the stored offers. Existing static frontend tests separately verify prices
and movement remain rendered even when trends are null. No browser E2E is claimed.

The historical percentages describe observations at the displayed line, not
predictions. Existing completion and regular-season/playoff metadata limitations
remain disclosed by the API/UI.

## Test execution and fixture correction

The first opt-in full suite executed all eleven previously skipped PostgreSQL
tests but found one outdated fixture: an independent-sport rollback test expected
creation of an NBA player without local or roster identity. Phase 3A intentionally
rejects that case. The fixture now supplies a unique roster identity belonging to
the event; no production safety guard or assertion was weakened.

Added real PostgreSQL tests for classifier read-only enforcement and prior-season
NBA research using twelve stored fixture logs through a migrated isolated schema
and HTTP API. Both run with the established disposable-database safeguards.

Final results:

| Directory | Command | Result |
| --- | --- | --- |
| backend | `.\venv\Scripts\python.exe -m unittest discover -s tests -p test_ingestion_postgres.py -v` with disposable test URL | 11 passed, zero skips |
| backend | `.\venv\Scripts\python.exe -m unittest discover -s tests` with disposable test URL | **239 passed, zero failures/errors/skips** |
| frontend | `npm test` | **37 passed, zero failures/skips** |
| frontend | `npx tsc --noEmit` | Passed |
| frontend | `npm run build` | Passed, ten static pages generated |
| root | `.\backend\venv\Scripts\python.exe -m compileall -q backend/app backend/scripts backend/tests` | Passed |
| root | `git --git-dir=.git --work-tree=. diff --check` | Passed |

The final backend total includes 13 real PostgreSQL tests: eleven schema/API/
reconciliation tests and two process-locking tests. Every previously skipped
PostgreSQL test executed. Existing datetime deprecation and AnyIO resource warnings
remain; no dependency upgrade or warning suppression was introduced.

## Review and checkpoint scope

Independent backend/frontend review found no remaining actionable defects. The
local checkpoint includes the implementation report's complete file manifest,
the updated `backend/tests/test_ingestion_postgres.py`, this verification report,
and the implementation report's follow-up link. Only explicitly reviewed source,
tests, and documentation are staged. Credentials, ignored provider reports,
fingerprint manifests, database files, generated builds, and temporary outputs
remain excluded.

The authorized local commit message is
`feat: improve player matching and historical research`. No push or Phase 3B work
is included.

## Readiness and Phase 3B design considerations

Phase 3B can begin as a separate task with a minimal additive Event schema and
nullable prop relationship. The data does not support a blanket backfill or
non-null constraint. Start with the one independently verified event and ten
relationships, then obtain independent evidence for unresolved identities without
guessing from mutable player teams.

Preserve all prop UUIDs, offers, snapshots, saved/slip choices, logs, and user data.
Do not merge split groups, choose between conflicting schedules, or fabricate
missing provider IDs. Event identity must survive schedule corrections, including
the observed three-second discrepancy. Keep legacy fields during rollout and
test both fresh-bootstrap and existing-schema upgrades on isolated PostgreSQL.

Provider athlete identity persistence, competition/final-status metadata, stable
research selection, and legacy route compatibility remain scoped follow-up work.
