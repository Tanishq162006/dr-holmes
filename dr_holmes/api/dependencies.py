"""FastAPI dependencies — auth scaffold, session injection."""
from __future__ import annotations
import os
import hashlib
from typing import Optional
from fastapi import Header, HTTPException, status, Query

from dr_holmes.api.persistence import get_sessionmaker

_AUTH_MODE = os.getenv("DR_HOLMES_AUTH_MODE", "dev").lower()


class User:
    def __init__(self, owner_id: str):
        self.owner_id = owner_id


async def get_current_user(authorization: Optional[str] = Header(default=None)) -> User:
    """Auth scaffold. dev mode: any non-empty token (or none) → owner_id='dev'.
    jwt mode (Phase 5+): real validation."""
    if _AUTH_MODE == "dev":
        if authorization and authorization.startswith("Bearer "):
            token = authorization.split(" ", 1)[1].strip()
            owner_id = hashlib.sha256(token.encode()).hexdigest()[:16] if token else "dev"
        else:
            owner_id = "dev"
        return User(owner_id=owner_id)

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    # jwt validation TBD
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "JWT auth not yet implemented")


async def get_ws_user(token: Optional[str] = Query(default=None)) -> User:
    """WS auth via query param (browsers can't set headers on WS)."""
    if _AUTH_MODE == "dev":
        owner_id = "dev"
        if token:
            owner_id = hashlib.sha256(token.encode()).hexdigest()[:16]
        return User(owner_id=owner_id)
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "JWT auth not yet implemented")
