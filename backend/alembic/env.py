"""Run explicit schema migrations without starting the application lifespan."""

from alembic import context
from sqlalchemy import create_engine, pool

from app.database import Base
from app import models  # noqa: F401: register complete application metadata


def run_migrations(connection):
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError(
        "This additive migration requires online schema inspection. "
        "Review the revision source and run upgrade against the intended database; "
        "offline --sql generation is not supported."
    )
elif context.config.attributes.get("connection") is not None:
    # Integration tests and controlled callers may supply an isolated connection.
    run_migrations(context.config.attributes["connection"])
else:
    from app.config import settings

    # Do not copy the URL into Alembic's interpolated config or log it.
    migration_engine = create_engine(settings.DATABASE_URL, poolclass=pool.NullPool)
    try:
        with migration_engine.connect() as connection:
            run_migrations(connection)
    finally:
        migration_engine.dispose()
