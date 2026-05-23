"""FastAPI application entry point."""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

from app.bootstrap import run_startup_tasks
from app.database import Base, SessionLocal, apply_sqlite_user_column_migrations, engine
from app.indexing import ensure_fts_table

logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("devnotebook")

_APP_DIR = Path(__file__).resolve().parent
_HEALTH_PATHS = frozenset({"/health"})


class _ConditionalTrustedHostMiddleware:
    """Trusted host validation, except Fly internal probes to ``/health``."""

    def __init__(self, app, *, allowed_hosts: list[str]):
        self.app = app
        self._trusted = TrustedHostMiddleware(app, allowed_hosts=allowed_hosts)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] in _HEALTH_PATHS:
            await self.app(scope, receive, send)
            return
        await self._trusted(scope, receive, send)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add baseline security headers; HSTS only in production."""

    def __init__(self, app, *, is_production: bool):
        super().__init__(app)
        self._is_production = is_production

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' https://unpkg.com https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline'"
        )
        if self._is_production:
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create database tables on startup and run bootstrap tasks."""
    import app.models  # noqa: F401 — registers models on Base.metadata

    Base.metadata.create_all(bind=engine)
    apply_sqlite_user_column_migrations(engine)
    ensure_fts_table(engine)
    logger.info("Database tables ensured (create_all).")
    db = SessionLocal()
    try:
        run_startup_tasks(db)
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()
    yield


def _rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> PlainTextResponse:  # noqa: ARG001
    return PlainTextResponse("Too many attempts. Please try again later.", status_code=429)


def create_app(*, enable_lifespan: bool = True) -> FastAPI:
    """Build the FastAPI application (routers, static files, optional DB lifespan).

    Parameters
    ----------
    enable_lifespan : bool
        When ``True`` (production), run ``create_all``, SQLite user-column
        migrations, and bootstrap tasks (admin from env variables, starter
        catalog seed) on the app's SQLite engine at startup. When ``False``
        (tests), skip startup side effects so dependency overrides can use an
        isolated in-memory session.

    Returns
    -------
    FastAPI
        Configured application instance.
    """
    import app.models  # noqa: F401 — registers models on Base.metadata

    is_production = os.environ.get("APP_ENV", "dev").strip().lower() == "production"
    fastapi_kwargs: dict = {}
    if enable_lifespan:
        fastapi_kwargs["lifespan"] = lifespan
    if is_production:
        fastapi_kwargs["docs_url"] = None
        fastapi_kwargs["redoc_url"] = None
        fastapi_kwargs["openapi_url"] = None

    application = FastAPI(**fastapi_kwargs)

    @application.get("/health", include_in_schema=False)
    async def health_check() -> PlainTextResponse:
        return PlainTextResponse("ok")

    from app.auth import SESSION_COOKIE_NAME, resolve_session_secret, session_cookie_secure
    from app.csrf import CookieFormCSRFMiddleware
    from app.rate_limit import limiter

    application.state.limiter = limiter
    application.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    application.mount("/static", StaticFiles(directory=str(_APP_DIR / "static")), name="static")

    from app.routes import admin, entries, pages, search, sections, topics

    application.include_router(pages.router)
    application.include_router(admin.router)
    application.include_router(topics.router)
    application.include_router(sections.router)
    application.include_router(entries.router)
    application.include_router(search.router)

    application.add_middleware(SlowAPIMiddleware)
    application.add_middleware(
        CookieFormCSRFMiddleware,
        secret=resolve_session_secret(),
        sensitive_cookies={SESSION_COOKIE_NAME},
        safe_methods={"GET", "HEAD", "OPTIONS"},
        cookie_secure=session_cookie_secure(),
        cookie_samesite="lax",
        cookie_httponly=False,
    )
    application.add_middleware(SecurityHeadersMiddleware, is_production=is_production)
    allowed_raw = os.environ.get("ALLOWED_HOSTS", "").strip()
    if allowed_raw:
        allowed_hosts = [h.strip() for h in allowed_raw.split(",") if h.strip()]
        if allowed_hosts:
            application.add_middleware(
                _ConditionalTrustedHostMiddleware,
                allowed_hosts=allowed_hosts,
            )
    elif is_production:
        logger.warning(
            "ALLOWED_HOSTS is not set in production. Set it to your domain(s) "
            "to prevent Host header attacks (e.g. ALLOWED_HOSTS=myapp.fly.dev).",
        )
    return application


app = create_app(enable_lifespan=True)
