import os
import sys
from pathlib import Path

import jwt
import pytest
import bcrypt
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.main import seed_development_admin, startup  # noqa: E402
from app.models.user import User  # noqa: E402
from app.routes import auth as auth_routes  # noqa: E402
from app.routes.auth import router  # noqa: E402
from app.utils.database import Base, get_db  # noqa: E402
from app.utils.security import create_token, get_jwt_secret  # noqa: E402


@pytest.fixture
def database():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def client(database, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-only-random-secret-material-0123456789")
    # Passlib 1.7's bcrypt backend self-check is incompatible with bcrypt 5.x.
    # Keep API tests runnable in that environment; the pinned backend environment
    # exercises the real hash and verification calls.
    if int(bcrypt.__version__.split(".")[0]) >= 5:
        monkeypatch.setattr(auth_routes, "hash_password", lambda value: f"test-hash:{value}")
        monkeypatch.setattr(auth_routes, "verify_password", lambda value, hashed: hashed == f"test-hash:{value}")
    app = FastAPI()
    app.include_router(router)

    def override_db():
        yield database

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize("role", ["insurance_admin", "system_admin"])
def test_public_registration_ignores_privileged_role(client, role):
    response = client.post(
        "/api/auth/register",
        json={
            "email": "new.user@example.com",
            "full_name": "New User",
            "password": "safe-password-123",
            "role": role,
        },
    )

    assert response.status_code == 200
    assert response.json()["role"] == "claim_officer"


def test_registered_user_can_still_log_in_and_use_jwt(client):
    registration = client.post(
        "/api/auth/register",
        json={"email": "login.user@example.com", "full_name": "Login User", "password": "user-password-123"},
    )
    assert registration.status_code == 200

    login = client.post(
        "/api/auth/login",
        json={"email": "login.user@example.com", "password": "user-password-123"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_inactive_user_cannot_log_in(client, database):
    database.add(
        User(
            email="inactive@example.com",
            full_name="Inactive User",
            password_hash="test-hash:inactive-password",
            role="system_admin",
            is_active=False,
        )
    )
    database.commit()

    response = client.post(
        "/api/auth/login",
        json={"email": "inactive@example.com", "password": "inactive-password"},
    )

    assert response.status_code == 401
    assert "access_token" not in response.json()


def test_only_system_admin_can_provision_privileged_roles(client, database):
    system_admin = User(
        email="sysadmin@example.com",
        full_name="System Admin",
        password_hash="test-hash:admin-test-password",
        role="system_admin",
    )
    officer = User(
        email="officer@example.com",
        full_name="Claim Officer",
        password_hash="test-hash:officer-test-password",
        role="claim_officer",
    )
    database.add_all([system_admin, officer])
    database.commit()
    database.refresh(system_admin)
    database.refresh(officer)

    payload = {
        "email": "provisioned@example.com",
        "full_name": "Provisioned Admin",
        "password": "provisioned-test-password",
        "role": "insurance_admin",
    }
    denied = client.post(
        "/api/auth/provision",
        json=payload,
        headers={"Authorization": f"Bearer {create_token(officer.id)}"},
    )
    assert denied.status_code == 403

    accepted = client.post(
        "/api/auth/provision",
        json=payload,
        headers={"Authorization": f"Bearer {create_token(system_admin.id)}"},
    )
    assert accepted.status_code == 201
    assert accepted.json()["role"] == "insurance_admin"


def test_jwt_secret_is_required_and_must_be_at_least_32_bytes(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="JWT_SECRET must be configured"):
        get_jwt_secret()

    monkeypatch.setenv("JWT_SECRET", "too-short")
    with pytest.raises(RuntimeError, match="at least 32 bytes"):
        get_jwt_secret()


def test_startup_fails_before_database_setup_when_jwt_secret_is_missing(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)

    with pytest.raises(RuntimeError, match="JWT_SECRET must be configured"):
        startup()


def test_tokens_use_the_configured_secret(monkeypatch):
    configured_secret = "test-only-random-secret-material-0123456789"
    monkeypatch.setenv("JWT_SECRET", configured_secret)

    token = create_token(42)
    decoded = jwt.decode(token, configured_secret, algorithms=["HS256"])

    assert decoded["sub"] == "42"


def test_development_admin_seed_is_disabled_by_default(database, monkeypatch):
    for key in ("SEED_DEVELOPMENT_ADMIN", "SEED_ADMIN_EMAIL", "SEED_ADMIN_PASSWORD"):
        monkeypatch.delenv(key, raising=False)

    assert seed_development_admin(database) is None
    assert database.query(User).count() == 0


def test_opt_in_admin_seed_uses_operator_supplied_credentials(database, monkeypatch):
    if int(bcrypt.__version__.split(".")[0]) >= 5:
        monkeypatch.setattr("app.main.hash_password", lambda value: f"test-hash:{value}")
    monkeypatch.setenv("SEED_DEVELOPMENT_ADMIN", "true")
    monkeypatch.setenv("SEED_ADMIN_EMAIL", "bootstrap@example.com")
    monkeypatch.setenv("SEED_ADMIN_PASSWORD", "operator-supplied-long-password")

    seeded = seed_development_admin(database)

    assert seeded.email == "bootstrap@example.com"
    assert seeded.role == "system_admin"
    assert seeded.password_hash != os.environ["SEED_ADMIN_PASSWORD"]
    assert database.query(User).count() == 1


def test_opt_in_admin_seed_rejects_missing_or_short_password(database, monkeypatch):
    monkeypatch.setenv("SEED_DEVELOPMENT_ADMIN", "true")
    monkeypatch.setenv("SEED_ADMIN_EMAIL", "bootstrap@example.com")
    monkeypatch.setenv("SEED_ADMIN_PASSWORD", "short")

    with pytest.raises(RuntimeError, match="at least 16 characters"):
        seed_development_admin(database)

    assert database.query(User).count() == 0
