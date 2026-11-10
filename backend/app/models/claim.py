from datetime import datetime, date
from sqlalchemy import String, Float, Integer, DateTime, Date, ForeignKey, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from ..utils.database import Base
class Claim(Base):
    __tablename__='claims'
    id: Mapped[int]=mapped_column(primary_key=True)
    claim_id: Mapped[str]=mapped_column(String(64), unique=True, index=True)
    # Nullable for rows created before the provider-level workflow was introduced.
    provider_id: Mapped[str|None]=mapped_column(String(64), nullable=True, index=True)
    patient_reference_id: Mapped[str]=mapped_column(String(64), index=True)
    hospital: Mapped[str]=mapped_column(String(150), index=True)
    patient_age: Mapped[int]=mapped_column(Integer)
    gender: Mapped[str]=mapped_column(String(20))
    diagnosis: Mapped[str]=mapped_column(String(200))
    treatment_type: Mapped[str]=mapped_column(String(150))
    admission_date: Mapped[date]=mapped_column(Date)
    discharge_date: Mapped[date]=mapped_column(Date)
    claim_amount: Mapped[float]=mapped_column(Float)
    previous_claims: Mapped[int]=mapped_column(Integer, default=0)
    previous_claim_amount: Mapped[float]=mapped_column(Float, default=0)
    provider_information: Mapped[str]=mapped_column(String(300))
    status: Mapped[str]=mapped_column(String(40), default='pending', index=True)
    submitted_by: Mapped[int]=mapped_column(ForeignKey('users.id'))
    created_at: Mapped[datetime]=mapped_column(DateTime, default=datetime.utcnow)
class FraudPrediction(Base):
    __tablename__='fraud_predictions'
    id: Mapped[int]=mapped_column(primary_key=True); claim_id: Mapped[int]=mapped_column(ForeignKey('claims.id'), unique=True)
    probability: Mapped[float]=mapped_column(Float); risk_score: Mapped[float]=mapped_column(Float); prediction: Mapped[str]=mapped_column(String(30)); factors: Mapped[str]=mapped_column(Text, default='[]')
    dnn_probability: Mapped[float|None]=mapped_column(Float, nullable=True)
    dnn_risk_score: Mapped[float|None]=mapped_column(Float, nullable=True)
    dnn_prediction: Mapped[str|None]=mapped_column(String(30), nullable=True)
    dnn_threshold: Mapped[float|None]=mapped_column(Float, nullable=True)
class BlockchainTransaction(Base):
    __tablename__='blockchain_transactions'
    id: Mapped[int]=mapped_column(primary_key=True); claim_id: Mapped[int]=mapped_column(ForeignKey('claims.id'), unique=True)
    claim_hash: Mapped[str]=mapped_column(String(64), index=True); transaction_hash: Mapped[str|None]=mapped_column(String(100), nullable=True); block_number: Mapped[int|None]=mapped_column(Integer, nullable=True)
    verification_status: Mapped[str]=mapped_column(String(64), default='pending'); created_at: Mapped[datetime]=mapped_column(DateTime, default=datetime.utcnow)
    configuration_missing: Mapped[str|None]=mapped_column(Text, nullable=True)
    verification_detail: Mapped[str|None]=mapped_column(Text, nullable=True)
    record_matches: Mapped[bool|None]=mapped_column(Boolean, nullable=True)
    contract_verified: Mapped[bool|None]=mapped_column(Boolean, nullable=True)
    receipt_status: Mapped[int|None]=mapped_column(Integer, nullable=True)
class ClaimAuditLog(Base):
    __tablename__='claim_audit_logs'
    id: Mapped[int]=mapped_column(primary_key=True); claim_id: Mapped[int]=mapped_column(ForeignKey('claims.id'), index=True); actor_id: Mapped[int]=mapped_column(ForeignKey('users.id')); action: Mapped[str]=mapped_column(String(150)); created_at: Mapped[datetime]=mapped_column(DateTime, default=datetime.utcnow)
