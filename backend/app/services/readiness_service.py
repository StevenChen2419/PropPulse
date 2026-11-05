"""Uncached readiness: reconnect after transient failure and never start refresh."""
from sqlalchemy import text
from app.services.schema_readiness import SchemaPrerequisiteError, validate_database


def check_readiness(engine, settings):
    if settings.configuration_errors():
        return {"status": "not_ready", "reason": "configuration"}
    try:
        with engine.connect() as connection:
            # SET TRANSACTION is local to this transaction. Pool rollback clears it.
            connection.execute(text("SET TRANSACTION READ ONLY"))
            connection.execute(text("SET LOCAL statement_timeout = '2000ms'"))
            connection.execute(text("SET LOCAL lock_timeout = '1000ms'"))
            validate_database(connection)
    except SchemaPrerequisiteError as exc:
        return {"status": "not_ready", "reason": str(exc)}
    except Exception:
        # Driver errors can contain connection URLs/passwords/SQL. Never return them.
        return {"status": "not_ready", "reason": "database_unavailable"}
    return {"status": "ready"}
