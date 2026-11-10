"""Create missing application tables and safely add known schema columns.

This baseline is additive: it creates absent tables and adds missing nullable
columns to older installations. It never drops tables, columns, or records.
"""

from alembic import op
from sqlalchemy import Boolean, Column, Float, Integer, String, Text, inspect

from app.models import claim as claim_models  # noqa: F401
from app.models import user as user_model  # noqa: F401
from app.utils.database import Base


revision = "0001_safe_schema_baseline"
down_revision = None
branch_labels = None
depends_on = None


ADDITIVE_COLUMNS = {
    "claims": {"provider_id": String(64)},
    "fraud_predictions": {
        "dnn_probability": Float(),
        "dnn_risk_score": Float(),
        "dnn_prediction": String(30),
        "dnn_threshold": Float(),
    },
    "blockchain_transactions": {
        "configuration_missing": Text(),
        "verification_detail": Text(),
        "record_matches": Boolean(),
        "contract_verified": Boolean(),
        "receipt_status": Integer(),
    },
}


def upgrade():
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=True)
    inspector = inspect(bind)
    for table_name, columns in ADDITIVE_COLUMNS.items():
        if not inspector.has_table(table_name):
            continue
        existing = {column["name"] for column in inspector.get_columns(table_name)}
        for column_name, column_type in columns.items():
            if column_name not in existing:
                op.add_column(table_name, Column(column_name, column_type, nullable=True))
                existing.add(column_name)

    if inspector.has_table("claims"):
        indexes = {index["name"] for index in inspector.get_indexes("claims")}
        if "ix_claims_provider_id" not in indexes:
            op.create_index("ix_claims_provider_id", "claims", ["provider_id"], unique=False)

    if bind.dialect.name == "postgresql" and inspector.has_table("blockchain_transactions"):
        bind.exec_driver_sql(
            "ALTER TABLE blockchain_transactions "
            "ALTER COLUMN verification_status TYPE VARCHAR(64)"
        )


def downgrade():
    raise RuntimeError(
        "This data-preserving baseline has no automatic downgrade. "
        "Create a reviewed backup and a specific forward migration instead."
    )
