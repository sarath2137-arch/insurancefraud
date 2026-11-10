from pathlib import Path
import sys

from sqlalchemy.pool import QueuePool


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.utils.database import create_database_engine, normalize_database_url  # noqa: E402


def test_plain_railway_postgresql_url_uses_psycopg3():
    normalized = normalize_database_url("postgresql://user:secret@db.example:5432/insurance?sslmode=require")
    assert normalized.startswith("postgresql+psycopg://")
    assert "sslmode=require" in normalized


def test_sqlite_url_is_preserved_for_local_development():
    assert normalize_database_url("sqlite:///./insurance.db") == "sqlite:///./insurance.db"


def test_postgresql_engine_uses_pre_ping_and_bounded_pool():
    engine = create_database_engine("postgresql+psycopg://user:secret@db.example:5432/insurance")
    try:
        assert engine.url.drivername == "postgresql+psycopg"
        assert isinstance(engine.pool, QueuePool)
        assert engine.pool._pre_ping is True
        assert engine.pool.size() == 5
        assert engine.pool._max_overflow == 5
    finally:
        engine.dispose()


def test_sqlite_engine_enables_health_checks_and_threaded_dev_access():
    engine = create_database_engine("sqlite://")
    try:
        assert engine.pool._pre_ping is True
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT 1").scalar_one() == 1
    finally:
        engine.dispose()
