from __future__ import annotations

import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional

from fastapi import Request
from sqlalchemy import select

from app.auth import decode_token
from app.db import SessionLocal
from app.errors import ApiError
from app.models import User


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    role: str


_current_principal: ContextVar[Optional[Principal]] = ContextVar("current_principal", default=None)
_latest_principal: Optional[Principal] = None

def current_principal() -> Principal:
    principal = _current_principal.get() or _latest_principal
    if principal is None:
        raise ApiError(401, "TOKEN_INVALID", "Authorization bearer token is required")
    return principal


def get_token_bearerAuth(
    request: Request,
):
    global _latest_principal
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ApiError(401, "TOKEN_INVALID", "Authorization bearer token is required")

    payload = decode_token(token, "access")
    user_id = uuid.UUID(payload["sub"])
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.id == user_id))
        if user is None:
            raise ApiError(401, "TOKEN_INVALID", "Token user does not exist")
        principal = Principal(user_id=user.id, role=user.role)

    _current_principal.set(principal)
    _latest_principal = principal
    request.state.user_id = str(principal.user_id)
    request.state.role = principal.role

    from generated_server.models.extra_models import TokenModel

    return TokenModel(sub=str(principal.user_id))
