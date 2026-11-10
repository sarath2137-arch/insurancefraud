from pathlib import Path
import sys

import pytest
from sqlalchemy import create_engine, inspect, text


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

alembic = pytest.importorskip("alembic")
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402


def test_initial_migration_preserves_legacy_claims_and_adds_missing_columns(tmp_path, monkeypatch):
    database_path = tmp_path / "legacy.db"
    legacy_engine = create_engine(f"sqlite:///{database_path}")
    with legacy_engine.begin() as connection:
        connection.execute(text("CREATE TABLE claims (id INTEGER PRIMARY KEY, claim_id VARCHAR(64))"))
        connection.execute(text("INSERT INTO claims (id, claim_id) VALUES (1, 'keep-this-claim')"))
    legacy_engine.dispose()

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    command.upgrade(config, "head")

    migrated_engine = create_engine(f"sqlite:///{database_path}")
    try:
        with migrated_engine.connect() as connection:
            claim = connection.execute(
                text("SELECT id, claim_id, provider_id FROM claims WHERE id = 1")
            ).one()
            assert tuple(claim) == (1, "keep-this-claim", None)
        columns = {column["name"] for column in inspect(migrated_engine).get_columns("claims")}
        assert {"id", "claim_id", "provider_id"}.issubset(columns)
        assert inspect(migrated_engine).has_table("users")
        assert inspect(migrated_engine).has_table("fraud_predictions")
    finally:
        migrated_engine.dispose()
