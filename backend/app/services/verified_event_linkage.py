"""One reviewed Celtics/Pistons Event and ten explicit relationships only.

No providers, migrations, schedule corrections or generic backfill interface.
The production entry point requires the development target. The separate test
entry point requires the explicit disposable PostgreSQL URL before connecting.
"""
import hashlib
import os
import ipaddress
from copy import deepcopy
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy import MetaData, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.database import Base
from app.models import Event, Player, Prop
from app.services.event_identity import validate_event_metadata, link_prop_to_event
from app.services.event_link_manifest import revalidate_event_link_manifest, _expected
from app.services.ingestion_control import odds_ingestion_lock
from app.services import verified_linkage_scope as scope

REVISION = "20261014_02"
REVISION02_TABLES = frozenset({
    "players", "props", "prop_books", "prop_book_snapshots", "player_game_logs",
    "users", "interactions", "saved_props", "slips", "slip_items", "fatigue_scores",
    "rankings", "events",
})


def revision02_metadata():
    """Isolate the reviewed revision-02 tables from later additive metadata.

    The executor remains approved only for revision 02. New evidence storage is
    neither required nor adopted by this historical operation; revision 03 is
    rejected before schema inspection or any candidate writes.
    """
    metadata = MetaData()
    for table in Base.metadata.sorted_tables:
        if table.name in REVISION02_TABLES:
            table.to_metadata(metadata)
    return metadata


class LinkageRejected(ValueError):
    """Fixed safe reason code, never database exception text."""


def require(condition, reason):
    if not condition:
        raise LinkageRejected(reason)


@contextmanager
def reported_lock(engine, report):
    operation_error = None
    try:
        with odds_ingestion_lock(engine.execution_options(postgresql_readonly=True)) as acquired:
            report["lock_acquired"] = acquired
            try:
                yield acquired
            except BaseException as error:
                operation_error = error
                raise
    except BaseException as error:
        # The original operation exception passing through the context means
        # its finally block completed the unlock. An unlock error replaces it.
        report["lock_released"] = operation_error is error
        raise
    else:
        report["lock_released"] = True


def validate_target_url(url, *, isolated=False):
    target = make_url(url)
    require(target.get_backend_name() == "postgresql", "postgresql_required")
    require(not target.query, "database_url_overrides_forbidden")
    if isolated:
        explicit = os.environ.get("PROPPULSE_TEST_POSTGRES_URL")
        require(explicit and target == make_url(explicit)
                and (target.database or "").startswith("proppulse_test_"), "isolated_target_required")
    else:
        require((target.host, target.port or 5432, target.database) ==
                ("localhost", 5432, "proppulse"), "development_target_required")
    return target


def configure_transaction(connection, *, writable=False):
    connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, " +
                            ("READ WRITE" if writable else "READ ONLY")))
    connection.execute(text("SET LOCAL lock_timeout = '3s'"))
    connection.execute(text("SET LOCAL statement_timeout = '30s'"))
    connection.execute(text("SET LOCAL idle_in_transaction_session_timeout = '60s'"))
    connection.execute(text("SET LOCAL TIME ZONE 'UTC'"))
    require(connection.execute(text("SHOW transaction_read_only")).scalar_one() ==
            ("off" if writable else "on"), "transaction_mode_conflict")


def verify_database(connection, target, *, isolated=False):
    dsn = connection.connection.driver_connection.get_dsn_parameters()
    require(dsn.get("dbname") == target.database, "connected_dsn_database_mismatch")
    if not isolated:
        require(dsn.get("host") == "localhost" and dsn.get("port", "5432") == "5432",
                "connected_dsn_target_mismatch")
        if dsn.get("hostaddr"):
            require(ipaddress.ip_address(dsn["hostaddr"]).is_loopback, "connected_dsn_address_mismatch")
    actual = connection.execute(text("SELECT current_database(), inet_server_port(), current_schema()" )).one()
    require(actual[0] == target.database, "connected_database_mismatch")
    require(connection.execute(text("SHOW server_version")).scalar_one().split()[0] == "15.18",
            "postgresql_version_mismatch")
    if not isolated:
        require(actual[1:] == (5432, "public"), "connected_target_mismatch")
    else:
        require(actual[2].startswith("proppulse_test_"), "isolated_schema_required")
    quote = connection.dialect.identifier_preparer.quote
    schema = actual[2]
    revision = connection.execute(text("SELECT version_num FROM " + quote(schema) + ".alembic_version")).scalars().all()
    require(revision == [REVISION], "revision_mismatch")
    approved_metadata = revision02_metadata()
    expected = set(REVISION02_TABLES) | {"alembic_version"}
    require(set(inspect(connection).get_table_names(schema=schema)) == expected, "schema_tables_mismatch")
    differences = compare_metadata(MigrationContext.configure(connection, opts={"compare_type": True}), approved_metadata)
    require(not differences, "schema_model_mismatch")
    trigger = connection.execute(text("""SELECT t.tgenabled, pg_get_triggerdef(t.oid)
        FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname=:schema AND c.relname='props' AND t.tgname='trg_props_event_identity'
        AND NOT t.tgisinternal"""), {"schema": schema}).all()
    require(len(trigger) == 1 and trigger[0][0] == "O"
            and "BEFORE UPDATE OF event_id" in trigger[0][1]
            and "guard_prop_event_identity()" in trigger[0][1], "link_guard_missing")
    return schema, sorted(expected)


def fingerprints(connection, schema, tables):
    """Full stored values stay in the database/process; reports contain hashes only."""
    quote = connection.dialect.identifier_preparer.quote
    inspector = inspect(connection)
    result = {}
    for table in tables:
        columns = [column["name"] for column in inspector.get_columns(table, schema=schema)]
        projections = {"full": columns}
        if table == "props":
            projections["without_event_id"] = [c for c in columns if c != "event_id"]
        item = {}
        for label, projection in projections.items():
            query = ("SELECT row_to_json(t)::text FROM (SELECT " + ",".join(map(quote, projection)) +
                     " FROM " + quote(schema) + "." + quote(table) + ") t ORDER BY row_to_json(t)::text")
            digest, count = hashlib.sha256(), 0
            for row in connection.execute(text(query)).scalars():
                digest.update(row.encode("utf-8") + b"\n")
                count += 1
            item[label] = {"rows": count, "sha256": digest.hexdigest()}
        result[table] = item
    return result


def candidate_inventory(session, *, locking=False):
    # Include related identity rows solely to detect expansion, never to adopt them.
    props = session.scalars(select(Prop).where(Prop.id.in_(scope.PROP_IDS)).order_by(Prop.id)
                            .with_for_update() if locking else
                            select(Prop).where(Prop.id.in_(scope.PROP_IDS)).order_by(Prop.id)).all()
    require({p.id for p in props} == scope.PROP_IDS, "candidate_missing")
    related = session.scalars(select(Prop.id).where(
        Prop.odds_event_id == scope.EVENT_METADATA["provider_event_id"],
        Prop.odds_sport_key == scope.EVENT_METADATA["sport_key"])).all()
    require(set(related) == scope.PROP_IDS, "related_scope_changed")
    rows = []
    for prop in props:
        player = session.get(Player, prop.player_id)
        require(player is not None, "player_missing")
        rows.append({"prop_id": prop.id, "event_id": prop.event_id, "player_id": player.id,
            "player_name": player.name, "sport": player.sport, "team": player.team, "team_abbr": player.team_abbr,
            **{field: getattr(prop, field) for field in ("prop_type", "line", "odds_sport_key",
                "odds_event_id", "game_time", "opponent", "is_home")}})
    return props, rows


def current_event_state(session, props, expected_existing_event_id):
    events = session.scalars(select(Event).order_by(Event.id)).all()
    if expected_existing_event_id is None:
        require(not events, "unexpected_existing_event")
        require(all(p.event_id is None for p in props), "unexpected_existing_link")
        require(session.query(Prop).filter(Prop.event_id.is_not(None)).count() == 0,
                "unrelated_event_links")
        return None
    try:
        expected_id = str(UUID(expected_existing_event_id))
    except (ValueError, TypeError, AttributeError):
        raise LinkageRejected("invalid_expected_event_id") from None
    require(len(events) == 1 and events[0].id == expected_id, "reviewed_event_uuid_mismatch")
    event = events[0]
    values = validate_event_metadata(**scope.EVENT_METADATA)
    require(all(getattr(event, key) == value for key, value in values.items()), "existing_event_metadata_conflict")
    links = {p.event_id for p in props}
    require(links == {None} or links == {expected_id}, "partial_or_conflicting_existing_links")
    all_linked = set(session.scalars(select(Prop.id).where(Prop.event_id.is_not(None))))
    require(all_linked == (set() if links == {None} else scope.PROP_IDS), "unrelated_event_links")
    return event


def revalidate(session, reviewed, expected_existing_event_id=None, *, locking=False):
    props, rows = candidate_inventory(session, locking=locking)
    event = current_event_state(session, props, expected_existing_event_id)
    # Only an explicitly reviewed, exact existing state may differ from the
    # original immutable manifest in this one FK. All other expected values match.
    historical_rows = deepcopy(rows)
    for row in historical_rows:
        row["event_id"] = None
    expected = {item["prop_id"]: item["expected"] for item in reviewed["manifest"]["candidates"]}
    for row in historical_rows:
        actual = _expected(row)
        for field in expected[row["prop_id"]]:
            require(actual[field] == expected[row["prop_id"]][field],
                    "candidate_changed:" + row["prop_id"] + ":" + field)
    revalidate_event_link_manifest(reviewed["manifest"], historical_rows, reviewed["evidence"],
                                  evidence_source=str(scope.EVIDENCE_PATH))
    return props, event


def verify_preservation(before, after, *, created):
    require(set(before) == set(after), "table_inventory_changed")
    for table in before:
        if table not in {"events", "props"}:
            require(before[table] == after[table], "unrelated_records_changed_" + table)
    require(before["props"]["without_event_id"] == after["props"]["without_event_id"], "legacy_prop_fields_changed")
    require(before["props"]["full"]["rows"] == after["props"]["full"]["rows"], "prop_count_changed")
    if created:
        require(before["events"]["full"]["rows"] == 0 and after["events"]["full"]["rows"] == 1,
                "event_count_changed")
    else:
        require(before["events"] == after["events"], "existing_event_changed")


def _run(engine, *, execute=False, approval=None, expected_existing_event_id=None, isolated=False):
    report = {"mode": "execute" if execute else "dry_run", "status": "rejected",
        "transaction_outcome": "not_started", "attempted": {"events_created": 0, "links_created": 0},
        "write_attempts": {"event_inserts": 0, "prop_link_updates": 0},
        "committed": {"events_created": 0, "links_created": 0}, "rejections": [],
        "post_commit_verification": "not_run", "lock_released": False}
    commit_sent = False
    try:
        require(not execute or approval == scope.APPROVAL_PHRASE, "operator_approval_required")
        target = validate_target_url(engine.url, isolated=isolated)
        if not isolated:
            from app.config import settings
            require(settings.ENVIRONMENT == "development" and not settings.LIVE_REFRESH_ENABLED,
                    "development_refresh_guard")
        reviewed = scope.load_reviewed_files()
        report.update({k: reviewed[k] for k in ("manifest_path", "evidence_path",
                       "manifest_file_sha256", "evidence_file_sha256")})
        report["target"] = {"database": target.database, "revision": REVISION,
                            "host": target.host, "port": target.port or 5432}
        # Confirm the actual target/schema in READ ONLY before any writable tx.
        with engine.execution_options(postgresql_readonly=True).connect() as connection:
            transaction = connection.begin()
            try:
                configure_transaction(connection)
                preflight_schema, preflight_tables = verify_database(connection, target, isolated=isolated)
            finally:
                transaction.rollback()
        with reported_lock(engine, report) as acquired:
            require(acquired, "ingestion_lock_held")
            with engine.execution_options(postgresql_readonly=True).connect() as connection:
                transaction = connection.begin()
                try:
                    configure_transaction(connection, writable=execute)
                    if execute:
                        # Conservative operational window: prevent ALL app DML,
                        # including non-ingestion writers, until verification/commit.
                        quote = connection.dialect.identifier_preparer.quote
                        connection.execute(text("LOCK TABLE " + ",".join(
                            quote(preflight_schema) + "." + quote(table) for table in preflight_tables) + " IN SHARE ROW EXCLUSIVE MODE"))
                    # Acquire table locks before any SELECT establishes the
                    # writable REPEATABLE READ snapshot; include intervening commits.
                    schema, tables = verify_database(connection, target, isolated=isolated)
                    reviewed = scope.load_reviewed_files()  # re-read pinned bytes under lock
                    before = fingerprints(connection, schema, tables)
                    report["before"] = before
                    with Session(bind=connection, autoflush=False, expire_on_commit=False) as session:
                        props, event = revalidate(session, reviewed, expected_existing_event_id, locking=execute)
                        report["candidate_prop_ids"] = sorted(p.id for p in props)
                        report["existing_links_reused"] = sum(p.event_id is not None for p in props)
                        created = event is None
                        report["event_action"] = "created" if created else "reused"
                        if execute:
                            if created:
                                report["write_attempts"]["event_inserts"] += 1
                                event = Event(**validate_event_metadata(**scope.EVENT_METADATA))
                                session.add(event)
                                session.flush()
                                report["attempted"]["events_created"] = 1
                            report["event_id"] = event.id
                            for prop in props:
                                if prop.event_id is None:
                                    report["write_attempts"]["prop_link_updates"] += 1
                                    link_prop_to_event(prop, event)
                                    session.flush()
                                    report["attempted"]["links_created"] += 1
                            revalidate(session, reviewed, event.id, locking=True)
                        else:
                            report["event_id"] = event.id if event else None
                            report["planned"] = {"events_created": int(created),
                                "links_created": 10 - report["existing_links_reused"]}
                        after = fingerprints(connection, schema, tables)
                        if execute:
                            verify_preservation(before, after, created=created)
                        else:
                            require(before == after, "dry_run_changed_data")
                        report["after"] = after
                        # Catch files changed during database validation, too.
                        require(scope.load_reviewed_files() == reviewed, "reviewed_files_changed")
                    if execute:
                        commit_sent = True
                        transaction.commit()
                        report["transaction_outcome"] = "committed"
                        report["committed"] = dict(report["attempted"])
                        # A new, explicitly READ ONLY snapshot verifies committed
                        # state. Its failure NEVER implies the commit rolled back.
                        post = connection.begin()
                        try:
                            configure_transaction(connection)
                            verify_database(connection, target, isolated=isolated)
                            with Session(bind=connection) as session:
                                revalidate(session, reviewed, report["event_id"])
                            committed_state = fingerprints(connection, schema, tables)
                            require(committed_state == after, "post_commit_state_changed")
                            report["post_commit"] = committed_state
                            report["post_commit_verification"] = "passed"
                        finally:
                            post.rollback()
                    else:
                        transaction.rollback()
                        report["transaction_outcome"] = "read_only_rolled_back"
                    report["status"] = "completed"
                except BaseException:
                    # Classify the write outcome before cleanup: a rollback
                    # failure must not turn a sent commit into "not_started".
                    if report["transaction_outcome"] != "committed":
                        report["transaction_outcome"] = "commit_unknown" if commit_sent else "rolled_back"
                        if commit_sent:
                            report["committed"] = None
                    else:
                        report["post_commit_verification"] = "failed"
                    if transaction.is_active:
                        try:
                            transaction.rollback()
                        except BaseException as rollback_error:
                            report["rollback_error"] = type(rollback_error).__name__
                            connection.invalidate()
                    raise
    except BaseException as error:
        report["status"] = ("requires_review" if report["transaction_outcome"] == "commit_unknown"
                            else "failed" if report["transaction_outcome"] == "committed" else "rejected")
        report["rejections"].append(str(error) if isinstance(error, (LinkageRejected, scope.ScopeRejected)) else type(error).__name__)
        report["interrupted"] = isinstance(error, (KeyboardInterrupt, SystemExit))
    if report["lock_released"] and report.get("lock_acquired"):
        try:
            with engine.execution_options(postgresql_readonly=True).connect() as connection:
                transaction = connection.begin()
                try:
                    configure_transaction(connection)
                    report["advisory_locks_remaining"] = connection.execute(text("""SELECT count(*)
                        FROM pg_locks WHERE locktype='advisory' AND database=(
                        SELECT oid FROM pg_database WHERE datname=current_database())""")).scalar_one()
                    require(report["advisory_locks_remaining"] == 0, "advisory_lock_remains")
                finally:
                    transaction.rollback()
        except Exception as error:
            if report["status"] == "completed":
                report["status"] = "failed"
            report["rejections"].append(str(error) if isinstance(error, LinkageRejected) else type(error).__name__)
    return report


def run_verified_linkage(engine, *, execute=False, approval=None, expected_existing_event_id=None):
    """Production path: exact development URL and actual target required."""
    return _run(engine, execute=execute, approval=approval,
                expected_existing_event_id=expected_existing_event_id)


def run_isolated_linkage(engine, *, execute=False, approval=None, expected_existing_event_id=None):
    """Test-only entry: opt-in test URL/name is validated before any connection."""
    return _run(engine, isolated=True, execute=execute, approval=approval,
                expected_existing_event_id=expected_existing_event_id)
