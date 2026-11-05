"""Read-only revision-05 deployment contract; readiness never migrates data.

Keep this deployment contract in sync with future reviewed schema revisions.
Never invoke migration upgrade/repair from readiness.
"""
import re
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
EXPECTED_REVISION = "20261022_05"
class SchemaPrerequisiteError(RuntimeError):
    pass

def fail(detail):
    raise SchemaPrerequisiteError("schema_prerequisites")

CHECKS = {
    "ck_events_nonempty_identity": "length(trim(provider)) > 0 AND length(trim(sport_key)) > 0 AND length(trim(provider_event_id)) > 0",
    "ck_events_nonempty_teams": "length(trim(home_team)) > 0 AND length(trim(away_team)) > 0",
    "ck_events_distinct_teams": "lower(trim(home_team)) != lower(trim(away_team))",
}
EVENT_COLUMNS = {"id", "provider", "provider_event_id", "sport_key", "home_team", "away_team", "scheduled_start_at", "updated_at"}
GUARD_BODY = """BEGIN
    IF OLD.event_id IS NOT NULL AND NEW.event_id IS DISTINCT FROM OLD.event_id THEN
        RAISE EXCEPTION 'A linked prop event identity cannot be reassigned or cleared'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;"""


def normalized(expression):
    value = expression.lower().replace("::text", "").replace("::character varying", "")
    value = re.sub(r"\btrim\s*\(\s*both\s+from\s+", "trim(", value)
    value = value.replace("trim(", "btrim(").replace("bbtrim(", "btrim(").replace("!=", "<>")
    return re.sub(r'[\s()"]', "", value)


def validate_schema(inspector):
    columns = {column["name"]: column for column in inspector.get_columns("events")}
    if set(columns) != EVENT_COLUMNS:
        fail("unexpected events columns")
    for name, column in columns.items():
        expected = UUID if name == "id" else sa.DateTime if name in {"scheduled_start_at", "updated_at"} else sa.String
        if column["nullable"] or not isinstance(column["type"], expected):
            fail("events column " + name)
        if isinstance(column["type"], sa.String) and column["type"].length is not None:
            fail("unexpected events string length restriction")
        if isinstance(column["type"], sa.DateTime) and column["type"].timezone:
            fail("events timestamps must use naive UTC storage")
        if column.get("default") is not None:
            fail("unexpected events server default")
    if inspector.get_pk_constraint("events")["constrained_columns"] != ["id"]:
        fail("events primary key")
    unique = {item["name"]: item for item in inspector.get_unique_constraints("events")}
    if unique.get("uq_events_provider_sport_event", {}).get("column_names") != ["provider", "sport_key", "provider_event_id"]:
        fail("events provider uniqueness")
    checks = {item["name"]: item["sqltext"] for item in inspector.get_check_constraints("events")}
    for name, expression in CHECKS.items():
        if name not in checks or normalized(checks[name]) != normalized(expression):
            fail("events check " + name)
    validate_index(inspector, "events", "ix_events_sport_start", ["sport_key", "scheduled_start_at"])
    prop_column = {column["name"]: column for column in inspector.get_columns("props")}.get("event_id")
    if not prop_column or not prop_column["nullable"] or not isinstance(prop_column["type"], UUID) or prop_column.get("default") is not None:
        fail("props.event_id must be nullable UUID without a default")
    validate_index(inspector, "props", "ix_props_event_id", ["event_id"])
    links = [item for item in inspector.get_foreign_keys("props") if "event_id" in item["constrained_columns"]]
    if len(links) != 1:
        fail("props.event_id foreign key")
    link = links[0]
    if (link["name"] != "fk_props_event_id_events" or link["constrained_columns"] != ["event_id"]
            or link["referred_table"] != "events" or link["referred_columns"] != ["id"]
            or link.get("referred_schema") not in (None, inspector.default_schema_name)
            or link.get("options", {}).get("ondelete", "").upper() != "RESTRICT"):
        fail("props.event_id foreign key definition")


def validate_index(inspector, table, name, columns):
    index = next((item for item in inspector.get_indexes(table) if item["name"] == name), None)
    if (not index or index["column_names"] != columns or index["unique"]
            or index.get("dialect_options", {}).get("postgresql_where")):
        fail("index " + name)


def validate_guard(connection):
    functions = connection.execute(sa.text("""
        SELECT p.oid, p.pronargs, p.prosrc, l.lanname, p.prosecdef, p.proconfig,
               p.prorettype::regtype::text AS return_type
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        JOIN pg_language l ON l.oid = p.prolang
        WHERE n.nspname = current_schema() AND p.proname = 'guard_prop_event_identity'
    """)).mappings().all()
    triggers = connection.execute(sa.text("""
        SELECT t.tgtype, t.tgenabled, t.tgnargs, t.tgqual IS NULL AS unconditional,
               p.proname, n.nspname = current_schema() AS local_function,
               ARRAY(SELECT a.attname FROM pg_attribute a
                     WHERE a.attrelid = t.tgrelid AND a.attnum = ANY(t.tgattr)) AS columns
        FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
        JOIN pg_namespace cn ON cn.oid = c.relnamespace
        JOIN pg_proc p ON p.oid = t.tgfoid JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE cn.nspname = current_schema() AND c.relname = 'props'
              AND t.tgname = 'trg_props_event_identity' AND NOT t.tgisinternal
    """)).mappings().all()
    if len(functions) != 1 or len(triggers) != 1:
        fail("partial or conflicting event identity guard")
    function, trigger = functions[0], triggers[0]
    if (function["pronargs"] != 0 or function["lanname"] != "plpgsql" or function["return_type"] != "trigger"
            or function["prosecdef"] or function["proconfig"] is not None
            or normalized(function["prosrc"]) != normalized(GUARD_BODY)
            or trigger["tgtype"] != 19 or trigger["tgenabled"] != "O" or trigger["tgnargs"] != 0 or not trigger["unconditional"]
            or trigger["proname"] != "guard_prop_event_identity" or not trigger["local_function"]
            or trigger["columns"] != ["event_id"]):
        fail("conflicting event identity guard definition")


def validate_database(connection):
    if connection.dialect.name != "postgresql":
        fail("postgresql_required")
    connection.execute(sa.text("SELECT 1"))
    inspector = sa.inspect(connection)
    tables = set(inspector.get_table_names())
    if "alembic_version" not in tables:
        raise SchemaPrerequisiteError("schema_revision")
    versions = connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalars().all()
    if versions != [EXPECTED_REVISION]:
        raise SchemaPrerequisiteError("schema_revision")
    from app.database import Base
    from app import models  # register metadata only
    # Reflection preserves NOT VALID CHECK expressions and omits FK validation
    # state. Definitions alone cannot prove integrity of preexisting rows.
    unvalidated = connection.execute(sa.text("""
        SELECT EXISTS (
            SELECT 1 FROM pg_constraint c
            JOIN pg_namespace n ON n.oid = c.connamespace
            JOIN pg_class r ON r.oid = c.conrelid
            WHERE n.nspname = current_schema() AND r.relname = ANY(:tables)
              AND c.contype IN ('c', 'f') AND NOT c.convalidated
        )
    """), {"tables": list(Base.metadata.tables)}).scalar_one()
    if unvalidated:
        fail("unvalidated_constraints")
    # Failed concurrent builds remain visible to reflection, including unique
    # indexes that do not enforce uniqueness. Inspect the required indexes only.
    required_indexes = {index.name for table in Base.metadata.sorted_tables
                        for index in table.indexes if index.unique}
    required_indexes.update({"ix_events_sport_start", "ix_props_event_id", *EVIDENCE_INDEXES})
    index_states = dict(connection.execute(sa.text("""
        SELECT r.relname, i.indisvalid AND i.indisready AND i.indislive AS usable
        FROM pg_index i
        JOIN pg_class r ON r.oid = i.indexrelid
        JOIN pg_class t ON t.oid = i.indrelid
        JOIN pg_namespace n ON n.oid = r.relnamespace
        WHERE n.nspname = current_schema() AND t.relname = ANY(:tables)
    """), {"tables": list(Base.metadata.tables)}).tuples().all())
    if any(name in index_states and not index_states[name] for name in required_indexes):
        fail("invalid_prerequisite_indexes")
    for table in Base.metadata.sorted_tables:
        if table.name not in tables:
            fail("missing_table")
        columns = {item["name"] for item in inspector.get_columns(table.name)}
        if not set(table.columns.keys()).issubset(columns):
            fail("missing_columns")
        if inspector.get_pk_constraint(table.name)["constrained_columns"] != ["id"]:
            fail("missing_primary_key")
        unique = {tuple(item["column_names"]) for item in inspector.get_unique_constraints(table.name)}
        for constraint in table.constraints:
            if isinstance(constraint, sa.UniqueConstraint) and tuple(constraint.columns.keys()) not in unique:
                fail("missing_unique_constraint")
        unique_indexes = {tuple(item["column_names"]) for item in inspector.get_indexes(table.name)
                          if item["unique"] and index_states.get(item["name"], False)
                          and not item.get("dialect_options", {}).get("postgresql_where")}
        for index in table.indexes:
            if index.unique and tuple(index.columns.keys()) not in unique_indexes:
                fail("missing_unique_index")
        foreign_keys = inspector.get_foreign_keys(table.name)
        for constraint in table.foreign_key_constraints:
            expected = [(item.parent.name, item.column.table.name, item.column.name) for item in constraint.elements]
            if not any(list(zip(item["constrained_columns"],
                                [item["referred_table"]] * len(item["referred_columns"]),
                                item["referred_columns"])) == expected for item in foreign_keys):
                fail("missing_foreign_key")
    validate_schema(inspector)
    validate_guard(connection)
    validate_evidence_schema(connection)
    validate_evidence_guard(connection)


# Frozen revision-03 shape: never import live application model metadata here.
EVIDENCE_TABLE = "nba_evidence_records"
EVIDENCE_COLUMNS = {"id", "provider", "sport", "kind", "identity", "player_id", "team_id", "game_id", "payload", "source", "observed_at", "ingested_at", "fingerprint"}
EVIDENCE_CHECKS = {
    "ck_nba_evidence_namespace": "provider IN ('espn', 'nba_com') AND sport = 'NBA'",
    "ck_nba_evidence_kind": "kind IN ('game', 'participation', 'athlete', 'team', 'membership', 'coverage')",
    "ck_nba_evidence_nonempty": "length(trim(identity)) > 0 AND length(trim(source)) > 0",
    "ck_nba_evidence_optional_identity": "(team_id IS NULL OR length(trim(team_id)) > 0) AND (game_id IS NULL OR length(trim(game_id)) > 0)",
    "ck_nba_evidence_fingerprint": "length(fingerprint) = 64 AND lower(fingerprint) = fingerprint",
}
EVIDENCE_INDEXES = {
    "ix_nba_evidence_namespace_identity": ["provider", "sport", "kind", "identity"],
    "ix_nba_evidence_records_player_id": ["player_id"],
    "ix_nba_evidence_records_team_id": ["team_id"],
    "ix_nba_evidence_records_game_id": ["game_id"],
}
EVIDENCE_GUARD_BODY = """BEGIN
    RAISE EXCEPTION 'NBA evidence is append-only; append a new observation instead'
        USING ERRCODE = '23514';
END;"""


def evidence_normalized(expression):
    # Preserve literal case/content while normalizing PostgreSQL presentation.
    literals = []
    def protect(match):
        literals.append(match.group(0))
        return "__literal" + str(len(literals) - 1) + "__"
    value = re.sub(r"'(?:''|[^'])*'", protect, expression).lower()
    value = value.replace("::text", "").replace("::character varying", "")
    value = re.sub(r"\btrim\s*\(\s*both\s+from\s+", "trim(", value)
    value = value.replace("trim(", "btrim(").replace("bbtrim(", "btrim(")
    value = value.replace("= any", "in").replace("array[", "").replace("]", "").replace("[", "")
    value = re.sub(r'[\s()"]', "", value)
    for index, literal in enumerate(literals):
        value = value.replace("__literal" + str(index) + "__", literal)
    return value

def validate_evidence_schema(connection):
    inspector = sa.inspect(connection)
    columns = {column["name"]: column for column in inspector.get_columns(EVIDENCE_TABLE)}
    if set(columns) != EVIDENCE_COLUMNS:
        fail("unexpected evidence columns")
    for name, column in columns.items():
        expected = UUID if name in {"id", "player_id"} else sa.DateTime if name in {"observed_at", "ingested_at"} else sa.JSON if name == "payload" else sa.String
        if not isinstance(column["type"], expected) or column["nullable"] != (name in {"player_id", "team_id", "game_id"}):
            fail("evidence column " + name)
        if column.get("default") is not None:
            fail("unexpected server default " + name)
        if isinstance(column["type"], sa.String) and column["type"].length != (64 if name == "fingerprint" else None):
            fail("unexpected string length " + name)
        if isinstance(column["type"], sa.DateTime) and column["type"].timezone:
            fail("evidence timestamps must use naive UTC storage")
    if inspector.get_pk_constraint(EVIDENCE_TABLE)["constrained_columns"] != ["id"]:
        fail("evidence primary key")
    unique = {item["name"]: item for item in inspector.get_unique_constraints(EVIDENCE_TABLE)}
    if unique.get("uq_nba_evidence_identity_fingerprint", {}).get("column_names") != ["provider", "sport", "kind", "identity", "fingerprint"]:
        fail("evidence observation uniqueness")
    checks = {item["name"]: item["sqltext"] for item in inspector.get_check_constraints(EVIDENCE_TABLE)}
    for name, expression in EVIDENCE_CHECKS.items():
        if name not in checks or evidence_normalized(checks[name]) != evidence_normalized(expression):
            fail("evidence check " + name)
    for name, fields in EVIDENCE_INDEXES.items():
        index = next((item for item in inspector.get_indexes(EVIDENCE_TABLE) if item["name"] == name), None)
        if (not index or index["column_names"] != fields or index["unique"]
                or index.get("dialect_options", {}).get("postgresql_where")):
            fail("evidence index " + name)
    links = inspector.get_foreign_keys(EVIDENCE_TABLE)
    if len(links) != 1:
        fail("evidence player foreign key")
    link = links[0]
    if (link["name"] != "fk_nba_evidence_player_id_players" or link["constrained_columns"] != ["player_id"]
            or link["referred_table"] != "players" or link["referred_columns"] != ["id"]
            or link.get("referred_schema") not in (None, inspector.default_schema_name)
            or link.get("options", {}).get("ondelete", "").upper() != "RESTRICT"):
        fail("evidence player foreign key definition")
    unvalidated = connection.execute(sa.text("""SELECT EXISTS (
        SELECT 1 FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace
        JOIN pg_class r ON r.oid=c.conrelid WHERE n.nspname=current_schema()
        AND r.relname='nba_evidence_records' AND c.contype IN ('c','f') AND NOT c.convalidated)""")).scalar_one()
    unusable = connection.execute(sa.text("""SELECT EXISTS (
        SELECT 1 FROM pg_index i JOIN pg_class r ON r.oid=i.indrelid
        JOIN pg_namespace n ON n.oid=r.relnamespace WHERE n.nspname=current_schema()
        AND r.relname='nba_evidence_records' AND NOT (i.indisvalid AND i.indisready AND i.indislive))""")).scalar_one()
    if unvalidated or unusable:
        fail("unvalidated constraint or invalid index")


def validate_evidence_guard(connection):
    functions = connection.execute(sa.text("""SELECT p.pronargs, p.prosrc, l.lanname,
        p.prosecdef, p.proconfig, p.prorettype::regtype::text AS return_type
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        JOIN pg_language l ON l.oid=p.prolang
        WHERE n.nspname=current_schema() AND p.proname='guard_nba_evidence_append_only'""")).mappings().all()
    triggers = connection.execute(sa.text("""SELECT t.tgtype, t.tgenabled, t.tgnargs,
        t.tgqual IS NULL AS unconditional, p.proname, n.nspname=current_schema() AS local_function,
        cardinality(t.tgattr::smallint[]) AS column_count
        FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
        JOIN pg_namespace cn ON cn.oid=c.relnamespace
        JOIN pg_proc p ON p.oid=t.tgfoid JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE cn.nspname=current_schema() AND c.relname='nba_evidence_records'
        AND t.tgname='trg_nba_evidence_append_only' AND NOT t.tgisinternal""")).mappings().all()
    if len(functions) != 1 or len(triggers) != 1:
        fail("partial evidence append-only guard")
    function, trigger = functions[0], triggers[0]
    if (function["pronargs"] != 0 or function["lanname"] != "plpgsql" or function["return_type"] != "trigger"
            or function["prosecdef"] or function["proconfig"] is not None
            or evidence_normalized(function["prosrc"]) != evidence_normalized(EVIDENCE_GUARD_BODY)
            or trigger["tgtype"] != 27 or trigger["tgenabled"] != "O" or trigger["tgnargs"] != 0
            or not trigger["unconditional"] or not trigger["local_function"] or trigger["column_count"] != 0
            or trigger["proname"] != "guard_nba_evidence_append_only"):
        fail("conflicting evidence append-only guard definition")
