"""Authentication (JWT) and authorisation (role → capability) for the API."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.loom.models import AppUser

ALGO = "HS256"

# Capabilities are what the code checks; roles are bundles of capabilities.
ROLE_CAPABILITIES: dict[str, set[str]] = {
    "L1_ANALYST": {"alerts:read", "cases:read", "cases:triage"},
    "L2_INVESTIGATOR": {
        "alerts:read", "cases:read", "cases:triage", "cases:investigate",
        "cases:propose", "packs:create", "copilot:use", "mend:use", "unmask:request",
    },
    "VIGILANCE": {
        "alerts:read", "cases:read", "cases:investigate", "cases:review", "cases:decide",
        "packs:create", "packs:lock", "copilot:use", "mend:use", "unmask:request", "unmask:approve",
    },
    "PRINCIPAL_OFFICER": {
        "alerts:read", "cases:read", "cases:review", "cases:decide", "packs:create",
        "packs:lock", "copilot:use", "str:draft", "unmask:approve",
    },
    "INSIDER_RISK": {"alerts:read", "cases:read", "alibi:review", "unmask:request", "mend:use"},
    "TEAM_LEAD": {"alerts:read", "cases:read", "cases:assign", "cases:review", "cases:decide"},
    "AUDITOR": {"alerts:read", "cases:read", "audit:read", "governance:read"},
    "ADMIN": {"alerts:read", "cases:read", "audit:read", "governance:read", "governance:write",
              "unmask:approve", "pipeline:run"},
}


@dataclass(frozen=True)
class Principal:
    id: str
    display_name: str
    role: str
    title: str

    @property
    def capabilities(self) -> set[str]:
        return ROLE_CAPABILITIES.get(self.role, set())


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=10)).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def _encode(sub: str, kind: str, minutes: int, extra: dict | None = None) -> str:
    now = datetime.now(UTC)
    payload = {"sub": sub, "typ": kind, "iat": now, "exp": now + timedelta(minutes=minutes)}
    payload.update(extra or {})
    return jwt.encode(payload, get_settings().jwt_secret, algorithm=ALGO)


def issue_tokens(user: AppUser) -> dict[str, str | int]:
    s = get_settings()
    return {
        "access_token": _encode(user.id, "access", s.jwt_access_minutes, {"role": user.role}),
        "refresh_token": _encode(user.id, "refresh", s.jwt_refresh_minutes),
        "expires_in": s.jwt_access_minutes * 60,
    }


def decode(token: str, kind: str) -> dict:
    try:
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=[ALGO])
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired or invalid") from exc
    if payload.get("typ") != kind:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong token type")
    return payload


bearer = HTTPBearer(auto_error=False)


def current_principal(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> Principal:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to continue")
    payload = decode(creds.credentials, "access")
    user = db.get(AppUser, payload["sub"])
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown user")
    return Principal(user.id, user.display_name, user.role, user.title)


def require(capability: str):
    """Dependency factory: `Depends(require("cases:decide"))`."""

    def guard(p: Annotated[Principal, Depends(current_principal)]) -> Principal:
        if capability not in p.capabilities:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Your role ({p.role}) cannot perform '{capability}'.",
            )
        return p

    return guard


CurrentUser = Annotated[Principal, Depends(current_principal)]
