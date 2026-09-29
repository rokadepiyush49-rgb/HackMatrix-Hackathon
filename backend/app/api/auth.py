"""Sign-in, token refresh, and the current user's profile."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core import audit
from app.core.db import get_db
from app.core.limiter import limiter
from app.core.security import CurrentUser, decode, issue_tokens, verify_password
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
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Username or password is incorrect")
    audit.append(db, user.id, "auth.login")
    db.commit()
    return issue_tokens(user)


@router.post("/refresh", response_model=TokenOut)
def refresh(body: RefreshIn, db: Annotated[Session, Depends(get_db)]) -> dict:
    payload = decode(body.refresh_token, "refresh")
    user = db.get(AppUser, payload["sub"])
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown user")
    return issue_tokens(user)


@router.get("/me", response_model=MeOut)
def me(p: CurrentUser) -> dict:
    return {"id": p.id, "display_name": p.display_name, "role": p.role, "title": p.title,
            "capabilities": sorted(p.capabilities)}


@router.get("/demo-users", response_model=list[DemoUserOut])
def demo_users(db: Annotated[Session, Depends(get_db)]) -> list[AppUser]:
    """Seeded personas for the sign-in screen (local demo data only)."""
    return db.query(AppUser).order_by(AppUser.id).all()
