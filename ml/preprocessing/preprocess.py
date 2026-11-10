"""Provider-level feature engineering for the Kaggle Medicare fraud tables."""

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.utils.class_weight import compute_class_weight


DATA_FILES = {
    "providers": "Train-1542865627584.csv",
    "beneficiaries": "Train_Beneficiarydata-1542865627584.csv",
    "inpatient": "Train_Inpatientdata-1542865627584.csv",
    "outpatient": "Train_Outpatientdata-1542865627584.csv",
}
PROVIDER_ID = "Provider"
TARGET = "PotentialFraud"
CHRONIC_COLUMNS = [
    "ChronicCond_Alzheimer", "ChronicCond_Heartfailure",
    "ChronicCond_KidneyDisease", "ChronicCond_Cancer",
    "ChronicCond_ObstrPulmonary", "ChronicCond_Depression",
    "ChronicCond_Diabetes", "ChronicCond_IschemicHeart",
    "ChronicCond_Osteoporasis", "ChronicCond_rheumatoidarthritis",
    "ChronicCond_stroke",
]
BENEFICIARY_NUMERIC = [
    "Age", "NoOfMonths_PartACov", "NoOfMonths_PartBCov",
    "IPAnnualReimbursementAmt", "IPAnnualDeductibleAmt",
    "OPAnnualReimbursementAmt", "OPAnnualDeductibleAmt",
    *CHRONIC_COLUMNS, "RenalDiseaseIndicator_numeric",
]
CLAIM_DROP_FEATURES = {
    PROVIDER_ID, TARGET, "BeneID", "ClaimID", "AttendingPhysician",
    "OperatingPhysician", "OtherPhysician",
}


def clean(frame):
    """Normalize Kaggle's literal NA markers and blank cells to pandas missing values."""
    return frame.replace({"NA": pd.NA, "N/A": pd.NA, "": pd.NA})


def _require_columns(frame, required, table_name):
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise ValueError(f"{table_name} is missing required columns: {', '.join(missing)}")


def _numeric(series):
    return pd.to_numeric(series, errors="coerce")


def _target_labels(provider_labels):
    _require_columns(provider_labels, [PROVIDER_ID, TARGET], "provider labels")
    if provider_labels[PROVIDER_ID].isna().any():
        raise ValueError("Provider labels contain a missing Provider ID.")
    if provider_labels[PROVIDER_ID].duplicated().any():
        raise ValueError("Provider label table must contain exactly one row per Provider.")
    labels = provider_labels.set_index(PROVIDER_ID)[TARGET].astype("string").str.strip().str.lower()
    mapped = labels.map({"no": 0, "yes": 1})
    if mapped.isna().any():
        unexpected = sorted(labels[mapped.isna()].dropna().unique().tolist())
        raise ValueError(f"PotentialFraud must contain only Yes/No labels; found {unexpected}.")
    mapped = mapped.astype("int64")
    mapped.name = TARGET
    return mapped


def _prepare_beneficiaries(beneficiaries, reference_date):
    _require_columns(beneficiaries, ["BeneID", "DOB"], "beneficiary data")
    if beneficiaries["BeneID"].isna().any() or beneficiaries["BeneID"].duplicated().any():
        raise ValueError("Beneficiary table must contain one non-missing row per BeneID.")
    bene = beneficiaries.copy()
    dob = pd.to_datetime(bene["DOB"], errors="coerce")
    bene["Age"] = (reference_date - dob).dt.days / 365.25
    # DOD is intentionally excluded: it may encode post-claim outcomes.
    for col in CHRONIC_COLUMNS:
        if col in bene:
            bene[col] = _numeric(bene[col]).map({1: 1.0, 2: 0.0, 0: 0.0})
    if "RenalDiseaseIndicator" in bene:
        renal = bene["RenalDiseaseIndicator"].astype("string").str.strip().str.upper()
        bene["RenalDiseaseIndicator_numeric"] = renal.map({"Y": 1.0, "N": 0.0, "0": 0.0, "1": 1.0})
    for col in BENEFICIARY_NUMERIC:
        if col in bene and col not in CHRONIC_COLUMNS and col != "Age":
            bene[col] = _numeric(bene[col])
    return bene.set_index("BeneID", drop=False)


def _prepare_claims(frame, table_name, inpatient=False):
    required = ["Provider", "BeneID", "ClaimID", "ClaimStartDt", "ClaimEndDt", "InscClaimAmtReimbursed"]
    if inpatient:
        required += ["AdmissionDt", "DischargeDt"]
    _require_columns(frame, required, table_name)
    claims = frame.copy()
    if claims["Provider"].isna().any() or claims["ClaimID"].isna().any():
        raise ValueError(f"{table_name} contains a missing Provider or ClaimID.")
    if claims["ClaimID"].duplicated().any():
        raise ValueError(f"{table_name} contains duplicate ClaimID values.")
    for col in ("ClaimStartDt", "ClaimEndDt"):
        claims[col] = pd.to_datetime(claims[col], errors="coerce")
    claims["ClaimDurationDays"] = (claims["ClaimEndDt"] - claims["ClaimStartDt"]).dt.days
    claims.loc[claims["ClaimDurationDays"] < 0, "ClaimDurationDays"] = np.nan
    if inpatient:
        for col in ("AdmissionDt", "DischargeDt"):
            claims[col] = pd.to_datetime(claims[col], errors="coerce")
        claims["InpatientStayDays"] = (claims["DischargeDt"] - claims["AdmissionDt"]).dt.days + 1
        claims.loc[claims["InpatientStayDays"] < 0, "InpatientStayDays"] = np.nan
    for col in ("InscClaimAmtReimbursed", "DeductibleAmtPaid"):
        if col in claims:
            claims[col] = _numeric(claims[col])
    return claims


def _aggregate_claims(claims, providers, prefix):
    grouped = claims.groupby("Provider", sort=False, observed=True)
    result = pd.DataFrame(index=pd.Index(providers, name=PROVIDER_ID))
    result[f"{prefix}_claim_count"] = grouped["ClaimID"].nunique().reindex(result.index).fillna(0)
    result[f"{prefix}_unique_beneficiary_count"] = grouped["BeneID"].nunique().reindex(result.index).fillna(0)
    for source, suffix in (("InscClaimAmtReimbursed", "reimbursement"), ("DeductibleAmtPaid", "deductible")):
        if source not in claims:
            continue
        series = grouped[source]
        result[f"{prefix}_{suffix}_total"] = series.sum(min_count=1).reindex(result.index)
        result[f"{prefix}_{suffix}_mean"] = series.mean().reindex(result.index)
        if suffix == "reimbursement":
            result[f"{prefix}_{suffix}_median"] = series.median().reindex(result.index)
    for source, suffix in (("ClaimDurationDays", "claim_duration_days"), ("InpatientStayDays", "inpatient_stay_days")):
        if source == "InpatientStayDays" and prefix != "inpatient":
            continue
        if source in claims:
            series = grouped[source]
            result[f"{prefix}_{suffix}_mean"] = series.mean().reindex(result.index)
            result[f"{prefix}_{suffix}_median"] = series.median().reindex(result.index)
            result[f"{prefix}_{suffix}_max"] = series.max().reindex(result.index)
    for role in ("AttendingPhysician", "OperatingPhysician", "OtherPhysician"):
        if role in claims:
            result[f"{prefix}_{role.lower()}_unique_count"] = grouped[role].nunique().reindex(result.index).fillna(0)

    diagnosis_cols = [c for c in claims if c.startswith("ClmDiagnosisCode_") or c == "ClmAdmitDiagnosisCode"]
    procedure_cols = [c for c in claims if c.startswith("ClmProcedureCode_")]
    for columns, name in ((diagnosis_cols, "diagnosis_code_slot_diversity"), (procedure_cols, "procedure_code_slot_diversity")):
        per_slot = []
        for col in columns:
            per_slot.append(claims.groupby("Provider", sort=False, observed=True)[col].nunique())
        if per_slot:
            result[f"{prefix}_{name}"] = pd.concat(per_slot, axis=1).sum(axis=1).reindex(result.index).fillna(0)
    return result


def _beneficiary_features(claims, beneficiaries, providers):
    pairs = claims[["Provider", "BeneID"]].dropna().drop_duplicates()
    missing_bene = ~pairs["BeneID"].isin(beneficiaries.index)
    if missing_bene.any():
        raise ValueError(f"{int(missing_bene.sum())} provider-beneficiary links have no beneficiary record.")
    pairs = pairs.join(beneficiaries.drop(columns=["BeneID"], errors="ignore"), on="BeneID", rsuffix="_beneficiary")
    result = pd.DataFrame(index=pd.Index(providers, name=PROVIDER_ID))
    group = pairs.groupby("Provider", sort=False, observed=True)
    result["beneficiary_unique_count"] = group["BeneID"].nunique().reindex(result.index).fillna(0)
    numeric_cols = [c for c in BENEFICIARY_NUMERIC if c in pairs]
    if numeric_cols:
        means = group[numeric_cols].mean().reindex(result.index).add_prefix("beneficiary_mean_")
        sums = group[numeric_cols].sum(min_count=1).reindex(result.index).add_prefix("beneficiary_sum_")
        result = result.join(means).join(sums)
    for col in ("Gender", "Race"):
        if col in pairs:
            vals = pairs[col].astype("string").str.strip()
            cats = sorted(vals.dropna().unique().tolist())
            for category in cats:
                indicator = vals.eq(category).fillna(False).astype(float).groupby(pairs["Provider"]).mean()
                result[f"beneficiary_{col.lower()}_{category}_share"] = indicator.reindex(result.index)
    for col in ("State", "County"):
        if col in pairs:
            result[f"beneficiary_{col.lower()}_unique_count"] = group[col].nunique().reindex(result.index).fillna(0)
            mode_share = group[col].agg(lambda values: values.value_counts().iloc[0] / values.notna().sum() if values.notna().any() else np.nan)
            result[f"beneficiary_{col.lower()}_mode_share"] = mode_share.reindex(result.index)
    return result


def build_provider_dataset(provider_labels, beneficiaries, inpatient, outpatient):
    """Return numeric feature rows and binary labels indexed by unique Provider."""
    y = _target_labels(provider_labels)
    providers = y.index
    max_claim_date = max(
        pd.to_datetime(inpatient.get("ClaimEndDt"), errors="coerce").max(),
        pd.to_datetime(outpatient.get("ClaimEndDt"), errors="coerce").max(),
    )
    if pd.isna(max_claim_date):
        raise ValueError("No valid claim end dates are available to derive beneficiary age.")
    bene = _prepare_beneficiaries(beneficiaries, max_claim_date)
    ip = _prepare_claims(inpatient, "inpatient claims", inpatient=True)
    op = _prepare_claims(outpatient, "outpatient claims", inpatient=False)
    overlap = set(ip["ClaimID"]).intersection(op["ClaimID"])
    if overlap:
        raise ValueError(f"Inpatient/outpatient tables share {len(overlap)} ClaimID values.")
    claims = pd.concat([ip, op], ignore_index=True, sort=False)
    unknown_providers = set(claims["Provider"].unique()) - set(providers)
    if unknown_providers:
        raise ValueError(f"Claim tables contain {len(unknown_providers)} providers without PotentialFraud labels.")

    features = pd.DataFrame(index=pd.Index(providers, name=PROVIDER_ID))
    ip_features = _aggregate_claims(ip, providers, "inpatient")
    op_features = _aggregate_claims(op, providers, "outpatient")
    all_features = _aggregate_claims(claims, providers, "total")
    features = features.join(ip_features).join(op_features).join(all_features)
    features = features.join(_beneficiary_features(claims, bene, providers))

    forbidden = CLAIM_DROP_FEATURES.intersection(features.columns)
    if forbidden:
        raise AssertionError(f"Identifier/target leakage in provider features: {sorted(forbidden)}")
    if not features.index.is_unique or not features.index.equals(y.index):
        raise AssertionError("Provider features and labels must align one-to-one by Provider.")
    non_numeric = features.select_dtypes(exclude=[np.number]).columns.tolist()
    if non_numeric:
        raise ValueError(f"Provider feature engineering left non-numeric columns: {non_numeric}")
    return features, y


def load_provider_dataset(data_dir=None):
    """Load the four real Kaggle training files and construct provider-level rows."""
    if data_dir is None:
        data_dir = Path(__file__).resolve().parents[1] / "data" / "raw"
    data_dir = Path(data_dir)
    paths = {name: data_dir / filename for name, filename in DATA_FILES.items()}
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("Required Kaggle CSV file(s) not found: " + ", ".join(missing))
    tables = {
        name: pd.read_csv(path, na_values=["NA"], keep_default_na=True, low_memory=False)
        for name, path in paths.items()
    }
    return build_provider_dataset(
        tables["providers"], tables["beneficiaries"], tables["inpatient"], tables["outpatient"]
    )


def split_provider_data(features, labels, random_state=42):
    """Stratify unique provider IDs into 70/15/15 train, validation, and test splits."""
    if not features.index.is_unique or not labels.index.is_unique:
        raise ValueError("Provider-level split requires unique Provider IDs.")
    if not features.index.equals(labels.index):
        raise ValueError("Feature and target Provider indexes must match in the same order.")
    provider_ids = features.index.to_numpy()
    train_ids, remaining_ids = train_test_split(
        provider_ids, test_size=0.30, random_state=random_state,
        stratify=labels.to_numpy(),
    )
    val_ids, test_ids = train_test_split(
        remaining_ids, test_size=0.50, random_state=random_state,
        stratify=labels.loc[remaining_ids].to_numpy(),
    )
    splits = {"train": train_ids, "validation": val_ids, "test": test_ids}
    sets = {name: set(ids) for name, ids in splits.items()}
    if sets["train"] & sets["validation"] or sets["train"] & sets["test"] or sets["validation"] & sets["test"]:
        raise AssertionError("Provider ID overlap found between data splits.")
    return {
        name: (features.loc[ids], labels.loc[ids])
        for name, ids in splits.items()
    }


def build_preprocessor(feature_columns):
    """Fit this numeric-only pipeline on training rows, then reuse for val/test/inference."""
    if not feature_columns:
        raise ValueError("At least one provider feature is required.")
    numeric_pipeline = Pipeline([
        ("impute", SimpleImputer(strategy="median", add_indicator=True)),
        ("scale", StandardScaler()),
    ])
    return ColumnTransformer(
        [("numeric", numeric_pipeline, list(feature_columns))],
        remainder="drop",
        verbose_feature_names_out=False,
    )


def calculate_class_weights(y_train):
    """Calculate balanced class weights from the actual training-provider labels."""
    classes = np.array(sorted(pd.Series(y_train).unique()))
    if not np.array_equal(classes, np.array([0, 1])):
        raise ValueError("Training labels must contain both binary classes 0 and 1.")
    weights = compute_class_weight(class_weight="balanced", classes=classes, y=np.asarray(y_train))
    return {int(label): float(weight) for label, weight in zip(classes, weights)}
