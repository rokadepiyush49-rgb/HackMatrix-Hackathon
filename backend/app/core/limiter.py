"""Request rate limiting (per client address). In-memory for the MVP; Redis at scale."""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=["600/minute"])
