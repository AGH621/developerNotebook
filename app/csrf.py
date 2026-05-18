"""CSRF middleware: starlette-csrf with form field support for classic HTML POSTs.

The upstream ``CSRFMiddleware`` creates ``Request(scope)`` without a
``receive`` callable, so ``request.form()`` is unavailable.  We override
``__call__`` to pre-read the body when the token might be in form data,
cache it for ``_get_submitted_csrf_token``, and supply a replay
``receive`` so downstream handlers can still read the body normally.
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import parse_qs

from starlette.requests import Request
from starlette.types import Receive, Scope, Send
from starlette_csrf.middleware import CSRFMiddleware

_FORM_CONTENT_TYPES = ("application/x-www-form-urlencoded", "multipart/form-data")


class CookieFormCSRFMiddleware(CSRFMiddleware):
    """Double-submit cookie CSRF; token may be sent as ``x-csrftoken`` or ``csrftoken`` form field."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        header_present = bool(request.headers.get(self.header_name))
        ctype = (request.headers.get("content-type") or "").lower()
        is_form = any(ct in ctype for ct in _FORM_CONTENT_TYPES)

        if (
            not header_present
            and is_form
            and request.method not in self.safe_methods
        ):
            body_parts: list[bytes] = []
            while True:
                message = await receive()
                body_parts.append(message.get("body", b""))
                if not message.get("more_body", False):
                    break
            body = b"".join(body_parts)
            scope["_csrf_cached_body"] = body

            replay_sent = False

            async def _replay_receive() -> dict:
                nonlocal replay_sent
                if not replay_sent:
                    replay_sent = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return {"type": "http.disconnect"}

            receive = _replay_receive

        await super().__call__(scope, receive, send)

    async def _get_submitted_csrf_token(self, request: Request) -> Optional[str]:
        header = request.headers.get(self.header_name)
        if header:
            return header
        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return None
        cached_body = request.scope.get("_csrf_cached_body")
        if cached_body is not None:
            params = parse_qs(cached_body.decode("utf-8", errors="replace"))
            token_values = params.get(self.cookie_name, [])
            if token_values:
                return token_values[0]
        return None
