from datetime import datetime, timedelta
from typing import Optional
import jwt
from jwt import InvalidTokenError as JWTError
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User
from app.config import settings
from uuid import UUID
from app.services.session_security import session_token, require_cookie_csrf

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)

def hash_password(password: str) -> str:
    return pwd_ctx.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    if len(plain.encode("utf-8")) > 72:
        return False
    try:
        return pwd_ctx.verify(plain, hashed)
    except (ValueError, TypeError):
        return False


def decode_subject(token: str) -> str:
    payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM],
                         options={"require": ["exp", "sub"]})
    try:
        return str(UUID(payload["sub"]))
    except (ValueError, TypeError, AttributeError):
        raise JWTError("Invalid subject") from None

def create_token(user_id: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": user_id, "exp": expire},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )

def get_current_user(
    request: Request,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    token = session_token(request)
    if token is None and creds:
        token = creds.credentials
    if token is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    require_cookie_csrf(request)
    try:
        user_id = decode_subject(token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")
    return user

def get_optional_user(
    request: Request,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Optional[User]:
    token = session_token(request)
    if token is None and creds:
        token = creds.credentials
    if token is None:
        return None
    require_cookie_csrf(request)
    try:
        user_id = decode_subject(token)
        return db.query(User).filter(User.id == user_id).first()
    except JWTError:
        return None
