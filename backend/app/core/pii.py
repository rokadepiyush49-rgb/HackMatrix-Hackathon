"""PII tokenisation and display masking.

Phone numbers and ID numbers are HMAC-tokenised at ingest so they can be compared for
equality (shared-identifier detection) without being stored in the clear.
"""

import hashlib
import hmac

from app.core.config import get_settings


def tokenise(value: str | None, kind: str) -> str | None:
    if not value:
        return None
    key = get_settings().pii_hmac_key.encode()
    digest = hmac.new(key, f"{kind}:{value.strip().lower()}".encode(), hashlib.sha256)
    return f"{kind[:3]}_{digest.hexdigest()[:20]}"


def mask_tail(value: str | None, keep: int = 4) -> str:
    if not value:
        return "—"
    tail = value[-keep:]
    return "•" * max(0, len(value) - keep) + tail
