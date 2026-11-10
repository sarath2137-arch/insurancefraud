from sqlalchemy import func
from fastapi import APIRouter,Depends
from sqlalchemy.orm import Session
from ..utils.database import get_db
from ..utils.security import require_roles
from ..models.claim import Claim,FraudPrediction
router=APIRouter(prefix='/api/reports',tags=['reports'])
@router.get('/summary')
def summary(db:Session=Depends(get_db),_=Depends(require_roles('insurance_admin','system_admin'))):
 claims=db.query(Claim).all(); pred={p.claim_id:p for p in db.query(FraudPrediction).all()}
 return {'total_claims':len(claims),'suspicious_claims':sum(1 for c in claims if pred.get(c.id) and pred[c.id].prediction=='suspicious'),'pending_claims':sum(c.status=='pending' for c in claims),'approved_claims':sum(c.status=='approved' for c in claims),'rejected_claims':sum(c.status=='rejected' for c in claims),'total_claim_amount':sum(c.claim_amount for c in claims),'average_risk':round(sum(pred[c.id].risk_score for c in claims if c.id in pred)/len(pred),1) if pred else 0}
@router.get('/fraud-statistics')
def stats(db:Session=Depends(get_db),_=Depends(require_roles('insurance_admin','system_admin'))):
 return {'by_hospital':[{'hospital':h,'count':n} for h,n in db.query(Claim.hospital,func.count(Claim.id)).group_by(Claim.hospital).all()]}
