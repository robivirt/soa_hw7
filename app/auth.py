from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ApiError
from app.models import User
from app.settings import settings


pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_token(user: User, token_type: str) -> str:
    now = datetime.now(timezone.utc)
    if token_type == "access":
        expires_at = now + timedelta(minutes=settings.access_token_minutes)
    else:
        expires_at = now + timedelta(days=settings.refresh_token_days)
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str, expected_type: str) -> dict:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError as exc:
        code = "TOKEN_EXPIRED" if expected_type == "access" else "REFRESH_TOKEN_INVALID"
        raise ApiError(401, code, "Token expired") from exc
    except jwt.InvalidTokenError as exc:
        code = "TOKEN_INVALID" if expected_type == "access" else "REFRESH_TOKEN_INVALID"
        raise ApiError(401, code, "Token invalid") from exc
    if payload.get("type") != expected_type:
        code = "TOKEN_INVALID" if expected_type == "access" else "REFRESH_TOKEN_INVALID"
        raise ApiError(401, code, "Token type is invalid")
    return payload


def get_current_user(
    request: Request,
    credentials: Annotated[Optional[HTTPAuthorizationCredentials], Depends(bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    if credentials is None:
        raise ApiError(401, "TOKEN_INVALID", "Authorization bearer token is required")
    payload = decode_token(credentials.credentials, "access")
    user_id = uuid.UUID(payload["sub"])
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise ApiError(401, "TOKEN_INVALID", "Token user does not exist")
    request.state.user_id = str(user.id)
    request.state.role = user.role
    return user


def require_roles(*roles: str):
    def dependency(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in roles:
            raise ApiError(403, "ACCESS_DENIED", "Access denied")
        return user

    return dependency
