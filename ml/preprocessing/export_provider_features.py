"""Export the existing provider-level inference features without target labels."""

from pathlib import Path
import sys

ML_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ML_ROOT))
from preprocessing.preprocess import load_provider_dataset


PROJECT_ROOT = ML_ROOT.parent
RAW_DATA = PROJECT_ROOT / "ml" / "data" / "raw"
OUTPUT = PROJECT_ROOT / "ml" / "data" / "provider_features.csv"


def export_provider_features(raw_data=RAW_DATA, output=OUTPUT):
    features, _ = load_provider_dataset(raw_data)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    features.to_csv(output, index_label="Provider", float_format="%.17g")
    return features


if __name__ == "__main__":
    table = export_provider_features()
    print(f"Exported {len(table)} provider rows and {len(table.columns)} features to {OUTPUT}.")
