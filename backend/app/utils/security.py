import os
from datetime import datetime, timedelta, timezone
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from .database import get_db

pwd_context = CryptContext(schemes=['bcrypt'], deprecated='auto')
oauth2_scheme = OAuth2PasswordBearer(tokenUrl='/api/auth/login')


def get_jwt_secret():
    """Return a configured signing secret; never fall back to a built-in value."""
    secret = os.getenv('JWT_SECRET', '')
    if len(secret.encode('utf-8')) < 32:
        raise RuntimeError('JWT_SECRET must be configured with at least 32 bytes of random secret material.')
    return secret


def hash_password(value): return pwd_context.hash(value)
def verify_password(value, hashed): return pwd_context.verify(value, hashed)
def create_token(user_id):
    return jwt.encode({'sub': str(user_id), 'exp': datetime.now(timezone.utc)+timedelta(minutes=int(os.getenv('JWT_EXPIRE_MINUTES','480')))}, get_jwt_secret(), algorithm='HS256')
def current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    from ..models.user import User
    secret = get_jwt_secret()
    try: user_id = jwt.decode(token, secret, algorithms=['HS256'])['sub']
    except Exception: raise HTTPException(status_code=401, detail='Invalid or expired token')
    user = db.get(User, int(user_id))
    if not user or not user.is_active: raise HTTPException(status_code=401, detail='User unavailable')
    return user
def require_roles(*roles):
    def guard(user=Depends(current_user)):
        if user.role not in roles: raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Insufficient permissions')
        return user
    return guard
