from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..utils.database import get_db
from ..utils.security import hash_password, verify_password, create_token, current_user, require_roles
from ..models.user import User
from ..schemas.user import Register, Login, UserProvision
router=APIRouter(prefix='/api/auth',tags=['auth'])
@router.post('/register')
def register(body:Register, db:Session=Depends(get_db)):
    if db.query(User).filter_by(email=body.email).first(): raise HTTPException(409,'Email already registered')
    u=User(email=body.email,full_name=body.full_name,password_hash=hash_password(body.password),role='claim_officer'); db.add(u);db.commit();db.refresh(u); return {'id':u.id,'email':u.email,'role':u.role}


@router.post('/provision', status_code=201)
def provision(body:UserProvision, db:Session=Depends(get_db), _=Depends(require_roles('system_admin'))):
    """Create an account with an assigned role; only a system administrator may do so."""
    if db.query(User).filter_by(email=body.email).first(): raise HTTPException(409,'Email already registered')
    u=User(email=body.email,full_name=body.full_name,password_hash=hash_password(body.password),role=body.role)
    db.add(u);db.commit();db.refresh(u)
    return {'id':u.id,'email':u.email,'role':u.role}


@router.post('/login')
def login(body:Login, db:Session=Depends(get_db)):
    u=db.query(User).filter_by(email=body.email).first()
    if not u or not u.is_active or not verify_password(body.password,u.password_hash): raise HTTPException(401,'Invalid email or password')
    return {'access_token':create_token(u.id),'token_type':'bearer','user':{'id':u.id,'email':u.email,'full_name':u.full_name,'role':u.role}}
@router.get('/me')
def me(u=Depends(current_user)): return {'id':u.id,'email':u.email,'full_name':u.full_name,'role':u.role}
