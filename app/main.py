"""FastAPI application entry point."""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.database import Base, engine

logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("devnotebook")

_APP_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create database tables on startup."""
    import app.models  # noqa: F401 — registers models on Base.metadata

    Base.metadata.create_all(bind=engine)
    logger.info("Database tables ensured (create_all).")
    yield


def create_app(*, enable_lifespan: bool = True) -> FastAPI:
    """Build the FastAPI application (routers, static files, optional DB lifespan).

    Parameters
    ----------
    enable_lifespan : bool
        When ``True`` (production), run ``create_all`` on the process SQLite
        engine at startup. When ``False`` (tests), skip startup DB side effects
        so dependency overrides can use an isolated in-memory session.

    Returns
    -------
    FastAPI
        Configured application instance.
    """
    import app.models  # noqa: F401 — registers models on Base.metadata

    if enable_lifespan:
        application = FastAPI(lifespan=lifespan)
    else:
        application = FastAPI()

    application.mount("/static", StaticFiles(directory=str(_APP_DIR / "static")), name="static")

    from app.routes import entries, pages, sections, topics

    application.include_router(pages.router)
    application.include_router(topics.router)
    application.include_router(sections.router)
    application.include_router(entries.router)
    return application


app = create_app(enable_lifespan=True)
