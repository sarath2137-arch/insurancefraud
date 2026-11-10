from datetime import date
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).parents[1]/'backend'))
from app.schemas.claim import ClaimCreate
from types import SimpleNamespace
from app.models.claim import FraudPrediction, BlockchainTransaction
from app.routes.claims import serialize


def test_claim_response_keeps_heuristic_and_provider_dnn_separate():
    prediction = SimpleNamespace(
        probability=0.2, risk_score=20.0, prediction='legitimate', factors='[]',
        dnn_probability=0.8, dnn_risk_score=80.0, dnn_prediction='Potential Fraud', dnn_threshold=0.5,
    )
    class Query:
        def __init__(self, value): self.value=value
        def filter_by(self, **_): return self
        def first(self): return self.value
    class DB:
        def query(self, model): return Query(prediction if model is FraudPrediction else None)
    claim=SimpleNamespace(id=1,claim_id='C1',provider_id='PRV1',patient_reference_id='P1',hospital='H1',patient_age=30,gender='X',diagnosis='Test',treatment_type='Care',admission_date=date(2026,1,1),discharge_date=date(2026,1,2),claim_amount=1,previous_claims=0,previous_claim_amount=0,provider_information='Provider',status='pending',created_at=None)
    response=serialize(claim,DB())
    assert response['fraud_scores']['claim_heuristic']['risk_score'] == 20.0
    assert response['fraud_scores']['provider_dnn']['risk_score'] == 80.0
    assert response['fraud']['risk_score'] == 20.0
def test_rejects_reversed_dates():
    try: ClaimCreate(claim_id='C1',provider_id='PRV1',patient_reference_id='P1',hospital='H1',patient_age=30,gender='X',diagnosis='Test',treatment_type='Care',admission_date=date(2026,2,2),discharge_date=date(2026,2,1),claim_amount=1,previous_claims=0,previous_claim_amount=0,provider_information='Provider')
    except ValueError: return
    assert False
