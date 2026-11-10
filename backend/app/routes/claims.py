import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..utils.database import get_db
from ..utils.security import current_user, require_roles
from ..models.claim import Claim, FraudPrediction, BlockchainTransaction, ClaimAuditLog
from ..schemas.claim import ClaimCreate, StatusUpdate
from ..services.fraud_service import predict, predict_provider_level
from ..services.blockchain_service import decision_hash, decision_payload, write_decision

router = APIRouter(prefix="/api/claims", tags=["claims"])


def serialize(c, db):
    p = db.query(FraudPrediction).filter_by(claim_id=c.id).first()
    b = db.query(BlockchainTransaction).filter_by(claim_id=c.id).first()
    heuristic = None if not p else {
        "probability": p.probability,
        "risk_score": p.risk_score,
        "prediction": p.prediction,
        "factors": json.loads(p.factors),
    }
    dnn = None if not p or p.dnn_probability is None else {
        "probability": p.dnn_probability,
        "risk_score": p.dnn_risk_score,
        "prediction": p.dnn_prediction,
        "threshold": p.dnn_threshold,
        "notice": "Provider-level risk signal for human review; not a fraud determination.",
    }
    return {
        "id": c.id, "claim_id": c.claim_id, "provider_id": c.provider_id,
        "patient_reference_id": c.patient_reference_id, "hospital": c.hospital,
        "patient_age": c.patient_age, "gender": c.gender, "diagnosis": c.diagnosis,
        "treatment_type": c.treatment_type, "admission_date": c.admission_date,
        "discharge_date": c.discharge_date, "claim_amount": c.claim_amount,
        "previous_claims": c.previous_claims, "previous_claim_amount": c.previous_claim_amount,
        "provider_information": c.provider_information, "status": c.status, "created_at": c.created_at,
        # Legacy aliases retain the previous heuristic response contract.
        "fraud": None if heuristic is None else {**heuristic, "heuristic": heuristic, "provider_dnn": dnn},
        "fraud_scores": {"claim_heuristic": heuristic, "provider_dnn": dnn},
        "blockchain": None if not b else {
            "decision_hash": b.claim_hash, "claim_hash": b.claim_hash,
            "transaction_hash": b.transaction_hash, "block_number": b.block_number,
            "verification_status": b.verification_status,
            "configuration_missing": json.loads(b.configuration_missing or "[]"),
            "verification_detail": b.verification_detail,
            "record_matches": b.record_matches,
            "contract_verified": b.contract_verified,
            "receipt_status": b.receipt_status,
            "created_at": b.created_at,
        },
    }


@router.post("", status_code=201)
def create(body: ClaimCreate, db: Session = Depends(get_db), user=Depends(current_user)):
    if db.query(Claim).filter_by(claim_id=body.claim_id).first():
        raise HTTPException(409, "Claim ID already exists")
    # Validate the canonical provider against all source tables and run the saved
    # feature engineering/preprocessor/model before persisting the claim.
    try:
        dnn = predict_provider_level(provider_id=body.provider_id)
    except FileNotFoundError as exc:
        raise HTTPException(503, f"Provider source data unavailable: {exc}")
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    except ValueError as exc:
        raise HTTPException(422, str(exc))

    heuristic_probability, heuristic_score, heuristic_prediction, factors = predict(body)
    dnn_prediction = "Potential Fraud" if dnn["prediction"] == 1 else "Low Risk"
    c = Claim(**body.model_dump(), submitted_by=user.id)
    db.add(c)
    db.flush()
    db.add(FraudPrediction(
        claim_id=c.id, probability=heuristic_probability, risk_score=heuristic_score,
        prediction=heuristic_prediction, factors=json.dumps(factors),
        dnn_probability=dnn["fraud_probability"], dnn_risk_score=dnn["risk_score"],
        dnn_prediction=dnn_prediction, dnn_threshold=dnn["threshold"],
    ))

    payload = decision_payload(c.claim_id, c.provider_id, {
        **dnn, "prediction": dnn_prediction,
    }, c.created_at)
    hashed = decision_hash(payload)
    chain = write_decision(payload, hashed)
    db.add(BlockchainTransaction(
        claim_id=c.id, claim_hash=hashed, transaction_hash=chain["transaction_hash"],
        block_number=chain["block_number"], verification_status=chain["verification_status"],
        configuration_missing=json.dumps(chain["configuration_missing"]),
        verification_detail=chain["verification_detail"],
        record_matches=chain["record_matches"], contract_verified=chain["contract_verified"],
        receipt_status=chain["receipt_status"],
    ))
    db.add(ClaimAuditLog(claim_id=c.id, actor_id=user.id, action="Claim submitted and analyzed"))
    db.commit()
    db.refresh(c)
    return serialize(c, db)


@router.get("")
def list_claims(db: Session = Depends(get_db), user=Depends(current_user)):
    q = db.query(Claim)
    if user.role == "claim_officer":
        q = q.filter_by(submitted_by=user.id)
    return [serialize(c, db) for c in q.order_by(Claim.created_at.desc()).all()]


@router.get("/{claim_id}")
def detail(claim_id: str, db: Session = Depends(get_db), user=Depends(current_user)):
    c = db.query(Claim).filter_by(claim_id=claim_id).first()
    if not c:
        raise HTTPException(404, "Claim not found")
    if user.role == "claim_officer" and c.submitted_by != user.id:
        raise HTTPException(403, "Not your claim")
    return serialize(c, db)


@router.put("/{claim_id}/status")
def status(claim_id: str, body: StatusUpdate, db: Session = Depends(get_db), user=Depends(require_roles("insurance_admin", "system_admin"))):
    valid = {"pending", "under_investigation", "approved", "rejected"}
    if body.status not in valid:
        raise HTTPException(422, "Invalid status")
    c = db.query(Claim).filter_by(claim_id=claim_id).first()
    if not c:
        raise HTTPException(404, "Claim not found")
    c.status = body.status
    db.add(ClaimAuditLog(claim_id=c.id, actor_id=user.id, action=f"Status changed to {body.status}"))
    db.commit()
    return serialize(c, db)
