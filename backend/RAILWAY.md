# Railway backend deployment

## Build

Configure the Railway backend service with the repository root (`/`) as its source/build context and `backend/Dockerfile` as the Dockerfile path. The Dockerfile expects a repository-root context. It copies only `backend/app`, Alembic files, the two DNN artifacts, and `ml/data/provider_features.csv`; `.dockerignore` excludes the raw Kaggle tables, notebooks, local environments, frontend, and blockchain dependencies. Commit the two specifically unignored DNN artifact files and the provider feature artifact before using Git-based builds.

Generate or refresh the minimized feature table when the source training tables are available:

```powershell
python ml\preprocessing\export_provider_features.py
```

This uses the existing feature engineering pipeline, writes only provider IDs and numeric features, and omits fraud labels. It does not train or modify the DNN. `tests/test_provider_ml.py` compares the generated feature values and DNN predictions with the original raw-table pipeline.

The image test target loads the model, preprocessor, and feature table and performs inference in the deployment runtime:

```powershell
docker build --target test -f backend\Dockerfile -t insurance-backend-test .
docker build -f backend\Dockerfile -t insurance-backend .
```

The production image command binds Uvicorn to `0.0.0.0` and uses Railway's `PORT`, defaulting to `8000` for local runs.

## Environment

Set Railway variables in the backend service configuration. Required values are `JWT_SECRET` (at least 32 random bytes), `DATABASE_URL` (reference the Railway PostgreSQL service URL), and `CORS_ORIGINS` (the exact Vercel frontend origin, comma-separated if more than one). Keep `SEED_DEVELOPMENT_ADMIN=false` in production. Do not put server secrets in frontend variables.

The SQLAlchemy setup converts `postgresql://` to `postgresql+psycopg://`, uses psycopg 3, enables `pool_pre_ping`, and uses a bounded pool. Optional pool variables are `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`, and `DB_POOL_RECYCLE`.

## Schema migrations

Migrations are not run by application startup. For a new or existing database, run this once as a deployment release/pre-deploy command, using the backend image and the same Railway `DATABASE_URL`:

```powershell
python -m alembic -c alembic.ini upgrade head
```

If executing from the repository root rather than the backend working directory:

```powershell
python -m alembic -c backend\alembic.ini upgrade head
```

Revision `0001_safe_schema_baseline` creates missing tables and adds known missing nullable columns. It does not drop or replace tables or records. Back up an existing production database before applying migrations. A downgrade is deliberately unsupported for this baseline; create a reviewed forward migration for future schema changes.

## Health endpoints

- `GET /health` and `GET /health/live` are liveness checks and do not disclose backend internals.
- `GET /health/ready` checks database connectivity, model/preprocessor loading, and provider feature availability. It can take longer the first time TensorFlow loads.
