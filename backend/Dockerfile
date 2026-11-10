FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app/backend

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/alembic.ini ./alembic.ini
COPY backend/migrations ./migrations
COPY ml/models/medical_fraud_dnn.keras /app/ml/models/medical_fraud_dnn.keras
COPY ml/models/medical_fraud_dnn_preprocessor.joblib /app/ml/models/medical_fraud_dnn_preprocessor.joblib
COPY ml/data/provider_features.csv /app/ml/data/provider_features.csv

EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

# The test target verifies artifacts and application behavior in the runtime
# image environment; it is not used as the production Railway image.
FROM runtime AS test
RUN python -m pip install --no-cache-dir pytest
COPY ml/preprocessing /app/ml/preprocessing
COPY tests /app/tests
RUN PYTHONPATH=/app/backend:/app/ml python -m pytest -q /app/tests
