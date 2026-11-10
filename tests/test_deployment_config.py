from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient


BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app import main as main_module  # noqa: E402
from app.main import app, cors_origins_from_environment  # noqa: E402


def test_cors_defaults_to_local_frontend(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    assert cors_origins_from_environment() == ["http://localhost:5173"]


def test_cors_accepts_multiple_exact_origins(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://claims.example.com, https://preview.example.com")
    assert cors_origins_from_environment() == [
        "https://claims.example.com",
        "https://preview.example.com",
    ]


@pytest.mark.parametrize(
    "value",
    ["*", "https://*.example.com", "https://example.com/path", "ftp://example.com"],
)
def test_cors_rejects_wildcards_paths_and_non_http_origins(monkeypatch, value):
    monkeypatch.setenv("CORS_ORIGINS", value)
    with pytest.raises(RuntimeError, match=r"exact HTTP\(S\) origins"):
        cors_origins_from_environment()


def test_liveness_endpoint_does_not_depend_on_model_or_database(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-only-random-secret-material-0123456789")
    monkeypatch.setenv("SEED_DEVELOPMENT_ADMIN", "false")
    with TestClient(app) as client:
        response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_reports_checks_without_internal_details(monkeypatch):
    from contextlib import nullcontext
    import pandas as pd

    class Connection:
        def execute(self, _statement):
            return None

    class Engine:
        def connect(self):
            return nullcontext(Connection())

    monkeypatch.setattr(main_module, "engine", Engine())
    monkeypatch.setattr(main_module, "_load_dnn", lambda: (object(), object(), ["feature"]))
    monkeypatch.setattr(
        main_module,
        "_load_provider_features",
        lambda: pd.DataFrame([[1.0]], index=pd.Index(["provider"], name="Provider"), columns=["feature"]),
    )
    monkeypatch.setenv("JWT_SECRET", "test-only-random-secret-material-0123456789")
    monkeypatch.setenv("SEED_DEVELOPMENT_ADMIN", "false")
    with TestClient(app) as client:
        response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"database": True, "model": True, "provider_features": True},
    }
