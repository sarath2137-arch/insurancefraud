import os

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker


def normalize_database_url(database_url: str) -> str:
    """Use psycopg 3 for plain PostgreSQL URLs while preserving other URLs."""
    url = make_url(database_url)
    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+psycopg")
    return url.render_as_string(hide_password=False)


def create_database_engine(database_url: str):
    normalized_url = normalize_database_url(database_url)
    is_sqlite = make_url(normalized_url).get_backend_name() == "sqlite"
    options = {"pool_pre_ping": True}
    if is_sqlite:
        options["connect_args"] = {"check_same_thread": False}
    else:
        options.update(
            pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
            max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "5")),
            pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "30")),
            pool_recycle=int(os.getenv("DB_POOL_RECYCLE", "1800")),
        )
    return create_engine(normalized_url, **options)


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./insurance.db")
engine = create_database_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
