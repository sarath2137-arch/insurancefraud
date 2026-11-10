from fastapi import APIRouter,Depends,HTTPException,Query
from sqlalchemy.orm import Session
from ..utils.database import get_db
from ..utils.security import current_user
from ..models.claim import Claim,FraudPrediction
from ..schemas.claim import ClaimCreate
from ..services.fraud_service import predict_details
router=APIRouter(prefix='/api/fraud',tags=['fraud'])
@router.post('/predict')
def prediction(body:ClaimCreate,model:str|None=Query(default=None,pattern='^(heuristic|baseline|dnn)$'),_=Depends(current_user)):
 try: result=predict_details(body,model)
 except RuntimeError as exc: raise HTTPException(503,str(exc))
 except ValueError as exc: raise HTTPException(422,str(exc))
 return {**result,'probability':result['fraud_probability'],'notice':'Decision-support only; investigate before making a fraud determination.'}
@router.get('/{claim_id}')
def result(claim_id:str,db:Session=Depends(get_db),_=Depends(current_user)):
 c=db.query(Claim).filter_by(claim_id=claim_id).first();p=c and db.query(FraudPrediction).filter_by(claim_id=c.id).first()
 if not p: raise HTTPException(404,'Prediction not found')
 dnn=None if p.dnn_probability is None else {'probability':p.dnn_probability,'risk_score':p.dnn_risk_score,'prediction':p.dnn_prediction,'threshold':p.dnn_threshold}
 heuristic={'probability':p.probability,'risk_score':p.risk_score,'prediction':p.prediction,'factors':p.factors}
 return {'claim_id':claim_id,'provider_id':c.provider_id,'claim_heuristic':heuristic,'provider_dnn':dnn,'probability':p.probability,'risk_score':p.risk_score,'prediction':p.prediction,'factors':p.factors}
