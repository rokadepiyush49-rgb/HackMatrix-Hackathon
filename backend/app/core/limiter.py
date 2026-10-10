"""Request rate limiting, keyed by client address (X-Forwarded-For behind the load balancer).

`memory://` counts per process, which is right for one local server. With several API replicas
set SUTRA_RATE_LIMIT_STORAGE_URI=redis://… so every replica shares one counter.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import get_settings

limiter = Limiter(key_func=get_remote_address, default_limits=["600/minute"],
                  storage_uri=get_settings().rate_limit_storage_uri)
