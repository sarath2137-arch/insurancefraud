"""Claim-level heuristic and separately callable provider-level DNN inference."""

from functools import lru_cache
from collections.abc import Mapping
import os
from pathlib import Path
import sys

import joblib
import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[3]
ML_ROOT = PROJECT_ROOT / "ml"
DNN_MODEL_PATH = ML_ROOT / "models" / "medical_fraud_dnn.keras"
DNN_PREPROCESSOR_PATH = ML_ROOT / "models" / "medical_fraud_dnn_preprocessor.joblib"
PROVIDER_DATA_DIR = ML_ROOT / "data" / "raw"
PROVIDER_FEATURES_PATH = ML_ROOT / "data" / "provider_features.csv"


@lru_cache(maxsize=1)
def _load_dnn():
    if not DNN_MODEL_PATH.is_file() or not DNN_PREPROCESSOR_PATH.is_file():
        raise RuntimeError("Provider-level DNN artifacts are missing. Train the model first.")
    import tensorflow as tf

    artifact = joblib.load(DNN_PREPROCESSOR_PATH)
    if not isinstance(artifact, dict) or "preprocessor" not in artifact or "feature_columns" not in artifact:
        raise RuntimeError("The saved DNN preprocessing artifact has an unsupported format.")
    return tf.keras.models.load_model(DNN_MODEL_PATH), artifact["preprocessor"], artifact["feature_columns"]


def _legacy_score(data):
    """Existing claim-level heuristic; it is deliberately not passed to the provider DNN."""
    amount = min(data.claim_amount / 200000, 0.55)
    frequency = min(data.previous_claims / 20, 0.25)
    history = min(data.previous_claim_amount / 500000, 0.15)
    stay = (data.discharge_date - data.admission_date).days
    probability = min(0.97, 0.05 + amount + frequency + history + (0.08 if stay > 21 else 0))
    factors = []
    if data.claim_amount > 100000:
        factors.append("High claim amount compared with typical claims")
    if data.previous_claims >= 4:
        factors.append("Unusually frequent previous claims")
    if stay > 21:
        factors.append("Unusually long treatment duration")
    if data.previous_claim_amount > 200000:
        factors.append("High previous claim amount")
    return probability, factors


def predict_provider_level(provider_id=None, feature_vector=None, threshold=None):
    """Predict using a provider ID in the local source tables or an exact feature mapping.

    Claim submission supplies a canonical Provider ID which is matched to the existing
    provider feature pipeline. Individual claim fields are never passed to this model.
    """
    if (provider_id is None) == (feature_vector is None):
        raise ValueError("Supply exactly one of provider_id or feature_vector.")
    if provider_id is not None:
        if not isinstance(provider_id, str) or not provider_id.strip():
            raise ValueError("provider_id must be a non-empty Provider ID string.")
        ml_root = str(ML_ROOT)
        if ml_root not in sys.path:
            sys.path.insert(0, ml_root)
        provider_features = _load_provider_features()
        if provider_id not in provider_features.index:
            raise ValueError(f"No provider-level feature data available for Provider {provider_id!r}.")
        model, preprocessor, feature_columns = _load_dnn()
        row = provider_features.loc[[provider_id], feature_columns]
    else:
        model, preprocessor, feature_columns = _load_dnn()
        if not isinstance(feature_vector, Mapping):
            raise ValueError("feature_vector must be a mapping of exact provider feature names to values.")
        supplied = set(feature_vector)
        expected = set(feature_columns)
        if supplied != expected:
            missing = sorted(expected - supplied)
            extra = sorted(supplied - expected)
            raise ValueError(f"Provider feature vector mismatch; missing={missing}, extra={extra}.")
        row = pd.DataFrame([{name: feature_vector[name] for name in feature_columns}], columns=feature_columns)

    transformed = preprocessor.transform(row)
    if hasattr(transformed, "toarray"):
        transformed = transformed.toarray()
    probability = float(model.predict(np.asarray(transformed, dtype=np.float32), verbose=0).reshape(-1)[0])
    used_threshold = float(os.getenv("DNN_THRESHOLD", "0.50")) if threshold is None else float(threshold)
    if not 0 <= used_threshold <= 1:
        raise ValueError("DNN threshold must be between 0 and 1.")
    return {
        "fraud_probability": probability,
        "risk_score": probability * 100,
        "prediction": int(probability >= used_threshold),
        "threshold": used_threshold,
    }


@lru_cache(maxsize=1)
def _load_provider_features():
    """Load the minimized provider feature table, falling back to local raw data."""
    if PROVIDER_FEATURES_PATH.is_file():
        features = pd.read_csv(
            PROVIDER_FEATURES_PATH,
            index_col="Provider",
            dtype={"Provider": "string"},
        )
        features.index = features.index.astype(str)
        if not features.index.is_unique or features.columns.duplicated().any():
            raise RuntimeError("Provider feature artifact has duplicate identifiers or columns.")
        if not all(pd.api.types.is_numeric_dtype(dtype) for dtype in features.dtypes):
            raise RuntimeError("Provider feature artifact contains non-numeric features.")
        return features

    # Preserve the prior source-table workflow for local development when the
    # precomputed deployment artifact has not been generated.
    ml_root = str(ML_ROOT)
    if ml_root not in sys.path:
        sys.path.insert(0, ml_root)
    from preprocessing.preprocess import load_provider_dataset
    return load_provider_dataset(PROVIDER_DATA_DIR)[0]


def predict_details(data, model_name=None):
    """Claim-level endpoint scorer. Provider-level DNN use is intentionally rejected here."""
    selected_model = (model_name or os.getenv("FRAUD_MODEL", "heuristic")).strip().lower()
    if selected_model == "dnn":
        raise RuntimeError(
            "The DNN predicts provider-level risk. This claim-level API has no Provider ID/history; "
            "use predict_provider_level with a Provider ID or exact provider feature vector."
        )
    if selected_model not in ("heuristic", "baseline"):
        raise ValueError("Unknown claim-level model. Choose 'heuristic' or 'baseline'.")
    probability, factors = _legacy_score(data)
    threshold = float(os.getenv("FRAUD_THRESHOLD", "0.65"))
    label = "Potential Fraud" if probability >= threshold else "Low Risk"
    return {
        "fraud_probability": round(probability, 6),
        "risk_score": round(probability * 100, 1),
        "prediction": label,
        "threshold": threshold,
        "factors": factors,
        "model": selected_model,
    }


def predict(data):
    """Backward-compatible claim scoring, preserving the original heuristic contract."""
    probability, factors = _legacy_score(data)
    threshold = float(os.getenv("FRAUD_THRESHOLD", "0.65"))
    return (
        round(probability, 4),
        round(probability * 100, 1),
        "suspicious" if probability >= threshold else "legitimate",
        factors,
    )
