"""Sign-in, token refresh, and the current user's profile."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core import audit
from app.core.config import get_settings
from app.core.db import get_db
from app.core.limiter import limiter
from app.core.security import (
    UNKNOWN_USER_HASH,
    CurrentUser,
    bearer,
    decode,
    issue_tokens,
    revoke_session,
    session_active,
    verify_password,
)
from app.loom.models import AppUser

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int


class RefreshIn(BaseModel):
    refresh_token: str


class LogoutIn(BaseModel):
    refresh_token: str | None = None


class MeOut(BaseModel):
    id: str
    display_name: str
    role: str
    title: str
    capabilities: list[str]


class DemoUserOut(BaseModel):
    id: str
    display_name: str
    title: str
    role: str


@router.post("/login", response_model=TokenOut)
@limiter.limit("10/minute")
def login(request: Request, body: LoginIn, db: Annotated[Session, Depends(get_db)]) -> dict:
    user = db.get(AppUser, body.username.strip().lower())
    if user is None:
        verify_password(body.password, UNKNOWN_USER_HASH)  # same cost as a real check: no username probing
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Username or password is incorrect")
    audit.append(db, user.id, "auth.login")
    db.commit()
    return issue_tokens(user)


@router.post("/refresh", response_model=TokenOut)
@limiter.limit("30/minute")
def refresh(request: Request, body: RefreshIn, db: Annotated[Session, Depends(get_db)]) -> dict:
    payload = decode(body.refresh_token, "refresh")
    if not session_active(db, payload):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "This session has ended. Sign in again.")
    user = db.get(AppUser, payload["sub"])
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown user")
    return issue_tokens(user, payload["sid"])


@router.post("/logout")
def logout(db: Annotated[Session, Depends(get_db)],
           creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
           body: LogoutIn | None = None) -> dict:
    """End this sign-in session: its access and refresh tokens (every refreshed copy too) are refused from now
    on, and the sign-out is recorded in the audit chain. The refresh token is accepted as well as the access
    token, so a sign-out still works after the access token has lapsed."""
    if body is not None and body.refresh_token:
        payload = decode(body.refresh_token, "refresh")
    elif creds is not None:
        payload = decode(creds.credentials, "access")
    else:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to continue")
    if not payload.get("sid"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "This session has ended. Sign in again.")
    if revoke_session(db, payload["sid"], payload["sub"]):
        audit.append(db, payload["sub"], "auth.logout")
    db.commit()
    return {"ok": True}


@router.get("/me", response_model=MeOut)
def me(p: CurrentUser) -> dict:
    return {"id": p.id, "display_name": p.display_name, "role": p.role, "title": p.title,
            "capabilities": sorted(p.capabilities)}


@router.get("/demo-users", response_model=list[DemoUserOut])
def demo_users(db: Annotated[Session, Depends(get_db)]) -> list[AppUser]:
    """Seeded personas for the sign-in screen (local demo data only)."""
    if not get_settings().demo_mode:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return db.query(AppUser).order_by(AppUser.id).all()
