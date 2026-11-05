"""Add authoritative event identity without linking or rewriting existing props.

Revision ID: 20261014_02
Revises: 20261014_01
"""
import re

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "20261014_02"
down_revision = "20261014_01"
branch_labels = None
depends_on = None

# Freeze prerequisites here: future model changes must not redefine adoption.
BASELINE = {
    "players": "id name team team_abbr sport position age jersey_number updated_at",
    "props": "id player_id prop_type line line_24h_ago over_odds under_odds sportsbook odds_event_id odds_sport_key odds_last_seen_at game_time opponent is_home is_active popularity_count created_at",
    "prop_books": "id prop_id sportsbook line over_odds under_odds provider_bookmaker_key provider_title provider_observed_at ingested_at updated_at",
    "prop_book_snapshots": "id prop_id sportsbook line over_odds under_odds captured_at",
    "player_game_logs": "id player_id sport external_game_id game_date opponent is_home stats source created_at updated_at",
    "users": "id email hashed_password username fav_sports fav_players fav_prop_types created_at",
    "interactions": "id user_id prop_id action created_at",
    "saved_props": "id user_id prop_id saved_at",
    "slips": "id user_id status created_at",
    "slip_items": "id slip_id prop_id side sportsbook line",
    "fatigue_scores": "id player_id fatigue_score workload_score back_to_back games_in_7d rolling_minutes_7d minutes_trend performance_volatility risk_flags shap_reasons scored_at",
    "rankings": "id prop_id user_id final_score user_affinity player_affinity prop_type_affinity popularity line_movement fatigue_edge reasons ranked_at",
}
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


def fail(detail):
    raise RuntimeError("Event identity schema is incomplete or incompatible: " + detail + ". No automatic repair or backfill is performed.")


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


def install_or_validate_guard(connection):
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
    if not functions and not triggers:
        connection.execute(sa.text("CREATE FUNCTION guard_prop_event_identity() RETURNS trigger LANGUAGE plpgsql AS $guard$\n" + GUARD_BODY + "\n$guard$"))
        connection.execute(sa.text("CREATE TRIGGER trg_props_event_identity BEFORE UPDATE OF event_id ON props FOR EACH ROW EXECUTE FUNCTION guard_prop_event_identity()"))
        return
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


def upgrade():
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        raise RuntimeError("Event identity migration requires PostgreSQL transactional DDL")
    inspector = sa.inspect(connection)
    tables = set(inspector.get_table_names())
    if not set(BASELINE).issubset(tables):
        fail("missing baseline application tables")
    for table, required in BASELINE.items():
        columns = {item["name"] for item in inspector.get_columns(table)}
        if not set(required.split()).issubset(columns):
            fail("missing baseline columns in " + table)
    has_events = "events" in tables
    has_link = "event_id" in {column["name"] for column in inspector.get_columns("props")}
    if has_events != has_link:
        fail("only one of events and props.event_id exists")
    if not has_events:
        op.create_table("events", sa.Column("id", UUID(as_uuid=False), primary_key=True),
            *(sa.Column(name, sa.String(), nullable=False) for name in ("provider", "provider_event_id", "sport_key", "home_team", "away_team")),
            sa.Column("scheduled_start_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("provider", "sport_key", "provider_event_id", name="uq_events_provider_sport_event"),
            *(sa.CheckConstraint(expression, name=name) for name, expression in CHECKS.items()))
        op.create_index("ix_events_sport_start", "events", ["sport_key", "scheduled_start_at"])
        op.add_column("props", sa.Column("event_id", UUID(as_uuid=False), nullable=True))
        op.create_foreign_key("fk_props_event_id_events", "props", "events", ["event_id"], ["id"], ondelete="RESTRICT")
        op.create_index("ix_props_event_id", "props", ["event_id"])
    validate_schema(sa.inspect(connection))
    install_or_validate_guard(connection)


def downgrade():
    raise RuntimeError("Automatic downgrade would discard event identities or weaken link protection. Roll back application code while retaining additive schema and data; removal requires a separately reviewed backup and migration.")
