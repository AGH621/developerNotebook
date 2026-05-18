"""Shared SlowAPI limiter keyed by client IP."""

from __future__ import annotations

import secrets

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


def rate_limit_key(request: Request) -> str:
    """Key by proxied IP in production; isolate pytest TestClient (host ``testclient``)."""
    client = request.client
    if client is not None and client.host == "testclient":
        return secrets.token_hex(16)
    return get_remote_address(request)


limiter = Limiter(key_func=rate_limit_key)
