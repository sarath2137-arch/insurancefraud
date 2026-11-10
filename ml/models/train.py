"""Train the provider-level DNN from the four real Kaggle training tables."""

from pathlib import Path
import sys

import joblib
import numpy as np
import pandas as pd
import tensorflow as tf
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

ML_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ML_ROOT))
from preprocessing.preprocess import (  # noqa: E402
    TARGET,
    build_preprocessor,
    calculate_class_weights,
    load_provider_dataset,
    split_provider_data,
)
from models.dnn_model import build  # noqa: E402

MODEL_PATH = ML_ROOT / "models" / "medical_fraud_dnn.keras"
PREPROCESSOR_PATH = ML_ROOT / "models" / "medical_fraud_dnn_preprocessor.joblib"
THRESHOLD = 0.50


def _class_distribution(labels):
    counts = labels.value_counts().reindex([0, 1], fill_value=0)
    return {"No (0)": int(counts.loc[0]), "Yes (1)": int(counts.loc[1])}


def main():
    features, labels = load_provider_dataset()
    if len(features) != 5410:
        raise ValueError(f"Expected 5,410 labelled providers from the supplied training file; found {len(features)}.")
    if features.index.name != "Provider" or not features.index.is_unique:
        raise ValueError("Feature rows must be uniquely indexed by Provider.")
    if TARGET in features.columns or "Provider" in features.columns:
        raise ValueError("Provider and PotentialFraud must not be model input columns.")
    forbidden_names = ("BeneID", "ClaimID", "AttendingPhysician", "OperatingPhysician", "OtherPhysician")
    if any(any(token in col for token in forbidden_names) for col in features.columns):
        raise ValueError("An identifier or raw physician ID was included as a model feature.")

    splits = split_provider_data(features, labels)
    (X_train, y_train) = splits["train"]
    (X_val, y_val) = splits["validation"]
    (X_test, y_test) = splits["test"]
    train_ids, val_ids, test_ids = set(X_train.index), set(X_val.index), set(X_test.index)
    if train_ids & val_ids or train_ids & test_ids or val_ids & test_ids:
        raise AssertionError("Provider leakage detected across train/validation/test splits.")

    feature_columns = features.columns.tolist()
    preprocessor = build_preprocessor(feature_columns)
    # Fit only on training providers. Validation and test only receive transform().
    X_train_t = preprocessor.fit_transform(X_train)
    X_val_t = preprocessor.transform(X_val)
    X_test_t = preprocessor.transform(X_test)
    X_train_t = np.asarray(X_train_t, dtype=np.float32)
    X_val_t = np.asarray(X_val_t, dtype=np.float32)
    X_test_t = np.asarray(X_test_t, dtype=np.float32)

    class_weights = calculate_class_weights(y_train)
    print(f"Train providers: {len(X_train)}; classes: {_class_distribution(y_train)}")
    print(f"Validation providers: {len(X_val)}; classes: {_class_distribution(y_val)}")
    print(f"Test providers: {len(X_test)}; classes: {_class_distribution(y_test)}")
    print(f"Engineered provider feature count: {len(feature_columns)}")
    print(f"Model input feature count after preprocessing: {X_train_t.shape[1]}")
    print(f"Provider feature names: {feature_columns}")
    print(f"Training class weights (computed from y_train): {class_weights}")

    model = build(X_train_t.shape[1])
    early_stopping = tf.keras.callbacks.EarlyStopping(
        monitor="val_auc", mode="max", patience=10, restore_best_weights=True
    )
    model.fit(
        X_train_t,
        y_train.to_numpy(dtype=np.float32),
        validation_data=(X_val_t, y_val.to_numpy(dtype=np.float32)),
        epochs=100,
        batch_size=64,
        class_weight=class_weights,
        callbacks=[early_stopping],
        verbose=2,
    )

    probabilities = model.predict(X_test_t, verbose=0).reshape(-1)
    predictions = (probabilities >= THRESHOLD).astype(np.int32)
    results = {
        "threshold": THRESHOLD,
        "Accuracy": accuracy_score(y_test, predictions),
        "Precision": precision_score(y_test, predictions, zero_division=0),
        "Recall": recall_score(y_test, predictions, zero_division=0),
        "F1-score": f1_score(y_test, predictions, zero_division=0),
        "ROC-AUC": roc_auc_score(y_test, probabilities),
        "Confusion Matrix (rows=true [0,1], columns=predicted [0,1])": confusion_matrix(
            y_test, predictions, labels=[0, 1]
        ).tolist(),
    }

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    model.save(MODEL_PATH)
    joblib.dump(
        {"preprocessor": preprocessor, "feature_columns": feature_columns},
        PREPROCESSOR_PATH,
    )
    print(f"Saved DNN model: {MODEL_PATH}")
    print(f"Saved preprocessor and feature order: {PREPROCESSOR_PATH}")
    print("Held-out provider test results:")
    for name, value in results.items():
        print(f"{name}: {value}")


if __name__ == "__main__":
    main()
