"""Short-lived signed URLs for binary assets (thumbnails, page images, files).

`<img src>` can't send an Authorization header, so asset URLs carry an HMAC
signature over a *scope* (e.g. one document version) and an expiry instead.
The API only signs scopes for resources the requesting user owns, so a valid
signature proves that ownership check happened.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time

from app.core.config import Settings

DEFAULT_TTL_SECONDS = 3600


def _signature(scope: str, expires: int, secret: str) -> str:
    mac = hmac.new(secret.encode(), f"{scope}|{expires}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac[:18]).decode().rstrip("=")


def sign_scope(scope: str, settings: Settings, ttl: int = DEFAULT_TTL_SECONDS) -> str:
    """Return a query string `exp=..&sig=..` valid for at least `ttl` seconds."""
    # Expiry rounded to the hour keeps URLs stable, so browsers can cache the images.
    expires = (int(time.time()) + ttl) // 3600 * 3600 + 3600
    sig = _signature(scope, expires, settings.jwt_secret.get_secret_value())
    return f"exp={expires}&sig={sig}"


def verify_scope(scope: str, expires: int, sig: str, settings: Settings) -> bool:
    if expires < time.time():
        return False
    expected = _signature(scope, expires, settings.jwt_secret.get_secret_value())
    return hmac.compare_digest(expected, sig)
