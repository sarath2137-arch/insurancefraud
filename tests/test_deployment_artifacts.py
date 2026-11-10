"""Checks the packaged deployment artifacts without requiring source CSVs."""

from pathlib import Path
import sys

import numpy as np


BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.fraud_service import (  # noqa: E402
    DNN_MODEL_PATH,
    DNN_PREPROCESSOR_PATH,
    _load_dnn,
    _load_provider_features,
    predict_provider_level,
)


def test_deployment_model_preprocessor_and_features_load_and_predict():
    assert DNN_MODEL_PATH.is_file()
    assert DNN_PREPROCESSOR_PATH.is_file()
    model, preprocessor, feature_columns = _load_dnn()
    features = _load_provider_features()

    assert features.index.is_unique
    assert features.index.size > 0
    assert list(features.columns) == list(feature_columns)
    transformed = preprocessor.transform(features.iloc[[0]][feature_columns])
    probability = float(model.predict(np.asarray(transformed, dtype=np.float32), verbose=0).reshape(-1)[0])
    result = predict_provider_level(provider_id=str(features.index[0]))

    assert 0.0 <= probability <= 1.0
    assert result["fraud_probability"] == probability
    assert result["prediction"] in (0, 1)
