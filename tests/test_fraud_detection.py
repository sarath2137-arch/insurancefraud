from datetime import date
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).parents[1]/'backend'))
from app.schemas.claim import ClaimCreate
from app.services.fraud_service import predict
def test_high_value_claim_has_elevated_score():
    c=ClaimCreate(claim_id='CLM1',provider_id='PRV1',patient_reference_id='PAT1',hospital='H1',patient_age=40,gender='F',diagnosis='Test',treatment_type='Care',admission_date=date(2026,1,1),discharge_date=date(2026,2,2),claim_amount=200000,previous_claims=5,previous_claim_amount=250000,provider_information='Provider')
    assert predict(c)[1] > 65
