"""Persist append-only NBA evidence without fetching, linking or rewriting data.

Revision ID: 20261017_03
Revises: 20261014_02
"""
import re

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "20261017_03"
down_revision = "20261014_02"
branch_labels = None
depends_on = None

# Frozen revision-03 shape: never import live application model metadata here.
TABLE = "nba_evidence_records"
COLUMNS = {"id", "provider", "sport", "kind", "identity", "player_id", "team_id", "game_id", "payload", "source", "observed_at", "ingested_at", "fingerprint"}
CHECKS = {
    "ck_nba_evidence_namespace": "provider = 'espn' AND sport = 'NBA'",
    "ck_nba_evidence_kind": "kind IN ('game', 'participation', 'athlete', 'team', 'membership', 'coverage')",
    "ck_nba_evidence_nonempty": "length(trim(identity)) > 0 AND length(trim(source)) > 0",
    "ck_nba_evidence_optional_identity": "(team_id IS NULL OR length(trim(team_id)) > 0) AND (game_id IS NULL OR length(trim(game_id)) > 0)",
    "ck_nba_evidence_fingerprint": "length(fingerprint) = 64 AND lower(fingerprint) = fingerprint",
}
INDEXES = {
    "ix_nba_evidence_namespace_identity": ["provider", "sport", "kind", "identity"],
    "ix_nba_evidence_records_player_id": ["player_id"],
    "ix_nba_evidence_records_team_id": ["team_id"],
    "ix_nba_evidence_records_game_id": ["game_id"],
}
GUARD_BODY = """BEGIN
    RAISE EXCEPTION 'NBA evidence is append-only; append a new observation instead'
        USING ERRCODE = '23514';
END;"""


def fail(detail):
    raise RuntimeError("NBA evidence schema is incomplete or incompatible: " + detail + ". No automatic repair or evidence ingestion is performed.")


def normalized(expression):
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

def validate_schema(connection, *, allow_nba_com=False):
    inspector = sa.inspect(connection)
    columns = {column["name"]: column for column in inspector.get_columns(TABLE)}
    if set(columns) != COLUMNS:
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
    if inspector.get_pk_constraint(TABLE)["constrained_columns"] != ["id"]:
        fail("evidence primary key")
    unique = {item["name"]: item for item in inspector.get_unique_constraints(TABLE)}
    if unique.get("uq_nba_evidence_identity_fingerprint", {}).get("column_names") != ["provider", "sport", "kind", "identity", "fingerprint"]:
        fail("evidence observation uniqueness")
    checks = {item["name"]: item["sqltext"] for item in inspector.get_check_constraints(TABLE)}
    for name, expression in CHECKS.items():
        accepted = {normalized(expression)}
        if allow_nba_com and name == "ck_nba_evidence_namespace":
            accepted.add(normalized("provider IN ('espn', 'nba_com') AND sport = 'NBA'"))
        if name not in checks or normalized(checks[name]) not in accepted:
            fail("evidence check " + name)
    for name, fields in INDEXES.items():
        index = next((item for item in inspector.get_indexes(TABLE) if item["name"] == name), None)
        if (not index or index["column_names"] != fields or index["unique"]
                or index.get("dialect_options", {}).get("postgresql_where")):
            fail("evidence index " + name)
    links = inspector.get_foreign_keys(TABLE)
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


def install_or_validate_guard(connection):
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
    if not functions and not triggers:
        connection.execute(sa.text("CREATE FUNCTION guard_nba_evidence_append_only() RETURNS trigger LANGUAGE plpgsql AS $guard$\n" + GUARD_BODY + "\n$guard$"))
        connection.execute(sa.text("CREATE TRIGGER trg_nba_evidence_append_only BEFORE UPDATE OR DELETE ON nba_evidence_records FOR EACH ROW EXECUTE FUNCTION guard_nba_evidence_append_only()"))
        return
    if len(functions) != 1 or len(triggers) != 1:
        fail("partial evidence append-only guard")
    function, trigger = functions[0], triggers[0]
    if (function["pronargs"] != 0 or function["lanname"] != "plpgsql" or function["return_type"] != "trigger"
            or function["prosecdef"] or function["proconfig"] is not None
            or normalized(function["prosrc"]) != normalized(GUARD_BODY)
            or trigger["tgtype"] != 27 or trigger["tgenabled"] != "O" or trigger["tgnargs"] != 0
            or not trigger["unconditional"] or not trigger["local_function"] or trigger["column_count"] != 0
            or trigger["proname"] != "guard_nba_evidence_append_only"):
        fail("conflicting evidence append-only guard definition")


def upgrade():
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        raise RuntimeError("NBA evidence migration requires PostgreSQL transactional DDL")
    tables = set(sa.inspect(connection).get_table_names())
    if not {"players", "events", "props", "player_game_logs"}.issubset(tables):
        fail("missing revision-02 baseline")
    if TABLE not in tables:
        op.create_table(TABLE,
            sa.Column("id", UUID(as_uuid=False), primary_key=True),
            *(sa.Column(name, sa.String(), nullable=False) for name in ("provider", "sport", "kind", "identity", "source")),
            sa.Column("player_id", UUID(as_uuid=False), nullable=True),
            sa.Column("team_id", sa.String(), nullable=True), sa.Column("game_id", sa.String(), nullable=True),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("observed_at", sa.DateTime(), nullable=False), sa.Column("ingested_at", sa.DateTime(), nullable=False),
            sa.Column("fingerprint", sa.String(64), nullable=False),
            sa.UniqueConstraint("provider", "sport", "kind", "identity", "fingerprint", name="uq_nba_evidence_identity_fingerprint"),
            sa.ForeignKeyConstraint(["player_id"], ["players.id"], name="fk_nba_evidence_player_id_players", ondelete="RESTRICT"),
            *(sa.CheckConstraint(expression, name=name) for name, expression in CHECKS.items()))
        for name, columns in INDEXES.items():
            op.create_index(name, TABLE, columns)
    validate_schema(connection, allow_nba_com=True)
    install_or_validate_guard(connection)


def downgrade():
    raise RuntimeError("Automatic downgrade would discard append-only NBA evidence. Retain additive schema and evidence; removal requires a separately reviewed backup and migration.")
