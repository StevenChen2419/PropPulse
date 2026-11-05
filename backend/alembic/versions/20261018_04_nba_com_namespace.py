"""Add NBA.com to the existing append-only evidence namespace.

Revision ID: 20261018_04
Revises: 20261017_03

No observations, player links, indexes or append-only guards are rewritten.
"""
import importlib.util
from pathlib import Path

from alembic import op
import sqlalchemy as sa

revision = "20261018_04"
down_revision = "20261017_03"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        raise RuntimeError("NBA namespace migration requires PostgreSQL transactional DDL")
    path = Path(__file__).with_name("20261017_03_nba_evidence.py")
    spec = importlib.util.spec_from_file_location("nba_evidence_revision03", path)
    previous = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(previous)
    previous.validate_schema(connection, allow_nba_com=True)
    # Validate (never repair) the existing append-only guard.
    guard_exists = connection.execute(sa.text("""SELECT EXISTS (
        SELECT 1 FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname=current_schema() AND c.relname='nba_evidence_records'
        AND t.tgname='trg_nba_evidence_append_only' AND NOT t.tgisinternal)""")).scalar_one()
    if not guard_exists:
        previous.fail("missing evidence append-only guard")
    previous.install_or_validate_guard(connection)
    checks = {item["name"]: item["sqltext"] for item in sa.inspect(connection).get_check_constraints(previous.TABLE)}
    expected = "provider IN ('espn', 'nba_com') AND sport = 'NBA'"
    if previous.normalized(checks["ck_nba_evidence_namespace"]) != previous.normalized(expected):
        op.drop_constraint("ck_nba_evidence_namespace", previous.TABLE, type_="check")
        op.create_check_constraint("ck_nba_evidence_namespace", previous.TABLE, expected)
    previous.validate_schema(connection, allow_nba_com=True)


def downgrade():
    raise RuntimeError("Automatic downgrade could invalidate retained NBA.com evidence; a separately reviewed migration is required.")
