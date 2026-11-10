import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..utils.database import get_db
from ..utils.security import require_roles, current_user
from ..models.claim import Claim, FraudPrediction, BlockchainTransaction
from ..services.blockchain_service import decision_hash, decision_payload, verify_decision, write_decision

router = APIRouter(prefix="/api/blockchain", tags=["blockchain"])


def _get_claim_rows(claim_id, db):
    claim = db.query(Claim).filter_by(claim_id=claim_id).first()
    if not claim:
        raise HTTPException(404, "Claim not found")
    prediction = db.query(FraudPrediction).filter_by(claim_id=claim.id).first()
    record = db.query(BlockchainTransaction).filter_by(claim_id=claim.id).first()
    if not record:
        raise HTTPException(404, "Blockchain decision record not found")
    if not prediction or prediction.dnn_probability is None or not claim.provider_id:
        raise HTTPException(409, "This claim has no provider-level DNN decision to register or verify")
    payload = decision_payload(claim.claim_id, claim.provider_id, {
        "fraud_probability": prediction.dnn_probability,
        "risk_score": prediction.dnn_risk_score,
        "prediction": prediction.dnn_prediction,
        "threshold": prediction.dnn_threshold,
    }, claim.created_at)
    return claim, prediction, record, payload


def _response(claim, record, result):
    return {
        "claim_id": claim.claim_id,
        "decision_hash": record.claim_hash,
        "blockchain_status": result["verification_status"],
        "verification_status": result["verification_status"],
        "record_matches": result["record_matches"],
        "contract_verified": result["contract_verified"],
        "transaction_hash": result["transaction_hash"] or record.transaction_hash,
        "block_number": result["block_number"] if result["block_number"] is not None else record.block_number,
        "receipt_status": result["receipt_status"] if result["receipt_status"] is not None else record.receipt_status,
        "configuration_missing": result["configuration_missing"],
        "verification_detail": result["verification_detail"],
        "timestamp": record.created_at,
    }


@router.post("/register")
def register(claim_id: str, db: Session = Depends(get_db), _=Depends(require_roles("insurance_admin", "system_admin"))):
    claim, _, record, payload = _get_claim_rows(claim_id, db)
    expected_hash = decision_hash(payload)
    if expected_hash != record.claim_hash:
        raise HTTPException(409, "Stored decision hash does not match the canonical decision payload")
    result = write_decision(payload, expected_hash)
    record.transaction_hash = result["transaction_hash"] or record.transaction_hash
    record.block_number = result["block_number"] if result["block_number"] is not None else record.block_number
    record.verification_status = result["verification_status"]
    record.configuration_missing = json.dumps(result["configuration_missing"])
    record.verification_detail = result["verification_detail"]
    record.record_matches = result["record_matches"]
    record.contract_verified = result["contract_verified"]
    record.receipt_status = result["receipt_status"] if result["receipt_status"] is not None else record.receipt_status
    db.commit()
    return _response(claim, record, result)


def _verify_claim(claim_id, db):
    claim, _, record, payload = _get_claim_rows(claim_id, db)
    expected_hash = decision_hash(payload)
    if expected_hash != record.claim_hash:
        raise HTTPException(409, "Stored decision hash does not match the canonical decision payload")
    result = verify_decision(claim.claim_id, expected_hash, payload)
    record.transaction_hash = result["transaction_hash"] or record.transaction_hash
    record.block_number = result["block_number"] if result["block_number"] is not None else record.block_number
    record.verification_status = result["verification_status"]
    record.configuration_missing = json.dumps(result["configuration_missing"])
    record.verification_detail = result["verification_detail"]
    record.record_matches = result["record_matches"]
    record.contract_verified = result["contract_verified"]
    record.receipt_status = result["receipt_status"] if result["receipt_status"] is not None else record.receipt_status
    db.commit()
    return _response(claim, record, result)


@router.get("/verify/{claim_id}")
def verify(claim_id: str, db: Session = Depends(get_db), _=Depends(current_user)):
    return _verify_claim(claim_id, db)


@router.get("/hash/{decision_hash}")
def verify_hash(decision_hash: str, db: Session = Depends(get_db), _=Depends(current_user)):
    lookup_hash = decision_hash.strip().removeprefix("0x").lower()
    stored = db.query(BlockchainTransaction).filter_by(claim_hash=lookup_hash).first()
    if not stored:
        raise HTTPException(404, "Decision hash not found")
    claim = db.query(Claim).filter_by(id=stored.claim_id).first()
    if not claim:
        raise HTTPException(404, "Claim not found")
    return _verify_claim(claim.claim_id, db)


@router.get("/{claim_id}")
def record(claim_id: str, db: Session = Depends(get_db), _=Depends(current_user)):
    return _verify_claim(claim_id, db)
