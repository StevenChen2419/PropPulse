from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.config import settings

try:
    engine_options = {"pool_timeout": 5, "connect_args": {"connect_timeout": 3}} \
        if settings.DATABASE_URL.startswith("postgresql") else {}
    engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, **engine_options)
except Exception:
    raise RuntimeError("Invalid database configuration") from None
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
