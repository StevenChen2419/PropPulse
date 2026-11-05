"""Add nullable offer provenance without inventing provider observations.

Revision ID: 20261014_01
Revises: None (initial legacy-schema adoption)
"""

from alembic import op
import sqlalchemy as sa


revision = "20261014_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    tables = set(inspector.get_table_names())
    if "prop_books" not in tables:
        # This is the initial adoption of versioning by a create_all application.
        # Bootstrap only an empty database; do not guess at repairing partial ones.
        if tables - {"alembic_version"}:
            raise RuntimeError(
                "prop_books is missing from a nonempty database. Inspect and repair "
                "the legacy schema before migration; no tables were replaced."
            )
        from app.database import Base
        from app import models  # noqa: F401: register application tables

        Base.metadata.create_all(bind=connection)
        inspector = sa.inspect(connection)

    columns = {column["name"] for column in inspector.get_columns("prop_books")}
    if "updated_at" not in columns:
        raise RuntimeError("Legacy prop_books.updated_at is missing; inspect schema before retrying.")
    additions = (
        sa.Column("provider_bookmaker_key", sa.String(), nullable=True),
        sa.Column("provider_title", sa.String(), nullable=True),
        sa.Column("provider_observed_at", sa.DateTime(), nullable=True),
        sa.Column("ingested_at", sa.DateTime(), nullable=True),
    )
    for column in additions:
        if column.name not in columns:
            op.add_column("prop_books", column)

    # updated_at historically represented local ingestion, not provider observation.
    # Retain its value and meaning; NULL provider fields must stay unknown.
    connection.execute(sa.text(
        "UPDATE prop_books SET ingested_at = updated_at WHERE ingested_at IS NULL"
    ))


def downgrade():
    raise RuntimeError(
        "Automatic downgrade would discard offer provenance. Revert application "
        "code while retaining these nullable columns and the revision marker. "
        "Any schema removal requires a separately reviewed backup and migration."
    )
