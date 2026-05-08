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


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(_APP_DIR / "static")), name="static")

# Route routers (sections and entries wiring in Phase 5).
from app.routes import pages, topics

app.include_router(pages.router)
app.include_router(topics.router)
