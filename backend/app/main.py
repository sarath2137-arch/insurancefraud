import os
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from .models.user import User
from .routes import auth, blockchain, claims, fraud_detection, reports
from .services.fraud_service import _load_dnn, _load_provider_features
from .utils.database import SessionLocal, engine
from .utils.security import get_jwt_secret, hash_password


def cors_origins_from_environment():
    """Return a strict allowlist; credentials are never enabled for wildcard origins."""
    configured = os.getenv("CORS_ORIGINS")
    origins = (
        [origin.strip() for origin in configured.split(",") if origin.strip()]
        if configured is not None
        else ["http://localhost:5173"]
    )
    if not origins:
        raise RuntimeError("CORS_ORIGINS must contain at least one allowed origin.")
    for origin in origins:
        parsed = urlparse(origin)
        if (
            "*" in origin
            or parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            raise RuntimeError("CORS_ORIGINS must contain exact HTTP(S) origins, not wildcard URLs or paths.")
    return list(dict.fromkeys(origins))


app = FastAPI(title="Medical Insurance Fraud Detection API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins_from_environment(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(auth.router)
app.include_router(claims.router)
app.include_router(fraud_detection.router)
app.include_router(blockchain.router)
app.include_router(reports.router)


@app.on_event("startup")
def startup():
    # Schema changes are applied explicitly with `alembic upgrade head`.
    get_jwt_secret()
    db = SessionLocal()
    try:
        seed_development_admin(db)
    finally:
        db.close()


def seed_development_admin(db):
    """Optionally bootstrap an administrator from operator-supplied credentials."""
    if os.getenv("SEED_DEVELOPMENT_ADMIN", "false").strip().lower() != "true":
        return None
    email = os.getenv("SEED_ADMIN_EMAIL", "").strip()
    password = os.getenv("SEED_ADMIN_PASSWORD", "")
    if not email or not password:
        raise RuntimeError("SEED_ADMIN_EMAIL and SEED_ADMIN_PASSWORD are required when administrator seeding is enabled.")
    if len(password) < 16:
        raise RuntimeError("SEED_ADMIN_PASSWORD must contain at least 16 characters.")
    if db.query(User).filter_by(email=email).first():
        return None
    user = User(email=email, full_name="System Administrator", password_hash=hash_password(password), role="system_admin")
    db.add(user)
    db.commit()
    return user


@app.get("/health")
@app.get("/health/live")
def health():
    return {"status": "ok"}


@app.get("/health/ready")
def readiness():
    checks = {"database": False, "model": False, "provider_features": False}
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception:
        pass
    try:
        _, _, feature_columns = _load_dnn()
        features = _load_provider_features()
        if features.index.size and set(feature_columns).issubset(features.columns):
            checks["model"] = True
            checks["provider_features"] = True
    except Exception:
        pass
    if not all(checks.values()):
        raise HTTPException(status_code=503, detail={"status": "not_ready", "checks": checks})
    return {"status": "ready", "checks": checks}
