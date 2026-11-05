# Public source snapshot

Prepared November 4, 2026 from reviewed source checkpoint `5a0b6818436e12f69ef92c70f49677fc2506b3ee`. This repository starts a separate public history; none of the original development Git objects are included. The original private working repository remains separate and unchanged.

## Publication review

Gitleaks 8.30.1 scanned all 75 original commits and the proposed source directory. Both scans reported four `generic-api-key` matches in `frontend/tests/fixtures/exact-line-research.json`: invented `game_id` values with the `mlb_stats_api:1234-invented-` prefix. Manual review classifies these as public-safe synthetic fixture identifiers / scanner false positives. No exclusions or rule suppressions were used. No actual API/access token, private key or database export was identified. Scanning is a dated check, not a guarantee against every secret pattern.

Historical generated provider-run status and local player UUID mappings are potentially sensitive operational data. They are excluded from this snapshot: `backend/data/odds_ingestion_status.json` (historical only), `backend/odds_ingestion_status.json`, and `backend/data/nba_player_mappings.json`. Private environments, backups, certificates, scans, sessions, approval receipts and provider collections are not distributed. Actual local record identifiers and personal machine paths in historical reports were replaced with descriptive placeholders; public provider IDs and synthetic test fixtures remain.

The historical JWT match was a weak example **signing-key configuration**, not a signed token or API credential. It also matched a local development setting, so that local setting must be treated as non-secret. Before exposing that environment, replace the signing key and invalidate existing development sessions (a key change invalidates their signatures). No production use was established. No environment or credential was changed automatically. The specific reused weak literal is absent from this snapshot; rejection tests use a different explicit placeholder. Production configuration rejects placeholder/weak keys. Other test-only signing values and local database examples are intentionally public fixtures, never deployment credentials.

## Setup and limits

Normal setup uses the committed dependency locks, safe `.env.example`, application source and Alembic migrations. It does not require retained provider data. An empty database has no private players or accounts. Missing ingestion status is handled as unavailable. Manual NBA collection requires your own reviewed private mapping via `--mapping`; provider collection/import is separately authorized work, not setup. Historical reports describe prior local checks whose private evidence is not shipped.

Publication changes affect documentation, ignore rules, exclusions and one invalid-secret test input. Two focused configuration tests passed in the existing isolated verification environment. Syntax, JSON, local Markdown targets, dependency-lock presence, Docker context and migration structure were checked. Images and full regression suites were not rebuilt/rerun for this source-publication task. Existing dated vulnerability reports and release limitations still apply; no public deployment is approved.
