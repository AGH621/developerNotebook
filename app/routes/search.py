"""Full-text search and global index HTML routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from sqlalchemy.orm import Session

from app.auth import require_auth
from app.database import get_db
from app.indexing import build_index_page_sections, search_entries
from app.models import User
from app.templating import templates

router = APIRouter()


@router.get("/search")
async def search_page(
    request: Request,
    q: Annotated[str | None, Query()] = None,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Full search page, HTMX results table (search page), or compact nav dropdown."""
    query = (q or "").strip()
    results = search_entries(db, user.id, query)

    hx = request.headers.get("hx-request") or ""
    is_htmx = hx.strip().lower() == "true"
    nav_view = (request.query_params.get("view") or "").strip().lower() == "nav"
    tpl = (
        "partials/nav_search_results.html"
        if is_htmx and nav_view
        else ("partials/search_results.html" if is_htmx else "search.html")
    )
    return templates.TemplateResponse(
        request,
        tpl,
        {
            "user": user,
            "query": query,
            "results": results,
        },
    )


@router.get("/index")
async def index_overview(
    request: Request,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Auto-generated alphabetical index: one table per starting letter."""
    letter_sections = build_index_page_sections(db, user.id)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "user": user,
            "letter_sections": letter_sections,
        },
    )
