"""Shared SlowAPI limiter keyed by client IP."""

from __future__ import annotations

import secrets

from slowapi import Limiter
from starlette.requests import Request

_PROXY_HEADERS = ("fly-client-ip", "x-forwarded-for", "x-real-ip")


def _get_real_client_ip(request: Request) -> str:
    """Extract the real client IP honoring reverse-proxy headers.

    Checks Fly-Client-IP, X-Forwarded-For, and X-Real-IP (in that order)
    before falling back to the direct connection address.
    """
    for header in _PROXY_HEADERS:
        value = request.headers.get(header)
        if value:
            return value.split(",")[0].strip()
    client = request.client
    return client.host if client else "127.0.0.1"


def rate_limit_key(request: Request) -> str:
    """Key by proxied IP in production; isolate pytest TestClient (host ``testclient``)."""
    client = request.client
    if client is not None and client.host == "testclient":
        return secrets.token_hex(16)
    return _get_real_client_ip(request)


limiter = Limiter(key_func=rate_limit_key)
