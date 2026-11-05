"""Preserve exact saved selections and original offer observations.

Existing bookmarks and slip identities remain unchanged. No historical price backfill.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261022_05"
down_revision = "20261018_04"
branch_labels = None
depends_on = None


def upgrade():
    # Initial legacy adoption bootstraps current metadata on an empty database.
    # Accept those already-present columns without rewriting any saved evidence.
    additions = {"saved_props": [("sportsbook", sa.String), ("line", sa.Float), ("side", sa.String)]}
    for table in ("saved_props", "slip_items"):
        additions.setdefault(table, []).extend([("original_odds", sa.Float), ("original_observed_at", sa.DateTime)])
    for table, fields in additions.items():
        columns = {column["name"]: column for column in sa.inspect(op.get_bind()).get_columns(table)}
        for name, kind in fields:
            if name not in columns:
                op.add_column(table, sa.Column(name, kind(), nullable=True))
            elif not isinstance(columns[name]["type"], kind) or not columns[name]["nullable"]:
                raise RuntimeError("Incompatible saved selection schema; inspect before retrying")


def downgrade():
    # Exact rows cannot become anonymous generic bookmarks on rollback.
    op.execute(sa.text("DELETE FROM saved_props WHERE side IS NOT NULL"))
    for table in ("saved_props", "slip_items"):
        op.drop_column(table, "original_observed_at")
        op.drop_column(table, "original_odds")
    for name in ("side", "line", "sportsbook"):
        op.drop_column("saved_props", name)
