# Milestone 4A.3 — ESPN NBA contract audit and adapter preparation

## Scope, baseline and evidence limits

Starting HEAD: `c72c86473b0a3347cf0ae91e7e31142b9c1dec86`, initially clean.
Parent/application AGENTS and the Phase 4A, verified participation, 4A.2,
ingestion reliability, Event schema/ingestion/API, and readiness reports were
reviewed with the current source. This work prepares an explicitly invoked
read-only contract collector and a versioned offline audit adapter. It does not
activate participation ingestion or change research calculations/public contracts.

**No live provider request or development PostgreSQL access occurred.** No
previously authorized retained scoreboard, summary or box-score examples were
supplied. Ignored provider artifacts and environment secrets were not inspected.
Checked-in synthetic examples are test fixtures, not independently verified ESPN
payloads. Live NBA data coverage and model accuracy remain unmeasured.

## Existing integration audit

The existing `fetch_player_game_logs.py` loads environment files and imports the
application engine; it is not a safe contract-collection entry point and was not
executed. The new collector imports neither it, application settings, database
modules, ingestion scripts nor the application lifespan.

| Repository-used endpoint | Fields already consumed | What this actually establishes |
| --- | --- | --- |
| `https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams` | `sports[0].leagues[0].teams[].team.id`, `displayName`/`name`, `abbreviation` | Team-directory candidates. Not a complete schedule or historical team assignment. |
| Same base + `/teams/{team_id}/roster` | `athletes[]`, optionally nested `items[]`, `id`, `displayName`/`fullName` | Current roster candidates at receipt time; no dated historical membership or local Player UUID proof. |
| `https://sports.core.api.espn.com/v3/sports/basketball/nba/athletes` | `items[]`, athlete `id`, `displayName`/`fullName`, `pageCount`; requests `limit=1000`, `active=true`, explicit page | Existing discovery loops up to 20 pages. Active-current roster discovery is not a complete historical participant census. |
| `https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{athlete_id}/gamelog` | `names`, `events[eventId].gameDate`, `opponent.displayName`, `atVs`, `seasonTypes[].categories[].events[]`, `eventId`, `stats` | Retained game-log observations under current code assumptions, not finality or explicit appearance/DNP proof. Requests include region/lang/contentorigin/season. |

`team_directory.py` and `player_matching.py` preserve display-name collisions
rather than choosing an arbitrary match. Game-log ingestion uses matching and
current-roster team correction; it does not retain an audited historical athlete
crosswalk or effective membership interval. NBA ingestion skips missing/nonpositive
minutes. Zero points can describe an appearance; missing minutes can coexist with
other observations. Neither statistic is a verified participation classification.
The generic athlete-details request in history ingestion is used for NFL position
fallback, not an implemented NBA participation pathway.

Repository-used fields are **source-code audited**, not independently revalidated
against live ESPN. No unknown response field or enum is treated as verified.

## Unresolved upstream requirements

| Needed fact | Current status / required evidence |
| --- | --- |
| Unique NBA game identity and actual date | Game-log IDs/dates are observed candidates. Need consistency across independently retained scoreboard/summary/box-score examples and timezone semantics. |
| Final versus unfinished | Unverified. Need actual provider fields/enums, completion semantics, corrections, and observation chronology. Past scheduled start or nonempty statistics is insufficient. |
| Postponed/cancelled/rescheduled | Unverified. Need original/new dates, preserved provider identity, explicit statuses, and changes over repeated observations. |
| Home/away provider team IDs | Existing team directory IDs exist; game participant-side fields remain unverified. Event labels cannot supply the crosswalk. |
| Athlete identity and actual appearance | Candidate athlete IDs exist. Need game-specific explicit participation evidence, including zero-point, missing-minute and overtime examples. |
| DNP and inactive | No verified provider classification or inclusion/omission semantics. A missing player must remain unknown. |
| Complete box score | Need actual roster/participant list definitions, partial/live responses, paging/truncation and omitted-player cases. HTTP 200 does not prove completeness. |
| Historical team membership/trades | Current roster snapshots cannot create effective history. Need dated, independently supported game/team/athlete associations and interval rules. |
| Complete schedule | Neither Event inventory nor known game logs is complete. Need independently reconciled date/team inventory, pagination, postponed/cancelled coverage and gaps. |
| Provider update timestamps | Unknown for unsupported payloads. Collector receipt UTC is observation provenance, not provider update/completion time. |

Scoreboard and summary endpoints in the plan are **proposed contract-audit
targets**, not validated parsers:

- `https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=YYYYMMDD`
- `https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={approved_game_id}`

Their routing and response semantics still require the separately authorized
read-only audit. No body field or status enum from them is invented here.

## Collector design and collection authorization

`espn_contract_collection.py` and `collect_espn_contracts.py` prepare a fixed-host,
fixed-route, NBA-only plan. Dry-run is the default: no HTTP, PostgreSQL connection,
directory creation or provider-response retention. Execution requires a separate
explicit authorization and the exact reviewed plan digest. Environment variables,
an execution flag alone, or an endpoint response cannot grant authorization.

All dates, team/game IDs, endpoint allowlist, request budget, minimum delay,
retry count, output directory and redaction policy are explicit. There is no
automatic discovery/backfill or response-link/pagination following. The hard
bounds are 1–14 inclusive dates, 1–2 numeric team IDs, 1–8 numeric game IDs,
1–32 attempts, a 1–60 second minimum delay and 0–2 retries per planned GET.
Every plan requires both team and game ID scope, even for a league-wide endpoint.
The CLI requires those IDs, budget, delay, retries, redaction policy, dates,
endpoints, NBA sport and an absolute local fresh output directory explicitly.
Each attempt, including retries, consumes the same finite request budget.
Redirects and ambient proxy configuration are disabled. No paid odds host,
credentials or application refresh integration is permitted. Transport/HTTP errors
produce bounded audit outcomes rather than fabricated empty coverage.

Each response has a 2,000,000-byte cap, 10-second HTTPX timeout and an elapsed
stream deadline. Safe connect/read timeouts, connect errors and 5xx may retry
within the explicit budget; redirects, 429, other 4xx, malformed/partial JSON,
duplicate JSON keys, nonfinite numbers, oversized data and output errors stop.
No response links or pagination claims expand the plan. HTTP 200/collection
completion never establishes NBA schedule or box-score completeness.
Requests explicitly ask for `Accept-Encoding: identity`. Nonidentity content
encoding is rejected before body reads or HTTPX decompression, preventing a small
compressed response from allocating a large decoded buffer before the byte check.
Cookies are cleared before and after every attempt; server cookies cannot carry
credentials into the next request. Response headers and exception bodies are not
retained or echoed.

Collection produces redacted JSON plus per-attempt outcome/time/hash provenance.
It never writes to PostgreSQL or invokes the evidence reconciler. Public sports
identities may be retained; secrets, auth/cookie/header content, private contact
information and private personal fields must be removed according to the explicit
policy. Unsupported or unredactable responses must not be retained as raw text.
Redaction can remove fields needed for later semantics; removed values are not
reconstructed. Output is exclusively created, never overwritten, and linked/
reparse paths are rejected. `backend/data/espn_contract_audit/` is Git-ignored for
future authorized collections; no actual collection is created by this milestone.
The parent directory must already exist; creating a retention parent is a separate
explicit preparation step, not an effect of dry-run. Use an owner-controlled
directory rather than one writable by untrusted local processes.
Redaction uses known sensitive keys and string patterns; without actual authorized
provider samples it is not proof that every unknown field is free of private data.
The authorization must include restricted local retention and human review before
sharing or checking any redacted examples into source control. Expand the policy
when that review discovers new sensitive fields; do not claim raw-response fidelity.

The declared team/game scope bounds roster/summary requests. A day scoreboard or
teams-directory response may cover other public teams: without verified body or
filter contracts, the collector cannot claim provider-side team filtering or
independently validate a requested game's team/date membership. Approval must
explicitly permit these bounded public endpoint responses. Their presence does
not authorize additional requests or automatic evidence ingestion.

## Example dry-run plan

The following is schematic; placeholders are intentionally invalid provider IDs.
Replace them only with independently supplied, explicitly approved IDs. Neither
the dates nor an odds Event implies that any selected game belongs to these teams.
The command has **no execution flag** and cannot collect a provider response:

```powershell
python scripts/collect_espn_contracts.py --sport NBA `
  --start-date 2026-10-15 --end-date 2026-10-16 `
  --team-id APPROVED_TEAM_1 --team-id APPROVED_TEAM_2 `
  --game-id APPROVED_GAME_1 --game-id APPROVED_GAME_2 `
  --game-id APPROVED_GAME_3 --game-id APPROVED_GAME_4 `
  --endpoint scoreboard --endpoint roster --endpoint summary `
  --request-budget 16 --min-delay-seconds 2 --max-retries 1 `
  --redaction-policy credentials_and_private_pii_v1 `
  --outdir C:\AUTHORIZED_PARENT\espn-contract-run-001
```

After valid replacements, dry-run prints a plan shaped as follows (URLs/digest
are generated from the exact validated values; no free-form URL is accepted):

```json
{
  "mode": "dry_run",
  "provider": "espn",
  "sport": "NBA",
  "scope": {
    "start_date": "2026-10-15", "end_date": "2026-10-16",
    "team_ids": ["<approved-team-1>", "<approved-team-2>"],
    "game_ids": ["<approved-game-1>", "<approved-game-2>", "<approved-game-3>", "<approved-game-4>"],
    "endpoints": ["roster", "scoreboard", "summary"]
  },
  "limits": {
    "request_budget": 16, "max_retries": 1, "min_delay_seconds": 2.0,
    "timeout_seconds": 10, "max_response_bytes": 2000000
  },
  "requests": [
    {"endpoint": "roster", "scope_id": "<approved-team-1>", "url": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/<approved-team-1>/roster", "contract_status": "repository_used"},
    {"endpoint": "roster", "scope_id": "<approved-team-2>", "url": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/<approved-team-2>/roster", "contract_status": "repository_used"},
    {"endpoint": "scoreboard", "scope_id": "2026-10-15", "url": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=20261015", "contract_status": "unverified_contract_audit"},
    {"endpoint": "scoreboard", "scope_id": "2026-10-16", "url": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=20261016", "contract_status": "unverified_contract_audit"},
    {"endpoint": "summary", "scope_id": "<approved-game-1>", "url": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event=<approved-game-1>", "contract_status": "unverified_contract_audit"},
    {"endpoint": "summary", "scope_id": "<approved-game-2>", "url": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event=<approved-game-2>", "contract_status": "unverified_contract_audit"},
    {"endpoint": "summary", "scope_id": "<approved-game-3>", "url": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event=<approved-game-3>", "contract_status": "unverified_contract_audit"},
    {"endpoint": "summary", "scope_id": "<approved-game-4>", "url": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event=<approved-game-4>", "contract_status": "unverified_contract_audit"}
  ],
  "output_dir": "<approved fresh absolute directory>",
  "redaction_policy": "credentials_and_private_pii_v1",
  "plan_sha256": "<digest of the exact emitted plan>"
}
```

Separate execution requires `--execute`, the exact authorization phrase
`AUTHORIZE BOUNDED ESPN NBA CONTRACT COLLECTION`, and
`--reviewed-plan-sha256` matching the reviewed plan. Merely knowing the phrase
does not grant permission: the human must separately authorize that exact plan,
scope, endpoint exposure and retention location. This milestone does not do so.

## Versioned audit adapter and durable evidence boundary

`espn_nba_contract_adapter.audit_collected_response` accepts a version-1 collector
envelope and returns `espn-nba-contract-audit-v1`. It validates explicit receipt
time, bounded finite JSON, repository-used structural collections, numeric provider
identity candidates and timezone-aware game-date candidates. It reports malformed
identities, dates/statistic columns and uncertain pagination. Duplicate observations
remain separate; payload hashes preserve provenance. Raw payloads are not echoed.

Supported audit outputs are team-ID candidates, athlete-ID candidates, current
roster observations and game-log ID/date observations. These are **not** the six
durable evidence record kinds. There are no local Player UUID assignments, Event
links, DNPs, membership intervals or completeness assertions. Summary/scoreboard
bodies are intentionally opaque. The adapter always returns:

```json
{
  "adapter_version": "espn-nba-contract-audit-v1",
  "contract_status": "awaiting_upstream_contract_validation",
  "evidence_records": [],
  "safe_to_reconcile": false,
  "verified": {
    "final_status": null,
    "appearance": null,
    "dnp": null,
    "inactive": null,
    "boxscore_complete": null,
    "schedule_complete": null,
    "historical_membership": null
  }
}
```

**Unsupported mapping stops here.** There is insufficient independent upstream
evidence to promote any provider response into trustworthy game/participation/
membership/coverage records. Even plausible-looking status fields cannot bypass
this boundary. A future reviewed adapter can reuse revision `20261017_03` and
`reconcile_fixture`'s existing internal six-kind contract after establishing actual
source semantics and a separately authorized write path. No competing reconciler,
table, migration or automatic schema-readiness change is introduced.

## Synthetic fixture validation

Tests explicitly label the examples synthetic. Repository-shape fixtures exercise
zero points, missing minutes, absent identity/time, timezone conversion, duplicate
observations, changing roster team context, missing players and pagination. Internal
scenario labels (not ESPN field names) cover final/unfinished, explicit appearance,
DNP/inactive, trades, postponed/cancelled, partial response and conflicting status;
every unsupported scenario remains unknown and emits zero durable records.

Disposable PostgreSQL tests demonstrate that an unverified audit leaves research
unknown and preserves the exact selected Prop/Event UUIDs. Separately, the existing
27-record synthetic six-kind fixture is reconciled/replayed through the existing
service and still produces two confirmed missed games without duplicating records.
That arithmetic test validates internal integration, not an ESPN response contract.

## Verification and changed files

No frontend, production API, calculator, statistical history, odds, Discover,
saved/slip or Event identity code changed. The database model, revision
`20261017_03`, readiness service and reconciler remain unchanged.

Changed files:

- `.gitignore` — exclude future authorized contract-retention artifacts.
- `backend/app/services/espn_contract_collection.py` — bounded planner, separately
  authorized read-only executor, strict parsing and redacted audit artifacts.
- `backend/scripts/collect_espn_contracts.py` — plan-only default CLI.
- `backend/app/services/espn_nba_contract_adapter.py` — versioned audit-only adapter.
- `backend/tests/test_espn_contract_collection.py` — mocked collection safeguards.
- `backend/tests/test_espn_nba_contract_adapter.py` — synthetic audit and isolated
  PostgreSQL bridge tests.
- `docs/milestone-4a3-espn-contract-validation.md` — audit, scope and limitations.

Independent review verified the authorization/digest gates, scope/budget checks,
redaction, transport and output-path restrictions, and the adapter's zero-evidence
boundary. Review found and corrected an HTTPX decompression-before-size-check
bypass: compressed responses now fail before any body read. A trap-stream test
covers gzip/br/deflate without reading or decompressing bytes. Explicit team/game
scope and CLI delay/retry/redaction options are required for every plan.

Fresh checks already executed:

| Check | Actual result |
| --- | --- |
| Collector focused tests | **35 passed**, MockTransport only; zero external HTTP attempts. |
| Audit adapter and PostgreSQL bridge | **18 passed**, including **2 PostgreSQL**, zero skips/HTTP attempts. |
| Full backend with provider HTTP blocked | **789 passed**, including **216 PostgreSQL scenarios**, no failures/skips, 125.514 seconds; **zero external HTTP transport attempts**. |
| Frontend unit / TypeScript | **68 passed** / passed. |
| Mocked Chrome | **26 desktop + 26 mobile = 52 passed**, exit 0. |
| Real-backend Chrome | **16 desktop + 16 mobile = 32 passed**, exit 0. |
| API fixture preservation | All **14 tables / 115 rows** retained identical counts and SHA-256; **zero provider HTTP attempts**. |
| Ordinary uncached production build | Failed fetching Google Inter with network `EACCES`. |
| Temporary font-mocked build | Passed, ten pages; genuine Inter rendering remains unverified. |
| Python compilation / whitespace | Passed. |

A separate actual CLI **dry-run only**, using clearly synthetic IDs, produced
eight planned GETs and a 16-attempt budget, created no output directory and made
no requests. Its receipt is a planning test, not authorization to collect those IDs.

PostgreSQL verification uses only cached PostgreSQL **15.18** in the new owned container
`proppulse-test-4a3`, ID
`3dcd9b0c28f88f59de4305d5101ab74f0aeea5f3f1769805865c7c4c2b2c3742`,
loopback **55491**, tmpfs data, no mounts, 512 MiB/one CPU/128 PID limits.
Backend random schemas use `proppulse_test_4a3`; real browser tests use a separate
initially empty `proppulse_test_4a3_browser`, with database-enforced read-only
research, disabled lifespan, blank provider keys and refresh off. Test transport
fixtures are explicitly mocked; no live ESPN/NBA/Odds request occurred.
Owned API/Next processes were stopped, generated reports/screenshots/logs were
removed, and the disposable PostgreSQL container was removed after checking its
exact ID/name/test label, tmpfs/no-mount configuration and loopback port. The final
implementation working tree contained only the seven listed changes, all
unstaged/uncommitted; HEAD remained the starting checkpoint. The subsequently
authorized local Git checkpoint is recorded below.

The ordinary Google-font build remains an environment limitation. Font-mocked
rendering and synthetic contract tests do not establish release readiness or live
participation accuracy. The implementation stopped before committing. No push,
operational migration, backfill, automatic refresh, deployment or Phase 4B work
was performed.

## Proposed bounded live-read validation — not executed

1. The human authorizes exact NBA dates, up to two independently identified team
   IDs and up to four independently identified game IDs. No IDs are invented or
   inferred from existing odds Events/current player names. Select representative
   historical completed and incomplete/cancelled/postponed cases where available;
   a small initial set cannot be claimed exhaustive.
2. Approve only scoreboard for two dates, roster for those two teams and summary
   for those four game IDs: **eight planned GETs**, maximum **16 attempts** including
   at most **one retry per GET**, minimum **two seconds** between every attempt,
   fixed timeout/byte bounds, no pagination/redirects or new endpoint discovery.
3. Approve a fresh unique absolute output directory under the ignored contract
   audit directory and the explicit redaction/retention policy. Generate the dry-run
   plan, review every URL and its declared/unknown scope, and retain its digest.
4. Only after separate explicit execution authorization, execute exactly that
   reviewed plan once. Stop on exhausted budget, unsupported payloads or unsafe
   failures. Review the redacted response artifacts and attempt manifest offline;
   record actual missing/partial coverage and unresolved contracts.
5. Add deterministic redacted examples and source-to-normalized mapping tests
   only after review. Separately authorize any durable writes/live validation or
   operational migration/deployment. Do not infer missing participation or
   manufacture schedule completeness. No collection or ingestion is performed
   by the current request.

## Final security review and local Git checkpoint — October 18, 2026

Starting HEAD remains `c72c86473b0a3347cf0ae91e7e31142b9c1dec86`. Git confirmed
exactly the seven listed source/test/documentation changes. Parent/application
instructions, prior reports, the complete diff, provider assumptions and evidence
boundary were reviewed. No live collection was authorized or executed.

Fresh review confirmed and corrected these defects within the same seven files:

- The elapsed deadline was checked before response chunks but not after EOF.
  A valid final chunk followed by a delayed EOF could incorrectly be retained.
  The collector now rechecks the deadline before parsing or writing the response.
- Handled interruptions or unexpected failures could leave earlier redacted
  artifacts without the final attempt audit. The collector now writes a
  best-effort sanitized `interrupted`/`failed` manifest, preserves attempt counts
  and successful artifacts, stops without retries and reraises the original error.
  Interruption during the inter-request delay does not count an unissued request.
- Failed/interrupted exclusive writes could leave partial files; a failed
  `fdopen` could also leak its raw descriptor. Ownership-aware cleanup now closes
  descriptors and removes only the file created by that invocation, checking file
  identity before unlinking. Existing/replaced paths are never intentionally erased.
- CLI `SystemExit` and unexpected failures could expose private exception text.
  The execution path now returns sanitized nonzero JSON outcomes; KeyboardInterrupt
  returns 130. Argument-parser exits remain outside this execution handler.

Eight new mocked regressions cover these failure paths, bringing the collector
suite to **43 tests**. Existing authorization/digest/route restrictions, request
budgets, delays, strict JSON, compression rejection and output no-overwrite/path
guards remain intact. Independent review found no remaining confirmed defect.

Audit persistence is best-effort when a volume is unavailable; an audit-write
failure never masks the original interruption. A hard process kill, machine loss
or unavailable filesystem cannot guarantee a final manifest. There is no automatic
resume or additional collection authorization in that state. Unknown response
contracts still cannot emit durable evidence, and neither collection success nor
an HTTP 200 establishes completeness.

Fresh verification uses only cached PostgreSQL **15.18** in owned container
`proppulse-test-4a3-checkpoint`, ID
`9ccee54d3a60eaea04c566261fb7af12cc9a72c4f49a788c06ea1317937f09fd`,
loopback **52325**, tmpfs/no data mounts, 512 MiB/one CPU/128 PID limits.
Backend random schemas use `proppulse_test_4a3_checkpoint`; real browser tests use
the separate initially empty `proppulse_test_4a3_checkpoint_browser`. Provider
keys are blank, refresh disabled, real API lifespan disabled, HTTP transports
blocked and research database sessions enforced read-only. Development PostgreSQL
and real ESPN/NBA/Odds endpoints were not accessed.

| Fresh final check | Actual result |
| --- | --- |
| Full backend, external provider HTTP blocked | **797 passed**, including **216 PostgreSQL scenarios**, no failures/skips, 125.918 seconds; **zero external HTTP transport attempts**. |
| Collector transport/authorization/failure regressions | **43 passed**, zero HTTP attempts. |
| Audit adapter / evidence bridge | **18 passed**, including **2 PostgreSQL**, zero skips/HTTP attempts. |
| Frontend unit / TypeScript | **68 passed** / passed. |
| Mocked Chrome desktop/mobile | **26 + 26 = 52 passed**, exit 0. |
| Real-backend Chrome desktop/mobile | **16 + 16 = 32 passed**, exit 0. |
| Database preservation | All **14 tables / 115 fixture rows** unchanged by count and SHA-256; **zero provider HTTP attempts**. |
| Normal uncached production build | Google Inter fetch fails with network `EACCES`. |
| Temporary font-mocked production build | Passed, ten pages; genuine Inter rendering remains unverified. |
| Python compilation / whitespace / artifact review | Passed; only the seven reviewed files are included. |

The local commit is authorized as
`feat: add bounded ESPN contract collector and audit adapter`. No provider
responses, audit outputs, environment secrets, generated manifests/logs/screenshots,
database files or font mocks belong to its manifest. The normal-build environment
limitation is accepted for this local checkpoint only; release readiness is not
claimed. Separately authorized live-read validation still requires the exact
scope, reviewed plan/digest and restricted retention/human review described above.
Final, DNP/inactive, historical-membership and completeness contracts remain
unverified; no next milestone or live collection starts with this checkpoint.

Owned API/Next processes were stopped and generated browser outputs/test logs were
removed. After checking the exact container ID/name/test label, tmpfs/no-mount
configuration and loopback port, the disposable PostgreSQL container was removed.
The staged manifest contains exactly the seven reviewed files and excludes all
provider payloads, audit outputs, credentials, database and build artifacts.
