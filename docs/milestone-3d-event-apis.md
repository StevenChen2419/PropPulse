# Milestone 3D: Event APIs and explicit Prop research selection

Implemented October 15, 2026 from clean HEAD
`468ccd2f76bb2af47b33ca09d281106afd2b45b7`. Parent/application AGENTS,
Milestone 1 offer availability, Milestone 2 reliability/PostgreSQL, Phase 3A
matching/history/PostgreSQL, Phase 3B schema, and Phase 3C ingestion/bounded
linkage reports informed this change. Current source and callers were audited.

The supplied development baseline (one Event, ten linked props, 6,054 unlinked
props, revision `20261014_02`) was **not remeasured or connected to**. No
development mutation, provider request, ingestion, Event backfill, new migration,
configuration change, commit, or push is part of this implementation.

## Contract audit and compatibility decision

| Endpoint before 3D | Identity and selection before 3D | Change |
| --- | --- | --- |
| `GET /props/games?sport=&limit=` | Eligible future props grouped using Player.team, Prop.opponent/is_home/game_time; object with games/total/refreshed_at | Group linked props by Event UUID; retain object and count fields |
| `GET /props/todays-games?sport=&limit=` | Same upcoming inventory, bare array; no local-date restriction | Preserve upcoming semantics and bare array |
| `GET /props/game?game_key=` | Parsed derived key, delegated to Feed; 404 when no eligible props | Add `event_id`, optional `sport`; known Events return empty metadata detail |
| `GET /props/feed?game_key=&sport=&prop_type=&limit=&offset=` | Recomputed per-prop key after eligible-offer filtering | Add `event_id`; resolve legacy identities before availability filtering |
| `GET /props/discover?game_key=&sport=&prop_type=&limit=&offset=` | Same derived-key filtering plus history/scoring gate | Add `event_id`; retain scoring, samples, and pagination |
| `GET /players/{player_id}/research?prop_type=&line=` | First live market/line match, ordered by game time/market/line; no unavailable selection | Add `prop_id`; reject ambiguous legacy selectors; retain explicit unavailable subjects/history |

The frontend client used `/todays-games`, string game keys, and market/line
research queries. Its existing calls still compile. Additive client parameters
and optional TypeScript identity fields prepare migration; no visual, navigation,
authentication, persistence, or store workflow was redesigned.

## Authoritative context and grouping

`game_identity_service.py` owns read-only Event context, effective schedule,
coarse SQL schedule filtering, legacy context, ambiguity detection, and selector
resolution. It never creates or links an Event. A linked prop resolves its FK
relationship and uses Event.home_team, away_team, sport_key, scheduled_start_at,
provider and opaque provider_event_id. Event.id is the canonical identity.

Both teams and all markets produce one card per Event UUID. Different providers,
sports, or dates remain separate Events. Mutable Player.team, legacy opponents,
home flags and stale/null Prop.game_time cannot split or redefine a linked Event.
The SQL schedule prefilter, final offer policy, display context, ordering and
history cutoff use the Event schedule for linked props. Schedule corrections do
not change the UUID or refresh odds. Event schedules can stop offers at game start;
they cannot overcome expired observations or other eligibility failures.

Game lists continue to show **eligible upcoming inventory**, so an Event with no
eligible props is absent from those lists. Its UUID detail remains addressable.
Event presence alone never manufactures an offer. Source labels still describe
offer freshness, not identity verification.

## Response context

Games, Game Detail, Feed, Discover and research props expose these additive fields:

```json
{
  "event_id": "LOCAL_EVENT_ID",
  "identity_source": "authoritative",
  "provider": "the_odds_api",
  "provider_event_id": "26b036ff107f3c658258eaf4a6f26228",
  "sport_key": "basketball_nba",
  "sport": "NBA",
  "away_team": "Boston Celtics",
  "home_team": "Detroit Pistons",
  "scheduled_start_at": "2026-10-20T19:00:00+00:00",
  "game_time": "2026-10-20T19:00:00+00:00",
  "game_key": "NBA|2026-10-20T19:00:00|Boston Celtics|Detroit Pistons"
}
```

This illustrates the supplied identity, not a fresh development API/availability
observation. Props retain their `id`, market, current line, sportsbook, nullable
prices, best equivalent-line prices, explicit offers, and freshness timestamps.
`odds_event_id` remains a compatibility field in Feed. Existing raw `opponent`,
`is_home`, and nested Player.team fields are compatibility/player data; consumers
must use the authoritative participant fields for the game header. They do not
prove a player's historical side. Research suppresses an opponent split when its
stored opponent conflicts with both Event participants, without guessing a side.
Shared serialization also adds context to saved/slip prop reads; their stored
prop IDs, sportsbook, side and selected line are never rewritten.

Game cards add `has_eligible_props: true`, preserve `prop_count`, and `/games`
preserves `available_props`/`fallback_used`. Detail uses `total_props` and
`has_eligible_props`. `schemas.py` adds the reusable Pydantic identity contract
and includes it in PropOut; routers retain their existing dictionary conventions.

## Event detail, filtering and errors

Canonical requests:

```text
GET /props/game?event_id=<uuid>
GET /props/feed?event_id=<uuid>
GET /props/discover?event_id=<uuid>
```

Filtering uses `Prop.event_id`, never matching names/timestamps or including
unlinked rows. Feed and Discover preserve their other market/sport restrictions,
offer eligibility and exact-line comparison. Discover keeps its existing minimum
five current-season decisions and unchanged scoring weights. Feed preserves its
existing unpaginated behavior for a game-specific query, including Event UUID
queries; ordinary Feed uses limit/offset. Discover remains paginated.

| Condition | Result |
| --- | --- |
| Known Event with eligible props | 200 metadata and currently eligible props |
| Known Event without eligible props (including no props at all) | Detail 200, `props: []`, `total_props: 0`, `has_eligible_props: false`, `actionable: false`, `source: unavailable`, `availability: market_unavailable`; Feed/Discover return empty lists |
| Unknown Event UUID | 404 for Detail, Feed and Discover |
| Malformed Event UUID | FastAPI 422 |
| Event disagrees with supplied sport | 400 |
| Both `event_id` and `game_key`, even if apparently consistent | 400; no precedence/fallback |
| Detail without either selector | 400 |
| Malformed legacy key or timestamp | 400 |
| Unknown/stale legacy key | 404; Feed/Discover formerly returned an empty list for a nonmatching key |
| Ambiguous legacy key | 409; no arbitrary Event choice |
| Unambiguous legacy game with no eligible props | Detail retains 404; Feed/Discover return empty lists |

Existence and ambiguity resolution include stored unavailable/inactive records
and empty Events. Expiration therefore cannot resolve an identity collision by
silently choosing the remaining live game.

## Legacy/unverified policy

Unlinked props always have `event_id: null`, no authoritative provider fields,
and `identity_source: legacy` or `unresolved`. A legacy display key requires a
known schedule, explicit boolean side, two distinct non-placeholder participants,
and sport. Its participants remain inferred from the old fields, never verified.
Unresolved context has a null key/participants and can still be browsed where
the existing offer policy permits. An old opaque ID alone does not verify an
Event or establish provider provenance.

Game lists exclude unsafe legacy cards when:

- Participant, side, or schedule information is incomplete or self-matching.
- The same stored sport/opaque-ID namespace produces conflicting keys or missing
  contexts, including conflicts on inactive or expired records.
- One display key overlaps multiple legacy namespaces or a known Event, including
  an Event with no linked eligible props.

Feed and generic research availability retain unlinked sportsbook-backed props
under the existing freshness rules, independently of card exclusions. Explicit
Prop UUID research can address unavailable/unresolved subjects. Missing provider
IDs, synthetic IDs, unknown observations and expired offers remain non-actionable
under the existing policy. No blanket exclusion of 6,054 legacy props and no
invented linkage occurs; historical/inactive data is not automatically actionable.

Legacy keys normalize their timestamp to UTC for comparison and accept previous
naive-UTC spelling or equivalent explicit offsets. A key matching exactly one
Event and no unlinked group resolves to that Event and returns its current
metadata. A mixed linked/unlinked key is rejected, not merged. Pre-link keys
with different inferred participants and old schedule keys have no permanent
alias: they return 404 unless independently represented by an unambiguous stored
legacy grouping. No fuzzy lookup or redirect guesses a related matchup.

An alias table would preserve historical URL spellings, but those spellings lack
trusted immutable evidence and can collide. No demonstrated requirement justifies
another schema migration now. Event UUID routes provide durable identity without
retaining unsafe aliases. Remaining legacy keys can still change on player trades.

## Research selection and availability

```text
GET /players/{player_id}/research?prop_id=<prop_uuid>
```

An explicit UUID loads that exact stored Prop independently of activity and offer
eligibility. Unknown UUID returns 404; malformed UUID returns 422; wrong-player
selection returns 400. Combining `prop_id` with either `prop_type` or `line`
returns 400. Market/line parameters are never fallback hints.

The UUID survives line movement. The response uses that prop's current line and
linked Event, without switching to another game, book or side. This API selects a
Prop, not a stored slip offer: it does not pin an old line or infer a side. Exact
persisted slip choices retain their independent original contract.

`selection_source` is `prop_id`, `legacy`, or `default`. `selection_available`
and the research prop's availability metadata describe the primary current
`sportsbook` plus `Prop.line`; at least one valid side must exist. Expired/missing
primary offers return null primary prices and false actionability, even if a
different book or line remains live. Alternatives remain explicitly labeled in
`sportsbook_offers`/best-line fields and never replace the primary identity.
`available_props` lists props with at least one eligible offer; an alternative-only
row may therefore have primary `actionable: false` and explicit available offers.

Explicit unavailable, expired, inactive and started selections remain in
`selected_prop`. History, trends, splits and exclusions are computed independently
using the selected Event's schedule. Missing history cannot hide available prices;
missing offers cannot erase history. L5/L10 continue across eligible recent
seasons; current-season windows remain strictly season-specific, with unchanged
sample sizes, exclusions and null rates.

Legacy market/line selection checks **all** stored matching player props,
including unavailable records: more than one returns 409; a unique unavailable
match returns 400. This intentionally prevents expiration from changing the
subject. It can reject broad market-only queries with historical duplicates; the
frontend must migrate to Prop UUIDs. Generic research with no selector keeps the
earliest eligible game, market, line ordering, adding Prop UUID as a deterministic
tie breaker. With no live props it preserves the empty research response.

## Time and today's-games semantics

Naive stored datetimes mean UTC. Exposed Event schedules and compatibility
`game_time` serialize with explicit `+00:00`; research movement timestamps now do
too. Provider observation, ingestion, local Event metadata write time and response
evaluation time remain distinct; an Event update is never an odds refresh. The
30-minute Live and inclusive six-hour Last known thresholds are unchanged.

`/todays-games` remains an upcoming eligible list for existing frontend callers,
even when the event is several days away. It does not mean the user's local date
or the venue's date. `/games` is the clearer upcoming contract. A future true
calendar-date endpoint would need an explicit date/timezone contract and separate
migration; no silent date filtering was introduced. Existing Feed/Discover day
priority remains Eastern, now evaluated using the effective Event schedule.

## Verification and data safety

All API fixtures use isolated FastAPI apps without the production
lifespan. `tests/run_no_provider_http.py` blocks synchronous/asynchronous httpx
external transports and standard-library HTTP connection creation, while allowing
ASGI TestClient. Existing provider tests mock their clients.

The disposable cached `postgres:15-alpine` container is
`proppulse-test-m3d-20261015`, loopback port 54764, database
`proppulse_test_milestone3d`, tmpfs storage, no bind mounts/named volumes, and
temporary test-only trust authentication. Test classes validate the explicit
`proppulse_test_` target and create/drop only random test schemas. The fixture
includes one Event with ten props across both teams, mixed unlinked/conflicting
groups, valid/expired offers and provider history. PostgreSQL game tests use the
real ranking queries; SQLite game tests stub only ranking's PostgreSQL ARRAY path.
Existing migration tests run only on disposable schemas, without authoring any
new revision. Development containers remain stopped.

Final results (all commands actually executed):

| Check | Result |
| --- | --- |
| `venv/Scripts/python.exe tests/run_no_provider_http.py` from backend, with explicit isolated test URL | **490 passed**, zero failures/errors/skips, 70.858 seconds |
| Real PostgreSQL cases included in full discovery | **127 passed**, PostgreSQL **15.18**, zero failures/errors/skips; corrected fixture count, see checkpoint below |
| Focused `test_event_apis.py` through the blocked-HTTP runner | **46 passed** (23 SQLite + 23 PostgreSQL), zero failures/errors/skips |
| Focused `test_research_selection.py` through the blocked-HTTP runner | **44 passed** (22 SQLite + 22 PostgreSQL), zero failures/errors/skips |
| External HTTP transport attempts in final full run | **0** |
| Frontend `npm test` | **39 passed**, zero failures/errors/skips |
| Frontend `npx tsc --noEmit` | Passed, exit 0 |
| Frontend `npm run build` | Passed, Next.js production build, exit 0 |
| Python `compileall -q backend/app backend/scripts backend/tests` | Passed, exit 0 |
| `git --git-dir=.git --work-tree=. diff --check` | Passed, exit 0 |
| Effective `LIVE_REFRESH_ENABLED` inspection from backend | **False** |

Independent read-only review identified ingestion-status and player-search paths
still using legacy schedules; both were fixed with regressions. Research primary
availability was also tightened so explicit alternatives cannot mask unavailable
primary selections. Final review found no remaining actionable defect. The final
full suite ran after these fixes and the shared Event-aware SQL prefilter.

After verification the disposable database had **zero leftover test schemas**
and **zero advisory locks**. Its exact container was removed. Inspection confirmed
tmpfs-only storage with no named-volume/bind mounts; development PostgreSQL,
backend and Redis containers remained stopped. Existing application volumes,
backups, environment files, data, IDs, prices, snapshots and user selections were
not modified. No development connection was made, so the supplied baseline is
not claimed as a newly verified inventory.

Earlier focused runs without the opt-in URL intentionally skipped PostgreSQL;
the final opt-in runs above executed every test with zero skips. An initial
settings inspection from the repository root failed to import `app`; the
inspection was rerun successfully from backend. Existing datetime/Pydantic/AnyIO
warnings and Git line-ending notices do not represent test failures. Provider/demo
messages in suite output come from mocked or isolated fixtures. No real provider
or legacy demo refresh script was run against application data.

No browser E2E, live-provider verification, or development database checks were
performed. Standalone lint was omitted because no ESLint configuration exists;
tests, TypeScript and the production build passed. No schema revision, dependency
or configuration change was required. Nothing was staged, committed or pushed.

## Files and Phase 3E readiness

Implementation: `backend/app/services/game_identity_service.py`,
`offer_service.py`, `trend_service.py`, `backend/app/routers/props.py`,
`players.py`, `backend/app/schemas.py`.

Tests: new `backend/tests/test_event_apis.py`, `test_research_selection.py`,
`run_no_provider_http.py`; updated `test_offer_availability.py` isolates its
existing freshness assertion from the new identity resolver.

Frontend contracts only: `frontend/src/lib/api.ts`, `types.ts`,
`frontend/tests/event-api-contract.test.cjs`. This document records audit/policy.

Phase 3E must:

1. Key verified game cards/routes by `event_id`; pass that UUID to Detail,
   Feed and Discover. Use `game_key` only for explicit legacy fallback.
2. Render identity provenance and authoritative participant/schedule fields;
   stop deriving headers from current Player.team or raw opponent/side.
3. Navigate to player research with `prop_id` and preserve it across polling,
   unavailable states and line changes. Avoid broad market-only ambiguity.
4. Keep explicit unavailable selections/history visible and separately render
   alternative books/lines without replacing stored choices.
5. Handle 400/404/409/422 responses, empty authoritative detail and legacy cards
   intentionally omitted for ambiguity; label upcoming versus calendar-day lists.
6. Verify actual browser navigation, polling, hydration and unavailable selection
   interactions. No browser E2E is claimed by this backend milestone.

Remaining limitations: legacy identity cannot be made immutable without trusted
linkage/alias evidence; player historical side and provider athlete identities
remain incomplete; competition/completion history metadata retains Phase 3A
limitations. Legacy compatibility requires inventory scans, so large deployments
may need a bounded indexed resolver after trustworthy identity coverage improves.
No Phase 3E navigation work has begun.

## Final engineering review and authorized local checkpoint

The final checkpoint review started on `master` at the expected
`468ccd2f76bb2af47b33ca09d281106afd2b45b7`. Status contained only the fourteen
Phase 3D implementation, test, contract and documentation files listed above.
Complete tracked/new-file review and an independent read-only review verified
Event UUID identity, schedule precedence, both-team grouping, empty Events,
exact UUID filters, legacy ambiguity, retained research selections, primary
offer availability, historical windows, errors, UTC fields and saved/slip safety.
Existing frontend calls still compile; stricter legacy ambiguity errors are the
documented intentional compatibility boundary.

Two confirmed corrections were made during this final review:

- The ingestion-status query had not eagerly loaded Event after the shared
  offer policy began reading its schedule. A three-Event/twelve-prop regression
  with an empty identity map reproduced four SELECTs in both SQLite and
  PostgreSQL. Adding `joinedload(Prop.event)` reduces the endpoint to one SELECT.
  Both regression variants failed before the fix and passed afterward.
- The verification runner counted any test ID containing "postgres", accidentally
  including five mocked target-guard cases and one mocked read-only-connection
  case. It now counts the seven opt-in `*PostgresTests` fixture classes. The
  earlier 490-test implementation run had **127 actual PostgreSQL cases**, not
  the reported 133; all 490 test outcomes remain unchanged. The new pair of
  query-count regressions makes the checkpoint total **492 tests**, including
  **128 actual PostgreSQL cases**.

Core Feed/Discover/player-prop queries eagerly load Event, player and offers.
Legacy key resolution and card safety still inspect all stored identities,
including inactive props and empty Events, to avoid expiration resolving an
ambiguity. That documented inventory cost is retained; arbitrary truncation
would weaken correctness. Existing saved/slip per-row lookups and broader query
optimization remain deferred, without changing stored identity/selection fields.

Checkpoint verification uses only disposable
`proppulse-test-m3d-checkpoint-20261015`, database
`proppulse_test_m3d_checkpoint`, PostgreSQL **15.18**, loopback port **59343**,
tmpfs-only data, temporary test-only trust and no volume/bind mounts. The existing
test database-name and random-schema guards remain active. No development
connection, application lifespan, ingestion, Event/link operation, provider call,
new schema migration or refresh worker is used.

| Checkpoint check | Result |
| --- | --- |
| Complete backend discovery through `tests/run_no_provider_http.py` | **492 passed**, zero failures/errors/skips |
| Actual isolated PostgreSQL fixture cases included above | **128 passed**: Event API 24, research selection 22, Event ingestion 26, Event migration 15, ingestion/API 11, process locking 2, bounded linkage 28 |
| Focused Event API suite | **48 passed**, including 24 PostgreSQL |
| Focused research-selection suite | **44 passed**, including 22 PostgreSQL |
| Focused existing offer-availability suite | **15 passed** |
| External HTTP attempts in complete and focused runs | **0** |
| Frontend tests | **39 passed**, zero failures/skips |
| TypeScript and frontend production build | Passed, exit 0; ten pages generated |
| Python compilation | Passed, exit 0 |
| Git whitespace checks, including added files | Passed |
| Effective automatic refresh | False |

The final complete run finished in **70.456 seconds** with the corrected
PostgreSQL counter. Before removing the disposable checkpoint container,
verification found **zero remaining test schemas** and **zero advisory locks**.
Only that test container was removed; development PostgreSQL/backend/Redis
remained stopped. No development database connection was made.

The proposed checkpoint contains no credentials, environment secrets, live raw
provider payloads, ignored reports/manifests, backups, generated build artifacts,
virtual environments or temporary test outputs. A secret-pattern scan found no
matches; fixtures contain synthetic test data. Only the fourteen reviewed files
are authorized for the local commit
`feat: add stable event APIs and prop research selection`. Earlier no-commit
statements describe the implementation stage. No push or history rewrite is
authorized. Browser E2E and standalone lint were not run for the reasons recorded
above; Phase 3E navigation remains unimplemented.
