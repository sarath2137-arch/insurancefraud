"""Read-only checks against the real Kaggle CSVs; no fixture data is generated."""

from pathlib import Path
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ML_ROOT = PROJECT_ROOT / "ml"
RAW_DATA = ML_ROOT / "data" / "raw"
sys.path.insert(0, str(ML_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from preprocessing.preprocess import (  # noqa: E402
    build_preprocessor,
    calculate_class_weights,
    load_provider_dataset,
    split_provider_data,
)
from app.services.fraud_service import _load_provider_features, predict_provider_level  # noqa: E402


REQUIRED_FILES = (
    "Train-1542865627584.csv",
    "Train_Beneficiarydata-1542865627584.csv",
    "Train_Inpatientdata-1542865627584.csv",
    "Train_Outpatientdata-1542865627584.csv",
)


@pytest.fixture(scope="module")
def provider_data():
    if not all((RAW_DATA / name).is_file() for name in REQUIRED_FILES):
        pytest.skip("Real Kaggle training CSV files are not available in ml/data/raw.")
    return load_provider_dataset(RAW_DATA)


def test_provider_features_are_one_row_per_labelled_provider(provider_data):
    features, labels = provider_data
    assert len(features) == 5410
    assert len(features.columns) == 97
    assert features.index.name == "Provider"
    assert features.index.is_unique
    assert features.index.equals(labels.index)
    assert labels.value_counts().to_dict() == {0: 4904, 1: 506}


def test_provider_ids_targets_and_claim_ids_are_not_features(provider_data):
    features, _ = provider_data
    assert "Provider" not in features.columns
    assert "PotentialFraud" not in features.columns
    assert all("BeneID" not in col and "ClaimID" not in col for col in features.columns)
    assert all("Physician" not in col for col in features.columns)
    assert all(features.dtypes.apply(lambda dtype: dtype.kind in "ifub"))


def test_provider_level_splits_are_stratified_and_disjoint(provider_data):
    features, labels = provider_data
    splits = split_provider_data(features, labels)
    ids = {name: set(split[0].index) for name, split in splits.items()}
    assert not ids["train"] & ids["validation"]
    assert not ids["train"] & ids["test"]
    assert not ids["validation"] & ids["test"]
    assert len(splits["train"][0]) == 3787
    assert sorted(len(splits[name][0]) for name in ("validation", "test")) == [811, 812]
    for _, split_labels in splits.values():
        assert set(split_labels.unique()) == {0, 1}


def test_preprocessor_is_fit_on_train_then_transforms_other_splits(provider_data):
    features, labels = provider_data
    splits = split_provider_data(features, labels)
    X_train = splits["train"][0]
    X_val = splits["validation"][0]
    X_test = splits["test"][0]
    preprocessor = build_preprocessor(features.columns.tolist())
    train_matrix = preprocessor.fit_transform(X_train)
    val_matrix = preprocessor.transform(X_val)
    test_matrix = preprocessor.transform(X_test)
    assert train_matrix.shape[1] == val_matrix.shape[1] == test_matrix.shape[1]
    assert list(preprocessor.feature_names_in_) == features.columns.tolist()


def test_class_weights_are_computed_from_training_provider_labels(provider_data):
    features, labels = provider_data
    y_train = split_provider_data(features, labels)["train"][1]
    weights = calculate_class_weights(y_train)
    assert set(weights) == {0, 1}
    assert weights[1] > weights[0]
    assert weights[0] == pytest.approx(len(y_train) / (2 * int((y_train == 0).sum())))
    assert weights[1] == pytest.approx(len(y_train) / (2 * int((y_train == 1).sum())))


def test_unknown_provider_id_is_rejected(provider_data):
    with pytest.raises(ValueError, match="No provider-level feature data"):
        predict_provider_level(provider_id="NOT_A_REAL_PROVIDER")


def test_valid_provider_id_runs_saved_provider_dnn(provider_data):
    features, _ = provider_data
    result = predict_provider_level(provider_id=str(features.index[0]))
    assert set(result) == {"fraud_probability", "risk_score", "prediction", "threshold"}
    assert 0 <= result["fraud_probability"] <= 1
    assert result["risk_score"] == pytest.approx(result["fraud_probability"] * 100)
    assert result["prediction"] in (0, 1)
    assert result["threshold"] == pytest.approx(0.50)


def test_packaged_features_and_predictions_match_source_pipeline(provider_data):
    source_features, _ = provider_data
    packaged_features = _load_provider_features()
    import pandas as pd

    pd.testing.assert_frame_equal(
        source_features,
        packaged_features,
        check_dtype=False,
        check_exact=False,
        rtol=1e-14,
        atol=1e-14,
    )
    provider_id = str(source_features.index[0])
    source_prediction = predict_provider_level(feature_vector=source_features.loc[provider_id].to_dict())
    packaged_prediction = predict_provider_level(provider_id=provider_id)
    assert packaged_prediction == pytest.approx(source_prediction, rel=1e-6, abs=1e-7)
