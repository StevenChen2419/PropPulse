# Phase 5E — local NBA integration assessment and approval checkpoint

Public-source note: this is a historical private-environment report. The local player mapping, provider response artifacts, backup paths and approval files discussed below are not distributed. They are not required for normal application setup; optional ingestion requires newly reviewed mappings and explicit provider/database authorization.

## Current-season manual refresh (Phase 6)

Run from `backend` with the existing virtual environment. The wrapper reuses
`collect_nba_statistics.build_plan/collect`, the normalizer/`prepare_batch`, and
`import_nba_statistics.main`; it does not add a second importer. Default dry-run
does not connect to PostgreSQL or make HTTP requests. Select exact local Player
UUIDs with `--players UUID [UUID ...]`, or use `--all-verified` (20 reviewed
mappings; unresolved Jalen Brunson is skipped). Collection never runs from API
research requests.

As of **October 19, 2026**, the October 20 season opening has not occurred:
there are no completed 2026–27 Regular Season games. This command safely returns
`no_games_yet`, zero requests and zero writes:

```powershell
.\venv\Scripts\python.exe scripts/refresh_nba_statistics.py --season 2026-27 --competition "Regular Season" --from-date 2026-10-20 --to-date 2026-10-20 --all-verified --dry-run
```

After games finish, choose **completed Eastern dates only** (the end date must
precede today). Example for use **October 23 or later**, after confirming games
in that range completed; the date bound alone does not certify player participation:

```powershell
$refreshArgs = @('--season', '2026-27', '--competition', 'Regular Season', '--from-date', '2026-10-20', '--to-date', '2026-10-22', '--players', 'LOCAL_CUNNINGHAM_PLAYER_ID', '--output-dir', 'data/odds_runs/nba-refresh/2026-10-23-cade', '--max-rows', '100')
.\venv\Scripts\python.exe scripts/refresh_nba_statistics.py @refreshArgs --dry-run
```

Review the displayed exact UUID/NBA-ID associations, endpoint/parameters, dates,
maximum GET budget, artifact destination and plan SHA-256. Obtain **one explicit
collection approval for that manifest**. Replace `APPROVED_PLAN_SHA256` below with
that digest only after approval. The collector uses one GET per selected player,
10-second timeout, no retries/redirects/proxies and at least two seconds between
attempts. Each new collection needs a fresh output directory; source artifacts
cannot be overwritten. Previous authorizations do not carry forward.

```powershell
.\venv\Scripts\python.exe scripts/refresh_nba_statistics.py @refreshArgs --collect-approved APPROVED_PLAN_SHA256
$artifact = 'data/odds_runs/nba-refresh/2026-10-23-cade/collected-responses.json'
.\venv\Scripts\python.exe scripts/refresh_nba_statistics.py @refreshArgs --artifact $artifact --dry-run
```

Collection validates/normalizes offline and stops before import. Empty valid
responses mean zero rows, never fabricated appearances. Failed/partial artifacts
are retained; missing selected responses or invalid rows reject the batch.
The artifact dry-run delegates to the existing **PostgreSQL-enforced read-only**
preview and reports per-player and consolidated added/new, updated, unchanged and
rejected counts. Validation errors reject the batch rather than partially writing
it. It writes ignored `import-preview.json` and `proposed-import-approval.json`.
The proposed approval pins artifact/mapping SHA-256 values, exact development
database host/port/name/role, UUIDs, season/competition/dates and row bound.

Review the actual preview/counts and obtain **separate explicit development import
approval** before executing:

```powershell
.\venv\Scripts\python.exe scripts/refresh_nba_statistics.py @refreshArgs --artifact $artifact --import-approved data/odds_runs/nba-refresh/2026-10-23-cade/proposed-import-approval.json
```

The existing importer revalidates the exact scope and identities, preserves ESPN
and earlier NBA.com history, rejects collisions and older observations, and writes
only PlayerGameLog within its existing transaction. Replay the same artifact with
`--dry-run` to confirm unchanged rows. A later newly observed artifact can report
updates even when counting statistics match because its observation time changed.
For a full-season 20-player batch, choose an appropriate explicit combined
`--max-rows` (default 1,000; maximum 10,000). No schema/migration is required.

The normal NBA research page defaults to the **current Eastern season** even for
a retained old Event. Use its season selector for historical research; the URL
retains season, competition and exact Prop selection across reloads and the
"Research another player" navigation. Current-season summary averages require
NBA.com data; unavailable current data never fills from historical or ambiguous
ESPN history. Two eligible appearances produce two-game L5/L10 samples with
independent valid counts for points/rebounds/assists/minutes. Historical results
are labeled; last appearance and rest retain their selected Event/reference scope.
Odds freshness and unavailable team/opponent evidence remain independent. The
separate ESPN line charts keep their own disclosed historical scope.

No current-season provider manifest is pending as of October 19, and no new
provider request or development write was performed for Phase 6. Real current
coverage still requires future completed games, collection approval, a successful
read-only preview and separate import approval. Team/rest context still depends
on existing evidence availability; refreshing player logs does not collect team
game evidence. Fixtures establish behavior, not live coverage.

Phase 6 verification: focused backend regression **87 passed / 33 skipped**
(disposable PostgreSQL URL unset); frontend **89 passed**, TypeScript and production
build passed. **8 desktop/mobile mocked browser cases passed**; Windows teardown
required stopping the exact task-owned Next test server. Read-only development
queries confirmed empty current scope for all 20 reviewed players and retained
976 historical NBA.com appearances across 18 players. No full backend regression,
live collection/import, authenticated mutation or PostgreSQL write test ran.

**Latest status:** approved remaining-player import completed October 19:
851 additional real NBA.com rows, **976 rows across 18 players** total.
Preservation, read-only idempotency, normal API calculations and representative
browser checks passed. Lillard/Haliburton returned empty; Brunson is unresolved.
Earlier sections retain historical checkpoint status.

October 19, 2026. Starting HEAD verified as
`b6c360ae2c8925dad780a5ba16f936de3732e96a`. This checkpoint does **not** claim
that current NBA.com statistics are operational in the everyday application.
No provider request, migration or application-data write was performed.

## Actual environment and readiness

Read parent/root AGENTS instructions, Phase 5A–5D reports, migration README,
revision sources 01–04, and current readiness/import/API/frontend implementations.
Git initially contained only the two preserved untracked reports. The sandbox
identity could not read Git/Docker normally; elevated read-only commands resolved
that access without changing global Git configuration. No approval rejection occurred.

Settings loaded from the normal backend working directory, without displaying
credentials: `ENVIRONMENT=development`, PostgreSQL host `localhost`, port `5432`,
database `proppulse`, `LIVE_REFRESH_ENABLED=False`. No ambient PG/libpq override
variables were present. No staging/production connection was attempted.

Initially no PostgreSQL listener existed and the connection was refused. Docker
showed all existing Compose services stopped. The user separately approved
**starting PostgreSQL only**. Before starting, the exact container was inspected:

- `proppulse-db-1`, ID
  `f56b623d6ff0b5e408558ab9a5597ecbfe005470ec207914d7df11656e688fc7`.
- Image `postgres:15-alpine`; Compose service `db`; working directory matches this
  repository; existing named volume `proppulse_pgdata` at PostgreSQL's data directory.
- Existing port binding is host port 5432 on unspecified host IP; it was not changed.
- Started that exact container only. Backend and Redis remain stopped. PostgreSQL
  remains running for the approved assessment; no unrelated process was stopped.

Queries then confirmed PostgreSQL **15.18**, database **proppulse**, container
address `172.18.0.2`, and `transaction_read_only=on`. Connections used
`default_transaction_read_only=on`, three-second connection timeout and five-second
statement timeout. Assessment used SELECTs and the existing read-only readiness
validator; transactions were closed without application writes. No personal/user
tables were queried. No application lifespan, create_all, fixture loader, refresh,
seed or ingestion entry point ran.

**Actual Alembic revision: `20261014_02`. Revision `20261018_04` is not applied.**
`check_readiness` returned `not_ready / schema_revision`. The evidence table is
absent. This is the first known readiness failure, not proof that every remaining
schema prerequisite will pass after upgrading. Readiness remains unchanged.

## Local NBA inventory and exact selections

NBA-only SELECTs found **21 Players**, all **21 with Props**; **372 PlayerGameLog
rows** across five players, all source `espn_nba`, covering October 21, 2025 through
June 14, 2026. No NBA log has `_nba` metadata or a `nba_com:` qualified game ID.
There are no current 2026–27 NBA game logs. Player has no NBA person-ID column;
no NBA.com mapping was found in game-log metadata, and no evidence table exists.

Three proposed pilot identities, preserving existing UUIDs:

| Existing Player UUID | Name | Stored team / position / jersey | Props / linked Events | Existing ESPN logs / latest recorded date | Candidate NBA person ID |
| --- | --- | --- | --- | --- | --- |
| `LOCAL_CUNNINGHAM_PLAYER_ID` | Cade Cunningham | Detroit Pistons / DET / PG / 2 | 9 / 1 | 81 / May 18, 2026 | `1630595` |
| `LOCAL_TATUM_PLAYER_ID` | Jayson Tatum | Boston Celtics / BOS / SF / 0 | 9 / 1 | 22 / May 1, 2026 | `1628369` |
| `LOCAL_GILGEOUS_ALEXANDER_PLAYER_ID` | Shai Gilgeous-Alexander | Oklahoma City Thunder / OKC / PG / 2 | 9 / 0 | 83 / May 31, 2026 | `1628983` |

Those ESPN counts are retained observations, not verified Regular Season totals;
competition cannot be inferred from their dates. All three have zero NBA.com
statistical rows and zero current-season observations in the assessed database.
Stored team fields are context, not independently verified current rosters.

Cunningham and Tatum share existing Event
`LOCAL_EVENT_ID`, provider `the_odds_api`, sport
`basketball_nba`, Detroit Pistons home / Boston Celtics away. Its stored naive UTC
start is October 20, 2026 19:00 UTC, or **3:00 p.m. Eastern**. This describes the
persisted Event; it does not independently certify the real NBA schedule.

| Player | Existing example Prop | Market / stored line | Last odds observation |
| --- | --- | --- | --- |
| Cunningham | `LOCAL_CUNNINGHAM_PROP_ID` | points / 24.5 | October 14, 2026 19:36:33 UTC |
| Tatum | `LOCAL_TATUM_PROP_ID` | points / 26.5 | October 14, 2026 19:36:33 UTC |
| Gilgeous-Alexander | `LOCAL_GILGEOUS_ALEXANDER_PROP_ID` | threes / 1.5; no linked Event | September 10, 2026 18:31:34 UTC |

These are actual stored selections, not newly created lines. Observation dates are
older than the six-hour actionable TTL. No active price or fresh offer is asserted.
No Event link was added for Gilgeous-Alexander; his statistics can use player-only
research. Other inventory candidates included Wembanyama with ten Props but no
linked Event. The pilot favors the two linked identities plus one with recorded history.

## Identity review requirement

The installed offline `nba_api.stats.static.players.get_players()` directory has
exact unique entries for the three displayed names and candidate IDs above.
No HTTP was used. Local sport/team/position/jersey and existing Prop/Event context
were inspected independently, but the static directory contains names/IDs/activity,
not roster/jersey evidence proving the association to a local UUID.

**These are proposed crosswalks, not accepted reviewed mappings.** Name matching
alone is insufficient. Before collection/import, obtain an explicit review of each
exact UUID/person-ID association, supported by an independently established
provider roster/profile association or the user's informed identity review.
Record per-association provenance through `verified_crosswalk`; do not set
`verified=True` from this name-directory lookup alone. No replacement Player is needed.

## Retired collection manifest

The October 1–18, 2026 request manifest is **retired**, superseded by the user's
October 19 continuation. No requests were executed against it and none may be
spent on that window. Per the user's corrected season timing, the 2026–27 Regular
Season begins October 20; preparation now concerns the database only.

There is **no active or approval-pending provider manifest** at this checkpoint.
After database readiness, prefer separately approved 2025–26 historical Regular
Season data immediately, or 2026–27 only after completed Regular Season games.
Prepare exact dates/player IDs/request counts then; do not reuse the retired scope
or the exhausted Phase 5D authorization. Never combine these season scopes.

## Import architecture and preview

Reuse `nba_api_provider.normalize_player_statistics` →
`nba_statistics_service.import_player_statistics` → existing PlayerGameLog →
`nba_season_summary` / `nba_matchup_context` → existing player research endpoint.
No provider HTTP belongs in API requests. The current frontend forwards explicit
season/competition and retains selected Props across navigation. Its backend
default uses the selected Event's Eastern season, or evaluation time for player-only
research: these October references default to **2026–27 Regular Season**.
Historical URLs already accept `season=2025-26&competition=Regular%20Season`;
no new season selector or frontend change is necessary for the pilot.

| Preview item | Current fact / proposed scope |
| --- | --- |
| Target | development `localhost:5432/proppulse`, exact existing container above |
| Players | three exact UUIDs in the crosswalk table, pending identity review |
| Season / competition | Not yet selected; the original 2026–27 preview is retired. Any future import requires a separately approved single-season scope. |
| Collected / normalized rows | unknown; no new source responses collected |
| Existing NBA.com rows / matching qualified IDs | zero for all three; no qualified NBA IDs anywhere in NBA logs |
| New / updated / unchanged rows | unknown until responses and a read-only comparison exist; do not equate all responses with new rows |
| Collisions | no existing NBA-qualified rows found; actual batch identity, source, date and scope validation still required |
| Preserved history | 186 existing ESPN observations across the three players, untouched |
| Transaction | one clean outer SQLAlchemy transaction covering all selected-player batches; importer savepoints; rollback whole operation on any failure; commit once only after separate approval |
| Allowed eventual row writes | exact pilot PlayerGameLog rows only; no Player/Prop/Event/odds/user/selection changes |
| Expected display | actual partial L5/L10 PTS/REB/AST/MIN, valid per-metric counts, source, season, last recorded appearance and calendar gaps if eligible rows exist; otherwise explicit unavailable state |

Identical replay is unchanged; a newer observation timestamp can produce an update
even if numeric statistics are identical. Reject older observations, dirty sessions,
unknown players and identity/source/scope collisions. Keep `nba_com:<ten-digit ID>`
game identities and ESPN rows. Do not manufacture logs to persist an empty result.
An empty current scope may still show the existing unavailable ESPN fallback label;
it must not be claimed as populated NBA.com coverage.

Team preview is separate: **zero stored evidence records because the table is
absent; collected supported games/teams and unresolved groups are unknown**.
Reuse `normalize_team_games` for reciprocal paired completed results. The existing
`append_normalized_evidence` remains restricted to `proppulse_test_*` targets;
it cannot be used operationally or have its guard relaxed. A small separately
reviewed operational append boundary is needed before any team-evidence write.
No team write is included in the proposed statistics transaction. Defer it if
there is no useful completed coverage. Team/rest/opponent calculations keep their
existing fresh-identity, exact-Event and partial-coverage guards; no unsupported
negative back-to-back, current team identity or opponent result is promised.

No new operational command was added before identities/source inputs are reviewed.
The eventual minimum caller needs an explicit dry-run using normalization and
SELECT-only comparison, exact target/crosswalk/season/artifact pins, readiness
validation, and the single outer transaction above. It must never import via test
fixture loaders. No parallel pipeline, model, migration or evidence framework is needed.

## Exact migration proposal — requires separate approval

Target remains the same development database. Required path is
`20261014_02 → 20261017_03 → 20261018_04`. From `backend`, the intended command,
**not executed**, is:

```powershell
.\venv\Scripts\python.exe -m alembic -c alembic.ini upgrade 20261018_04
```

Revision03 adds the evidence table, foreign key, constraints/indexes and append-only
guard/function; revision04 validates it and broadens the provider namespace CHECK
to include NBA.com. Alembic version metadata advances. These two revisions are
additive, with no existing sports/user row backfill or deletion. Earlier revision01
does contain an ingestion-time backfill, but it is already behind the actual revision
and is not part of this upgrade. Never stamp or relax readiness.

Take one small local logical backup before the approved upgrade, as required by
the migration runbook. Backup creation/location must be included in approval;
none was created or inspected here. No disaster-recovery rehearsal is necessary.
PostgreSQL transactional DDL rolls back a failed upgrade. After a committed
upgrade, keep additive schema during code rollback; automatic downgrades refuse.
Any schema removal or backup restore needs separate review, especially because
restore can discard later writes. Recheck read-only readiness after an approved
upgrade; migration success alone does not establish complete readiness.

## Changes, checks and authorized operations

Only this report is added. Executable source, configuration, migrations, fixture
guards and saved/slip behavior are unchanged. Independent backend source review
confirmed the reused importer and the separate team-writer limitation.

Fresh provider-blocked focused checks, with **no disposable PostgreSQL URL set**:

| Command via `tests/run_no_provider_http.py` | Actual result |
| --- | --- |
| `test_nba_statistics_import.py` | 9 passed, 3 PostgreSQL tests skipped |
| `test_nba_season_summary.py` | 5 passed, 1 PostgreSQL test skipped |
| `test_nba_matchup_context.py` | 21 passed, 1 PostgreSQL test skipped |

All three commands exited 0 and each recorded zero external HTTP attempts.
These are **35 passed / 5 skipped**, not PostgreSQL import verification.
No test points at the development database. Disposable PostgreSQL idempotency/API
tests, frontend tests/TypeScript, desktop/mobile browsers, ordinary production build
and full regression suites were not run: no executable changes/import occurred,
and the normal application lacks its required migration. Prior milestone results
are not fresh Phase 5E results. No normal-app browser success is claimed.

The sole separately authorized operation was starting the existing PostgreSQL
container. Read-only sports assessment was covered by the initial authorization.
All provider, migration, backup and import approvals remain outstanding.

## Remaining approvals and blockers

1. Review the three proposed exact UUID/person-ID associations with adequate
   identity provenance; they are not accepted from names alone.
2. Separately authorize the target-specific local backup and migration above.
3. After database readiness and identity review, prepare and separately authorize a new bounded historical or post-opening current-season manifest; the old manifest is retired.
4. With actual responses, implement/test the smallest necessary offline operational
   caller using mocks and disposable PostgreSQL; present exact new/updated/unchanged
   counts, collisions and any separate supported team append preview.
5. Separately approve the final artifact/target/row scope before development import.
6. Only afterward verify the normal application's exact selections and current versus
   historical coverage on desktop/mobile. Empty current-season samples remain valid.

Preserved reports retain SHA-256:

- `docs/phase-5a-simplification-audit.md`:
  `2efcc90e58203aba9ac81980d3cf143b561296943faa9fbb23acd05f38231f96`.
- `docs/milestone-4a4-espn-collection-plan.md`:
  `369d01900c5e69681fadc2438c214643136490b4f7b2703868920c4845e171b3`.

Final Git status was verified: exactly the new Phase 5E report plus those same two
preserved untracked reports; no tracked changes or staged files. HEAD still matches
the starting checkpoint. Tracked whitespace checks and the new report's UTF-8,
trailing-whitespace and final-newline checks passed; both preserved hashes matched.
Only the approved PostgreSQL container is running and healthy. Independent read-only
review found no source/report contradictions. No deployment, commit or push.

## Continuation — database preparation approval checkpoint, October 19

This section supersedes the earlier collection proposal and approval ordering.
The October 1–18 manifest is retired above. **Nothing below has been executed.**
Identity/profile research below is distinct from statistics collection; no NBA.com
endpoint or profile was directly requested, no sports API collector ran, and no
statistical payload was downloaded or stored.

### Independent identity evidence and limits

Read-only SELECTs reconfirmed the three local UUID/name/team/position/jersey rows.
The installed offline NBA directory again returned Cunningham `1630595`, Tatum
`1628369`, and Gilgeous-Alexander `1628983`. Independent ESPN search-index evidence:

| Candidate local UUID → NBA ID | Independent provider evidence | Review status |
| --- | --- | --- |
| `LOCAL_CUNNINGHAM_PLAYER_ID` → `1630595` | [ESPN biography, ID 4432166](https://insider.espn.com/nba/player/bio/_/id/4432166/cade-cunningham): Detroit Pistons, jersey 2 | Team/jersey corroborated; exact local/provider association unresolved |
| `LOCAL_TATUM_PLAYER_ID` → `1628369` | [ESPN profile, ID 4065648](https://www.espn.com/nba/player/_/id/4065648/jayson-tatum): Boston Celtics, jersey 0, forward | Team/jersey/position corroborated; exact local/provider association unresolved |
| `LOCAL_GILGEOUS_ALEXANDER_PLAYER_ID` → `1628983` | [ESPN team page](https://www.espn.com/nba/team/_/name/OKC/Thunder): Oklahoma City, jersey 2, guard; [profile ID 4278073](https://www.espn.com/nba/player/_/id/4278073/shai-gilgeous-alexander) independently identifies the player/team | Team/jersey/position corroborated; exact local/provider association unresolved |

Evidence was reviewed October 19 through indexed provider pages, whose stated
crawl ages were approximately six months. Direct requests for the three main
ESPN profiles returned a JavaScript/robot-verification challenge; no bypass was
attempted. Search snippets also surfaced NBA links; those were not opened or used
as newly collected NBA evidence. The independent evidence supports the identity
traits, but does not establish a durable provider-ID link to these local UUIDs or
fresh October roster membership. **Zero crosswalks are marked confirmed for import.**
The NBA IDs are confirmed only as entries in the installed static directory.
Retain the candidates and require an explicit independently supported UUID-level
association review before any import. Schema upgrade does not depend on resolving
these mappings and creates no athlete mappings.

### Reconfirmed target and exact migration effects

Fresh read-only checks: development `localhost:5432/proppulse`, PostgreSQL 15.18,
revision `20261014_02`, evidence table absent, readiness `schema_revision`.
Backend container remains stopped; no listener on port 8000 was found. PostgreSQL
alone remains running. Container tools `pg_dump` and `pg_restore` both report 15.18.

Verified revision declarations and implementation:

1. `20261017_03.down_revision = 20261014_02`: creates `nba_evidence_records`,
   primary/unique/check constraints, four indexes, a nullable Player FK with
   `ON DELETE RESTRICT`, and the append-only trigger/function. Starts with zero
   evidence rows. Existing Player, Event, Prop, odds, history and user rows are
   neither rewritten nor linked/backfilled.
2. `20261018_04.down_revision = 20261017_03`: validates that table and guard,
   replaces only its provider namespace CHECK to accept ESPN and NBA.com, and
   validates again. Alembic advances its revision marker.

Earlier revisions 01/02 do not rerun; in particular revision01's ingestion-time
backfill and empty-database bootstrap do not execute on this target. No create_all,
provider calls, polling or application lifespan is involved. The migration README's
old revision02 head statement is historical; revision files and current readiness
require revision04.

`env.py` uses PostgreSQL transactional DDL and one migration transaction (no
per-revision commit/autocommit). The supplied-connection operation below places
both upgrades and full readiness validation inside one explicit outer transaction.
Any exception rolls back the entire operation before commit, including the table,
guards, constraint change and revision marker. No stamp, schema repair, automatic
downgrade, import or restore is allowed by this plan.

### Exact proposed backup operation

Backup destination on the host:

`<repository-root>\backend\data\odds_runs\5e\proppulse-before-20261018_04-20261019.dump`

SHA-256 sidecar: the same path plus `.sha256`. The existing ignored `odds_runs`
directory keeps these files out of Git; no directory or backup file has been created
for this continuation. Destination absence was checked. The full database archive
includes private user/authentication data necessary for recovery; keep it local,
do not display its contents, attach it to this chat or commit it. Confirm normal
user-only access to the destination before creation. It excludes cluster-global
roles/tablespaces, which this migration does not change.

After approval, recheck the exact container ID/Compose directory/volume, development
settings and revision02. Keep backend/refresh/manual ingestion stopped throughout;
stop if another writer is active rather than terminating unrelated sessions.
Capture aggregate counts of existing tables without retrieving personal records.
Check free space first; if inadequate, stop rather than changing storage. The
custom-format dump is compressed by pg_dump's default; actual size is unknown.

Proposed PowerShell from the repository root (stop on every nonzero native exit):

```powershell
$containerId = 'f56b623d6ff0b5e408558ab9a5597ecbfe005470ec207914d7df11656e688fc7'
$backupPath = '<repository-root>\backend\data\odds_runs\5e\proppulse-before-20261018_04-20261019.dump'
$archivePath = '/tmp/proppulse-5e-before-04-20261019.dump'
if ((Test-Path -LiteralPath $backupPath) -or (Test-Path -LiteralPath "$backupPath.sha256")) { throw 'Backup destination exists' }
docker exec $containerId test ! -e $archivePath
if ($LASTEXITCODE -ne 0) { throw 'Container archive path unavailable' }
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $backupPath) | Out-Null
docker exec $containerId pg_dump --host=/var/run/postgresql --port=5432 --username=proppulse --dbname=proppulse --no-password --format=custom --lock-wait-timeout=5s --file=$archivePath
if ($LASTEXITCODE -ne 0) { throw 'pg_dump failed; do not migrate' }
docker exec $containerId pg_restore --list $archivePath | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Archive listing failed; do not migrate' }
docker exec $containerId pg_restore --exit-on-error --file=/dev/null $archivePath
if ($LASTEXITCODE -ne 0) { throw 'Archive full decode failed; do not migrate' }
$containerDigest = docker exec $containerId sha256sum $archivePath
if ($LASTEXITCODE -ne 0) { throw 'Container checksum failed' }
docker cp "${containerId}:$archivePath" $backupPath
if ($LASTEXITCODE -ne 0) { throw 'Backup copy failed; do not migrate' }
if ((Get-Item -LiteralPath $backupPath).Length -le 0) { throw 'Empty backup' }
$backupDigest = (Get-FileHash -LiteralPath $backupPath -Algorithm SHA256).Hash
if ($backupDigest -ine ($containerDigest -split '\s+')[0]) { throw 'Backup checksum mismatch' }
Set-Content -LiteralPath "$backupPath.sha256" -Value $backupDigest -Encoding ascii
```

The explicit Unix socket selects this database inside the verified container,
avoiding ambient PGHOST/network routing. `--no-password` fails closed if local
authentication requires a password; do not add credentials or relax authentication.
No binary PowerShell redirection is used. The container copy is temporary and stays
until the host copy is verified; later cleanup removes only that exact temporary
file, never the host backup or database volume. That cleanup is not required to
perform the upgrade and can wait until the checkpoint is reported.

Verification requires pg_dump exit 0, readable archive TOC, successful full
`pg_restore --file=/dev/null` decode, nonempty host copy and matching host/container
SHA-256. Record size/digest/actual completion time. TOC review must include the
14 existing public tables, their data entries, schema/constraints and the
`alembic_version` TABLE DATA entry. Its revision02 value must be checked live
immediately before backup; TOC listing cannot verify that row's value.
This checks archive structure/decompression/transport integrity; it is
**not a test restore or proof of full recovery**, and no recovery rehearsal or
new PostgreSQL instance is proposed. If anything fails, do not migrate or overwrite
partial files; report the exact failure for review.

### Exact proposed migration and verification operation

Only after the backup checks above succeed, run from
`<repository-root>\backend`.
The following is the guarded equivalent of
`.\venv\Scripts\python.exe -m alembic -c alembic.ini upgrade 20261018_04`:

```powershell
@'
import os
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from app.config import settings
from app.services.schema_readiness import validate_database

u = make_url(settings.DATABASE_URL)
assert settings.ENVIRONMENT == 'development' and not settings.LIVE_REFRESH_ENABLED
assert u.get_backend_name() == 'postgresql'
assert u.host == 'localhost' and (u.port or 5432) == 5432 and u.database == 'proppulse'
assert not u.query  # Reject libpq host/service/other URL overrides.
assert not any(k.startswith('PG') for k in os.environ)
engine = create_engine(settings.DATABASE_URL, connect_args={
    'connect_timeout': 3, 'options': '-c lock_timeout=5000 -c statement_timeout=60000'})
try:
    with engine.begin() as c:
        assert c.execute(text('SELECT current_database()')).scalar_one() == 'proppulse'
        assert c.execute(text('SELECT version_num FROM alembic_version')).scalars().all() == ['20261014_02']
        assert c.execute(text("SELECT to_regclass('public.nba_evidence_records')")).scalar_one() is None
        tables = inspect(c).get_table_names(schema='public')
        quote = c.dialect.identifier_preparer.quote
        def counts():
            return {t: c.exec_driver_sql('SELECT count(*) FROM public.' + quote(t)).scalar_one()
                    for t in tables if t != 'alembic_version'}
        before = counts()
        cfg = Config('alembic.ini')
        cfg.attributes['connection'] = c
        command.upgrade(cfg, '20261018_04')
        validate_database(c)
        assert counts() == before
        assert c.execute(text('SELECT count(*) FROM nba_evidence_records')).scalar_one() == 0
    print('Committed revision04; readiness prerequisites and existing row counts passed')
except Exception:
    raise SystemExit('Upgrade or verification failed; stop and inspect actual revision read-only') from None
finally:
    engine.dispose()
'@ | .\venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'Migration failed; stop' }
```

Do not run this block before explicit approval. It checks the exact settings/target,
pre-upgrade revision and absent evidence table, applies only revisions03/04, validates
all current schema/readiness prerequisites **before committing**, and compares
aggregate existing table counts without exposing user records. Counts do not prove
byte-level preservation, but the reviewed migrations contain no existing-row DML.
Backup and aggregate-count baselines bracket the upgrade with all writers stopped.

After commit, reconnect with `default_transaction_read_only=on`: confirm database,
version `20261018_04`, zero evidence rows, unchanged existing-table counts and
`check_readiness(engine, settings) == {'status': 'ready'}`. Readiness checks model
columns/PK/FK/unique constraints, valid indexes/constraints, exact Event-link guard,
evidence namespace and append-only guard. Keep the backend stopped even if ready.
Do not infer successful UI/statistical coverage from schema readiness.

On a lock/statement timeout, conflicting existing object, readiness mismatch or
count mismatch, the block rolls back and stops. Inspect the resulting revision in
a new read-only connection; do not retry blindly, stamp, repair or delete objects.
If the client disconnects around commit, first establish the actual revision rather
than assuming rollback. After successful commit, retain additive schema during code
rollback. Any physical rollback/backup restore needs separate approval; restoring
can erase post-backup writes. The archive is retained; no automatic downgrade exists.

### Approval requested, and work deliberately not performed

Approve only: create and verify the exact logical backup/sidecar above, then apply
the guarded `02 → 03 → 04` upgrade and read-only preservation/readiness checks to
this verified local development database. Keep the backend stopped afterward.
No identity mapping write, statistical import, provider collection, application
startup, deployment or unrelated infrastructure operation is included.

At this checkpoint **no backup, migration or statistics import exists**. Checks
performed were read-only local target/revision/identity/readiness checks, backup-tool
version checks, destination absence and stopped-backend verification, plus independent
identity source review. No executable source changed; earlier focused test results
remain historical to the first Phase 5E checkpoint, not rerun for this document edit.

## Authorized backup and migration execution record

October 19, 2026. The user explicitly authorized the exact local development
backup, documented verification, revisions03/04, transactional preservation and
readiness checks, then fresh read-only verification. This authorization excluded
provider requests, identity writes, statistics imports, refresh/backfill, application
startup, automatic restore/downgrade/stamp and deployment. Those exclusions were
preserved. This execution supersedes the earlier pending backup/migration status.

### Preflight and backup results

Reconfirmed the same exact container ID, Compose working directory, existing
`proppulse_pgdata` volume, development settings, `localhost:5432/proppulse`, no
URL query/libpq environment overrides, refresh disabled, PostgreSQL 15.18,
revision02 and absent evidence table. Read-only preflight found zero other active
database clients. Backend/Redis were stopped, with no listeners on ports 8000,
3000 or 3199. No service was started during this execution.

Both backup tools were version 15.18. Host free space was approximately 29 GB;
container `/tmp` had approximately 993 GB available. Parent/destination/file ACL
checks found no allow rules for Everyone, Authenticated Users or built-in Users.
Neither backup destination nor checksum sidecar existed. No access policy was
changed. Aggregate row counts were captured without reading personal records.

The approved pg_dump command used the explicit container-local Unix socket,
database/role/port, custom format, noninteractive authentication and five-second
lock-wait bound. It completed successfully. Results:

| Check | Actual result |
| --- | --- |
| Host archive | `<repository-root>\backend\data\odds_runs\5e\proppulse-before-20261018_04-20261019.dump` |
| Size | **2,699,493 bytes** |
| Backup start / verified | **20:17:43.875 / 20:17:44.750 UTC**, or **4:17 p.m. Eastern**, October 19 |
| pg_dump exit | **0** |
| pg_restore TOC | Exit 0; all **14** expected tables and **14** TABLE DATA entries, including alembic_version, plus constraints |
| Full archive decode | `pg_restore --exit-on-error --file=/dev/null`: **exit 0** |
| Container/host SHA-256 | **Matched** |
| SHA-256 | `0fe4a3989872c94367e8e575980fc19e28ea171f57c200bef80b2f54f2ba5ecf` |
| Sidecar | Same host path plus `.sha256`, written successfully |

The pre-backup live query confirmed revision02; TOC review verified its table-data
entry, not the marker value inside the archive. The host backup was rehashed before
migration and after fresh verification and still matched. No restore was performed;
archive/decompression/hash verification is not a claim of tested recovery.

The temporary archive remains at `/tmp/proppulse-5e-before-04-20261019.dump` inside
the same container. The verified host archive and sidecar are retained and ignored
by Git. Neither binary nor personal backup contents were displayed or attached.

### Transaction and fresh verification

The approved guarded Alembic supplied-connection operation ran from `backend`.
Before changing schema, it rechecked target settings, revision02, absent evidence
table, no other active clients, backup/sidecar hashes, and exact agreement with
the pre-backup aggregate baseline. A single outer PostgreSQL transaction applied
only revisions `20261017_03` and `20261018_04`.

Before commit, full `validate_database` passed, all existing-table counts matched,
the new evidence table contained zero rows, and the revision was exactly 04. The
transaction committed at **20:18:10.811 UTC / 4:18 p.m. Eastern**.

At **20:18:33.602 UTC**, a fresh connection with
`default_transaction_read_only=on` reconfirmed the exact database, revision04,
all schema prerequisites, all counts and the backup checksum. The normal
`check_readiness` returned **`{'status': 'ready'}`**. There were no backup,
migration, transactional validation or post-commit verification errors.

| Existing table | Before backup | Before commit | Fresh after commit |
| --- | ---: | ---: | ---: |
| alembic_version | 1 | 1 (marker04) | 1 (marker04) |
| events | 1 | 1 | 1 |
| fatigue_scores | 20 | 20 | 20 |
| interactions | 149 | 149 | 149 |
| player_game_logs | 30,865 | 30,865 | 30,865 |
| players | 1,050 | 1,050 | 1,050 |
| prop_book_snapshots | 19,586 | 19,586 | 19,586 |
| prop_books | 6,544 | 6,544 | 6,544 |
| props | 6,064 | 6,064 | 6,064 |
| rankings | 0 | 0 | 0 |
| saved_props | 0 | 0 | 0 |
| slip_items | 0 | 0 | 0 |
| slips | 2 | 2 | 2 |
| users | 3 | 3 | 3 |

The new `nba_evidence_records` table contains **0 rows**. Total retained rows
including the one Alembic marker are **64,285** across the 14 pre-existing tables;
there are now 15 tables. The marker changed from 02 to 04 as approved. Counts establish
row-count preservation, not byte-level fingerprint equality; the reviewed migration
path contains no existing application-row DML. No application records were edited
by an import, backfill or other operation.

Only PostgreSQL remains running and healthy. Backend and Redis containers remain
stopped; no backend/frontend listener exists on 8000, 3000 or 3199. No provider
HTTP, mapping creation, statistics import, refresh, backfill, readiness bypass,
stamp, downgrade, restore, commit, push or deployment occurred. The retired
October 1–18 collection manifest remains retired. Schema readiness does not imply
populated NBA.com research or normal-app UI verification.

No executable source changed, so application regression/build/browser suites were
not rerun for this operation. Verification was the approved backup integrity checks,
transactional schema/readiness/count checks and fresh read-only checks above.
Protected untracked reports retain their original hashes. Changes remain limited
to this untracked report plus ignored backup artifacts, with nothing staged.
Stop here; any real-data collection and subsequent import need separate approval.

## Reusable NBA statistics workflow — October 19, 2026

Implemented `backend/scripts/import_nba_statistics.py` around the existing
normalizer/importer. It previews with a PostgreSQL read-only transaction and reports
added/updated/unchanged per player. `--execute --approval <scope.json>` requires the
exact preview scope: database host/port/name/role, mapping and artifact SHA-256,
selected UUIDs, season, competition, date bounds and maximum rows. Execution locks
the selected Players and commits one outer transaction; any failure rolls back the
whole batch. Only PlayerGameLog is written. ESPN history and all other tables stay
untouched. No migrations, research HTTP, tables or dependencies were added.

The single reviewed file is `backend/data/nba_player_mappings.json`, a JSON list:

```json
[{"player_id":"<existing UUID>","nba_player_id":"<NBA person ID>",
  "player_name":"<local review name>","review_status":"verified",
  "provenance":"<independent association evidence and review>"}]
```

It covers all **21** existing NBA Players: **20 verified, one unresolved** (Jalen
Brunson lacks local jersey/position corroboration). Independent ESPN profiles and
historical roster evidence corroborate local team, jersey and broad position;
the installed offline NBA directory supplies the unique NBA ID. This explicit
multi-trait association review supersedes the earlier unresolved pilot assessment;
it does not certify current roster membership. Exact evidence links accompany each
verified entry. Unreviewed identities are skipped with explanations. New odds-ingested
players use the same format after reliable identity review; names alone never suffice.
The command accepts up to 100 mappings and 10,000 total rows, at most 1,000/player.

Supported scopes are **2025-26 Regular Season, 2025-10-01–2026-06-30**, and
**2026-27 Regular Season, starting 2026-10-20**, ending no later than 2027-06-30
and strictly before the current Eastern date. The latter has no eligible interval
on October 19. Provider game IDs and named seasons are validated independently;
current and historical samples are never mixed.

Collection is separate: `scripts/collect_nba_statistics.py` displays a plan by
default. Execution requires separately approved `--approved-plan-sha256` and an
exclusive new `--output` artifact. It uses existing nba_api PlayerGameLog only,
ten-second timeout, zero retries/redirects, two-second spacing and one request per
selected reviewed player. Its artifact envelope is
`{season,competition,date_from,date_to,responses:[{nba_player_id,observed_at,payload}]}`.
Original responses and receipt timestamps are retained; no database is opened.

Dry-run example from `backend` (omit `--player` to select all reviewed mappings
represented in the artifact; repeat it for a subset):

```powershell
.\venv\Scripts\python.exe scripts/import_nba_statistics.py `
  --mapping data/nba_player_mappings.json --artifact <collected-artifact.json> `
  --season 2025-26 --competition 'Regular Season' `
  --date-from 2025-10-01 --date-to 2026-06-30 --max-rows 2100
```

Read-only development validation reused two previously collected Phase 5D responses:
LeBron James (`LOCAL_JAMES_PLAYER_ID`, NBA 2544), 60 rows, and
Nikola Jokic (`LOCAL_JOKIC_PLAYER_ID`, NBA 203999), 65 rows.
The real CLI preview reports **125 added / 0 updated / 0 unchanged**, without writing.
The adapted artifact, original-artifact digest, preview and exact proposed approval
JSON remain ignored under `backend/data/odds_runs/5e/fastnba-*`. This is a preview,
not permission to execute and not a completed development import.

**Proposed live pilot batch:** exactly three GETs to
`https://stats.nba.com/stats/playergamelog`, PlayerID **1630595, 1628369, 1628983**;
Season=2025-26, SeasonType=Regular Season, LeagueID=00, DateFrom=10/01/2025,
DateTo=06/30/2026. No LeagueGameLog or current-season request is proposed. Plan SHA-256:
`b2142e0fd36c58fd178381265415e487fb718da28d334b2111fa225db607852e`.
After approval and collection, preview these three UUIDs with a maximum **300 rows**
on development `localhost:5432/proppulse`, role `proppulse`; approve the resulting
exact artifact/mapping digests before executing. Its artifact digest cannot exist
before collection, so no pilot import approval is yet possible.

An immediately reviewable alternative needs no new HTTP: the existing two-player
125-row preview above. Its exact proposed scope is
`backend/data/odds_runs/5e/fastnba-existing-proposed-approval.json`, database
`localhost:5432/proppulse`, role `proppulse`, the two UUIDs above, historical scope
above, maximum 125 rows; mapping SHA-256
`cbdbedce36b4d6553345cdb843950dcaedbc196837f832008fedbbcdbfd9da03`, artifact SHA-256
`a681a1d9e979cf305655b41eb9a993154b75a08c5d8da937d0690731a000ca96`.
This alternative also requires separate approval. No development import ran.

The normal development player page remains pending a separately approved import. Historical
imports cannot establish fresh team membership or complete team-rest coverage;
existing rest/opponent guards retain their unavailable states when unsupported.

Actual verification (no new provider HTTP):

- Workflow/approval tests: **17 passed**, including **6 disposable PostgreSQL**
  cases for batch/idempotence/rollback, ESPN and other-table preservation, missing
  samples, L5/L10/minutes, exact linked Prop/Event and player-only research.
- Existing normalizer/importer: **12 passed**, including disposable PostgreSQL.
- Collection interface: **5 passed**, mocked nba_api and blocked provider HTTP;
  includes unresolved-player skipping and rejection of pre-opening current scope.
- Full backend checkpoint: **955 run, 953 passed, 2 artifact-dependent skips**,
  no failures/errors, **zero external HTTP transport attempts**, 163.296 seconds.
  Those two skipped real-artifact PostgreSQL cases were then run with the retained
  Phase 5D artifact: **2 passed**, 3.920 seconds. No second full suite was run.
- Existing desktop/mobile research browser checks: **6 passed**, exit 0, using
  isolated invented statistics and PostgreSQL-enforced read-only API. Windows
  server teardown required stopping the verified test Next.js process afterward;
  the runner then completed successfully. These are not development-data UI checks.
- Changed Python compilation and whitespace checks passed. Frontend unit tests,
  TypeScript and a new production build were not run: no frontend source or API
  response contract changed. Browser checks used the existing production build.

Disposable PostgreSQL 15 (`proppulse-test-fastnba`, loopback port 57507, tmpfs,
no host mounts) and the browser API were stopped after checks. Development remained
revision04/ready with 21 NBA Players, all 372 NBA logs still ESPN, 30,865 total logs
and no NBA.com statistics imported. Git HEAD remains the requested b6c360a;
six new source/config/test files and this existing untracked report are uncommitted.
The pre-existing Phase 5A and Phase 4A.4 reports were left untouched.

## Fast-track existing-artifact approval checkpoint — October 19, 2026

HEAD remains `b6c360ae2c8925dad780a5ba16f936de3732e96a`. The existing CLI dry-run
was rerun against development `localhost:5432/proppulse`, role `proppulse`, for
2025-26 Regular Season, October 1, 2025–June 30, 2026, maximum 125 rows:

| Player / exact local UUID / NBA ID | New | Updated | Unchanged | Rejected |
| --- | ---: | ---: | ---: | ---: |
| LeBron James / `LOCAL_JAMES_PLAYER_ID` / 2544 | 60 | 0 | 0 | 0 |
| Nikola Jokic / `LOCAL_JOKIC_PLAYER_ID` / 203999 | 65 | 0 | 0 | 0 |

Fresh read-only checks confirmed revision `20261018_04`, readiness `ready`, exact
reviewed names/team/position/jersey mappings, no existing logs for these players,
and successful importer identity/source/game-context collision validation. All 372
NBA logs remain ESPN; total logs remain 30,865. Aggregate content fingerprints for
all 15 tables and ESPN logs are retained in ignored
`backend/data/odds_runs/5e/fastnba-current-readonly-validation.json` for subsequent
preservation checks; no personal row contents were emitted.

Approved-proposal artifact/mapping digests still match those above. The adapted
response objects exactly equal the retained Phase 5D response objects, whose file
SHA-256 is `7e19720415833449f64f55f5bbb4cd21166f00fe26e01da0571b3358f0fe0666`.
The retained backup and sidecar still match
`0fe4a3989872c94367e8e575980fc19e28ea171f57c200bef80b2f54f2ba5ecf`.
The unchanged proposed approval JSON hashes to
`f70068a7ad3c138f8b641aa1846c3ff7bbbfba039478d64c92803be2c97c5fcc`.

Execution requires explicit user approval, then the same command with
`--execute --approval data/odds_runs/5e/fastnba-existing-proposed-approval.json`.
It locks selected Players, validates collisions, uses per-player savepoints inside
one outer transaction, and commits only on success; exceptions roll back the whole
operation. Only reviewed PlayerGameLog rows may change. A post-commit backup restore
is not automatic and requires separate approval.

Focused checks: workflow **11 passed / 6 skipped**; importer **9 passed / 3 skipped**.
PostgreSQL fixture tests skipped because no explicit disposable test database was
configured; none targeted development data. No executable changes, full-suite run,
provider HTTP, database writes, service startup, commit, push or deployment occurred.
Normal-app API/browser verification and idempotency remain pending import approval.

## Authorized import completed — October 19, 2026

The user explicitly approved the exact hashes, two UUIDs, historical scope and
125-new-row limit above. Immediately before execution, all approved hashes, source
payload equality, backup, revision04/readiness, exact dry-run counts and existing
table fingerprints were reconfirmed. The existing CLI ran once with `--execute`
and the unchanged proposed approval JSON: **LeBron 60 inserted, Jokic 65 inserted;
0 updated, 0 unchanged, 0 rejected**. No other player or season was imported.

Fresh read-only verification compared every imported row's normalized fields to
the approved source and retained its exact database ID/provider game ID in ignored
`fastnba-approved-execution-result.json`. Replay was preview-only: **0 new,
0 updated, 125 unchanged**. Total logs are **30,990**. After browser verification,
all 30,865 original logs (including all 372 ESPN NBA logs) and all other tables
still matched the pre-import content fingerprints. Players, Props, Events, odds,
users, saved props and slips were unchanged. Backup/sidecar remain intact.

Normal `app.main:app` and Next.js development frontend run on loopback ports
8000/3000 against the existing development database; refresh remains disabled.
An ignored launcher adds an outbound socket audit guard; **zero external backend
connection attempts** occurred. No fixtures or test API routes were used. Redis
was not started. Both player-only and exact retained Prop pages were checked in
the browser with `season=2025-26&competition=Regular%20Season`, including reload
retention. Four normal research API cases matched the retained source oracle.

| Player | Rows | L5 PTS / REB / AST / MIN | L10 PTS / REB / AST / MIN |
| --- | ---: | --- | --- |
| LeBron James | 60 | 23.0 / 6.6 / 9.2 / 29.2 | 19.9 / 7.2 / 9.1 / 32.0 |
| Nikola Jokic | 65 | 25.4 / 12.6 / 9.8 / 33.8 | 25.3 / 14.5 / 11.9 / 35.2 |

Every metric shows 5/5 and 10/10 valid samples. Both latest appearances are
April 12, 2026; coverage starts November 18, 2025 (LeBron) and October 23, 2025
(Jokic). NBA.com source and historical/noncurrent-form labels display correctly.
Neither player has an existing linked Event or actionable odds; retained legacy
Props show unavailable prices and unsupported team context stays unavailable.
The existing Cunningham Prop/Event API relationship also passed, with the expired
market remaining unavailable. Legacy line-based ESPN charts remain separate from
the NBA season summary. Authenticated save/slip mutations were not exercised;
their stored data was fingerprint-verified and selection behavior has focused tests.

Focused tests: **46 backend passed / 11 disposable-PostgreSQL cases skipped**
(no isolated test URL), **39 frontend passed**. Browser checks covered both players,
player-only/exact-Prop views and reloads. No executable application source changed,
so no full backend suite, production build or typecheck was rerun. UI screenshots,
API results and exact imported-row inventory are retained as ignored local artifacts.
Only this report and ignored verification files changed in this execution turn;
existing uncommitted work and protected reports were preserved. No commit/push,
deployment, migration, team-evidence changes or provider requests occurred.

Real NBA.com statistics now populate **2 of 21** local NBA players. The existing
workflow supports additional reviewed mappings; the remaining 19 need separately
authorized source coverage/imports, and Brunson's mapping remains unresolved.


## Remaining 18 players — collection approval checkpoint, October 19, 2026

Starting HEAD confirmed as `58018f28443b9cd1703cd07b61519a6b0e8e5572`.
Read-only PostgreSQL checks confirmed development `localhost:5432/proppulse`,
role `proppulse`, revision `20261018_04`, readiness `ready`, and refresh disabled.
All 18 selected UUIDs exist with the exact reviewed NBA names. No identity research
was repeated. Brunson remains unresolved and excluded; LeBron (2544) and Jokic
(203999) remain excluded. Current NBA.com coverage is still **2 players / 125 rows**
(60 LeBron, 65 Jokic); all selected players have zero NBA.com rows.

| Display name | Local Player UUID | NBA person ID | Mapping status | NBA.com rows |
| --- | --- | --- | --- | ---: |
| Anthony Davis | `LOCAL_PLAYER_ID_18` | 203076 | verified | 0 |
| Anthony Edwards | `LOCAL_PLAYER_ID_19` | 1630162 | verified | 0 |
| Bam Adebayo | `LOCAL_PLAYER_ID_20` | 1628389 | verified | 0 |
| Cade Cunningham | `LOCAL_CUNNINGHAM_PLAYER_ID` | 1630595 | verified | 0 |
| Damian Lillard | `LOCAL_PLAYER_ID_21` | 203081 | verified | 0 |
| Devin Booker | `LOCAL_PLAYER_ID_22` | 1626164 | verified | 0 |
| Donovan Mitchell | `LOCAL_PLAYER_ID_23` | 1628378 | verified | 0 |
| Giannis Antetokounmpo | `LOCAL_PLAYER_ID_24` | 203507 | verified | 0 |
| Ja Morant | `LOCAL_PLAYER_ID_25` | 1629630 | verified | 0 |
| Jayson Tatum | `LOCAL_TATUM_PLAYER_ID` | 1628369 | verified | 0 |
| Joel Embiid | `LOCAL_PLAYER_ID_26` | 203954 | verified | 0 |
| Kevin Durant | `LOCAL_PLAYER_ID_27` | 201142 | verified | 0 |
| Luka Doncic | `LOCAL_PLAYER_ID_28` | 1629029 | verified | 0 |
| Paolo Banchero | `LOCAL_PLAYER_ID_29` | 1631094 | verified | 0 |
| Shai Gilgeous-Alexander | `LOCAL_GILGEOUS_ALEXANDER_PLAYER_ID` | 1628983 | verified | 0 |
| Stephen Curry | `LOCAL_PLAYER_ID_30` | 201939 | verified | 0 |
| Tyrese Haliburton | `LOCAL_PLAYER_ID_31` | 1630169 | verified | 0 |
| Victor Wembanyama | `LOCAL_PLAYER_ID_32` | 1641705 | verified | 0 |

The ignored exact manifest is
`backend/data/odds_runs/5e/remaining-players/collection-manifest.json`.
Its collector plan SHA-256 is
`6f4733815f92dad69e42f57274200ac849165126655a013267337168f1905e79`.
Mapping file SHA-256 remains
`cbdbedce36b4d6553345cdb843950dcaedbc196837f832008fedbbcdbfd9da03`.
The manifest selects exactly these 18 UUIDs/NBA IDs, one GET per player, maximum
18 GETs to `https://stats.nba.com/stats/playergamelog`. Each request uses PlayerID
from the table plus Season=2025-26, SeasonType=Regular Season, LeagueID=00,
DateFrom=10/01/2025, DateTo=06/30/2026. Restrictions: ten-second request timeout,
zero retries, no redirects or proxies, at least two seconds after each completed
request including failures, no extra endpoints or provider requests. Proposed
exclusive output: `backend/data/odds_runs/5e/remaining-players/collected-responses.json`.
This proposal supersedes the older three-player proposal for this task.

A confirmed collector blocker was fixed minimally: failed requests previously
terminated the batch. The existing collector now records failures and continues,
preserves raw received bodies/status/UTC observations (including rejected HTTP or
malformed schema responses), and explicitly disables environmental/library proxies.
Successful payloads retain the existing importer envelope. No importer or application
logic changed. The later offline normalizer determines successful/empty/rejected
schema and identity outcomes; only eligible validated responses will be previewed.

Verification: collection tests **7 passed**, workflow tests **11 passed / 6 skipped**
(no disposable PostgreSQL test URL configured). All provider transports were mocked
in tests. Database inventory used PostgreSQL-enforced read-only connections.
Full regression, frontend/build/typecheck and browser checks were not run at this
checkpoint: the change is confined to the collection utility; import/application
verification awaits approved source data. Both protected reports retain their
preparation hashes in ignored `offline-preparation.json`.

**Approval pending:** authorized GETs **0**, attempted GETs **0**, collection outcomes
not yet available. No development writes occurred. Consolidated import preview,
artifact digest, import approval, execution/idempotency and application verification
remain pending collection approval. Collection approval will not authorize import.
Changes remain uncommitted; no push or deployment occurred.


## Authorized 18-GET collection and consolidated preview — October 19, 2026

The user approved plan `6f4733815f92dad69e42f57274200ac849165126655a013267337168f1905e79`.
Its exact collector digest, rebuilt plan, mapping digest and selected IDs were
reverified before execution. The existing collector ran once: **18 authorized /
18 actual GETs**, all **HTTP 200**, **16 populated / 2 empty / 0 failed / 0 rejected**.
Execution ran 21:02:51.414447–21:03:37.425259 UTC (5:02–5:03 p.m. Eastern).
Raw response bodies, HTTP status and UTC receipt times are retained. Each raw JSON
payload equals its corresponding importer payload. No source publication timestamp
was inferred. No other provider request was made. Ten-second timeout, no retries,
redirects or proxies, and two-second spacing remained enforced. Collection opened
no database. Actual request count is now also persisted by the existing collector.

Existing normalization validated **851 returned / 851 normalized games**, exact
reviewed UUID/NBA-ID associations from the preceding table, 2025-26 Regular Season,
October 1, 2025–June 30, 2026, and `nba_com:00225...` game identities. No duplicate
import identities or source/player/game-context conflicts were found. One combined
CLI default-mode preview succeeded against `localhost:5432/proppulse`, role
`proppulse`, with a maximum **851 rows**. Both empty responses remain in its exact
18-player scope but propose zero writes.

| Player | NBA ID | Returned | Valid | New | Updated | Unchanged | Rejected |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Anthony Davis | 203076 | 20 | 20 | 20 | 0 | 0 | 0 |
| Anthony Edwards | 1630162 | 61 | 61 | 61 | 0 | 0 | 0 |
| Bam Adebayo | 1628389 | 73 | 73 | 73 | 0 | 0 | 0 |
| Cade Cunningham | 1630595 | 64 | 64 | 64 | 0 | 0 | 0 |
| Damian Lillard | 203081 | 0 | 0 | 0 | 0 | 0 | 0 |
| Devin Booker | 1626164 | 64 | 64 | 64 | 0 | 0 | 0 |
| Donovan Mitchell | 1628378 | 70 | 70 | 70 | 0 | 0 | 0 |
| Giannis Antetokounmpo | 203507 | 36 | 36 | 36 | 0 | 0 | 0 |
| Ja Morant | 1629630 | 20 | 20 | 20 | 0 | 0 | 0 |
| Jayson Tatum | 1628369 | 16 | 16 | 16 | 0 | 0 | 0 |
| Joel Embiid | 203954 | 38 | 38 | 38 | 0 | 0 | 0 |
| Kevin Durant | 201142 | 78 | 78 | 78 | 0 | 0 | 0 |
| Luka Doncic | 1629029 | 64 | 64 | 64 | 0 | 0 | 0 |
| Paolo Banchero | 1631094 | 72 | 72 | 72 | 0 | 0 | 0 |
| Shai Gilgeous-Alexander | 1628983 | 68 | 68 | 68 | 0 | 0 | 0 |
| Stephen Curry | 201939 | 43 | 43 | 43 | 0 | 0 | 0 |
| Tyrese Haliburton | 1630169 | 0 | 0 | 0 | 0 | 0 | 0 |
| Victor Wembanyama | 1641705 | 64 | 64 | 64 | 0 | 0 | 0 |

**Totals: 851 returned / 851 valid / 851 new / 0 updated / 0 unchanged / 0 rejected.**
Lillard and Haliburton returned empty source results; no games or participation
explanations were fabricated. No selected player failed or was excluded from the
preview. LeBron, Jokic and unresolved Brunson remain excluded from the import.

Ignored artifacts under `backend/data/odds_runs/5e/remaining-players/`:

- Original collection: `collected-responses.json`, SHA-256
  `1220520c576ce16a446a1e3dd75393498efda7dee454edc6af09680fc38545e5`.
- Import artifact: `validated-import-artifact.json`, SHA-256
  `b8f0a7be1e1d92a44da1658f910a64248acaaaea943b20b00bab961d54ecc848`.
  All 18 response objects exactly equal the original collected responses; the
  envelope additionally references the original artifact digest.
- Mapping: `backend/data/nba_player_mappings.json`, unchanged SHA-256
  `cbdbedce36b4d6553345cdb843950dcaedbc196837f832008fedbbcdbfd9da03`.
- Exact approval: `proposed-import-approval.json`, SHA-256
  `3cd6c2d4fb9b0c59cfa439149928d3923f14660c851bf599b8203560ddf8eed1`.
- Detailed results: `collection-result.json`, `validation-and-preview.json`,
  `import-preview.stdout.json`; before/after aggregate content fingerprints are
  retained locally and contain no displayed personal records.

Post-preview PostgreSQL-enforced read-only verification confirmed revision04/ready
and exact content-fingerprint equality for **all 15 tables** against the immediate
pre-collection baseline, including all 30,990 game logs, original ESPN history,
LeBron/Jokic and all Player/Prop/Event/odds/user/saved/slip data. No development
import or application-data write occurred. Real application coverage therefore
remains **2 players / 125 NBA.com rows**. If the previewed import succeeds, it would
reach **18 populated verified players / 976 rows**, with two verified players still
empty and Brunson unresolved; this is a projection, not completed coverage.

**Separate development import approval is pending:** approve exactly the 18 UUIDs
and NBA IDs in the preceding mapping table, target role/database above, the import
artifact/mapping digests above, 2025-26 Regular Season and specified dates, maximum
851 rows, all new. Execution must use the existing importer with the exact
`proposed-import-approval.json`; it locks selected Players, checks all identities
and source/game contexts, and writes only PlayerGameLog. Per-player savepoints sit
inside one outer transaction; failure rolls back the whole batch. No post-commit
restore or rollback is automatic or authorized. Player mappings, team evidence and
all unrelated tables remain outside the write scope.

Collection tests **7 passed**, including actual transport count; real artifacts
passed normalization and the one combined read-only preview. No additional full
regression/build/typecheck run was warranted by the request-count metadata change.
Import integrity/idempotency and representative normal research API/browser checks
remain pending the separately approved import. Protected untracked report hashes
remain unchanged. Only collector/tests/this report are modified; artifacts remain
ignored, with no commit, push or deployment.


## Authorized 851-row import completed — October 19, 2026

The user separately approved the exact 851-row import. Before executing, all three
authorized artifact/mapping hashes, the exact approval-file hash/content, raw/import
payload equality, development target/role, revision04/readiness and refresh-disabled
settings were reconfirmed. All 15 table fingerprints still matched the pre-collection
baseline. A fresh read-only preview exactly matched every approved per-player count.
The existing approval-based CLI ran **once**, committing **851 new / 0 updated /
0 unchanged / 0 rejected** rows in one outer transaction. Per-player additions match
the preceding collection/preview table; Lillard/Haliburton each added zero.

Every inserted row matches its normalized approved source, including exact
player/game identity and historical scope. Fresh read-only replay returned **0 new /
0 updated / 851 unchanged**. Excluding the 851 verified new row IDs, all **30,990**
original game logs match their original aggregate content fingerprint, preserving
ESPN history and all LeBron/Jokic rows. All 14 other tables match their original
fingerprints, including Player, Prop, Event, odds, users, saved/slip data, schema
marker and team evidence. No mapping write, evidence write or migration ran.

Actual NBA.com coverage is **976 rows / 18 populated players**, comprising the two
original players plus 16 newly populated players. This is **18 of 20 verified
mappings / 18 of 21 local NBA Players**. Damian Lillard and Tyrese Haliburton have
no NBA.com rows because their approved responses were empty; Jalen Brunson remains
unresolved and excluded. Total PlayerGameLog rows are **31,841**.

Normal API checks against the running local app passed for all 18 selected players,
including exact retained Prop UUIDs; both linked Cade/Tatum Event associations and
the canonical `/props/game` response retained their identities. L5/L10 PTS, REB,
AST and MIN were independently calculated directly from the original response
columns and matched every populated player's API output. Empty players return
unavailable averages and zero samples. Browser checks covered player-only Cade,
Tatum, Shai and Wembanyama, Cade's exact Prop and reload retention, the canonical
Celtics/Pistons Event page, and both empty players. Historical 2025-26 labels,
Regular Season and NBA.com source appeared correctly on populated summaries.

| Player | Rows | L5 PTS / REB / AST / MIN | L10 PTS / REB / AST / MIN |
| --- | ---: | --- | --- |
| Cade Cunningham | 64 | 14.6 / 4.0 / 8.0 / 23.6 | 17.1 / 4.1 / 10.1 / 27.6 |
| Jayson Tatum | 16 | 23.6 / 12.0 / 7.8 / 36.2 | 22.4 / 10.9 / 6.1 / 34.6 |
| Shai Gilgeous-Alexander | 68 | 28.0 / 3.6 / 7.2 / 30.6 | 29.0 / 3.3 / 6.5 / 31.7 |
| Victor Wembanyama | 64 | 34.6 / 14.0 / 4.0 / 28.2 | 29.5 / 13.5 / 4.0 / 28.6 |

All displayed representative metrics have **5/5 and 10/10 valid samples**. Source
receipt times display in Eastern time. Linked Prop/Event scope remains exact;
expired/missing prices and unsupported recent team/rest evidence stay unavailable.
Selecting the upcoming Event changes the rest reference date, while historical
averages remain unchanged. Legacy ESPN line-based charts retain their separately
labeled scope. Empty-player UI correctly says season statistics unavailable and
shows its existing ESPN fallback notes; it does not claim imported NBA.com coverage.

Focused checks: **46 backend passed / 11 disposable-PostgreSQL cases skipped**
(no isolated test URL), **27 frontend passed**. Real development verification used
read-only queries and the normal running API/browser, not a test fixture app.
No full regression, production build or typecheck was rerun: no executable
application source changed in this import turn. Authenticated save/slip mutations
were not exercised; stored data was fingerprint-verified unchanged. No new services
were started and no additional provider request, push or deployment occurred.

Ignored artifacts in `backend/data/odds_runs/5e/remaining-players/` retain the fresh
preview, CLI execution result, exact imported-row inventory, preservation/replay,
normal API results and browser verification record. A local report serialization
error occurred after successful commit and verification because a coverage UUID
was not JSON serializable; only reporting was corrected and verification rerun
read-only. The import was not repeated. Protected untracked report hashes remain
unchanged. Source changes remain uncommitted.
