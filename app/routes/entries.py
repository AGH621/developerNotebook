"""Entry CRUD routes (HTMX partials for section entry tables)."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.auth import require_auth
from app.database import get_db
from app.models import Entry, Section, Topic, User
from app.templating import templates

router = APIRouter()
entries_log = logging.getLogger("devnotebook.routes.entries")


def _entry_owned(db: Session, entry_id: int, user_id: int) -> Entry | None:
    return db.scalars(
        select(Entry)
        .join(Section)
        .join(Topic)
        .where(Entry.id == entry_id, Topic.user_id == user_id)
        .options(selectinload(Entry.section)),
    ).first()


def _section_owned_for_user(db: Session, section_id: int, user_id: int) -> Section | None:
    return db.scalars(
        select(Section)
        .join(Topic)
        .where(Section.id == section_id, Topic.user_id == user_id),
    ).first()


@router.post("/sections/{section_id}/entries")
async def create_entry(
    request: Request,
    section_id: int,
    description: Annotated[str | None, Form()] = None,
    command: Annotated[str | None, Form()] = None,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Append a command entry to a section owned by the current user.

    Parameters
    ----------
    request : Request
        Incoming request for template rendering.
    section_id : int
        Parent section primary key.
    description : str or None
        Short label from the ``description`` field.
    command : str or None
        Command text from the ``command`` field.
    user : User
        Authenticated owner.
    db : Session
        Database session.

    Returns
    -------
    TemplateResponse
        Renders ``partials/entry_row.html`` for the new row.
    Response
        **404** when the section is missing or not owned by ``user``.
    """
    section = _section_owned_for_user(db, section_id, user.id)
    if section is None:
        entries_log.warning(
            "Entry create forbidden section_id=%s user_id=%s",
            section_id,
            user.id,
        )
        return Response(status_code=404)

    desc = (description or "").strip()
    cmd = (command or "").strip()
    next_ord = db.scalar(
        select(func.coalesce(func.max(Entry.display_order), -1)).where(
            Entry.section_id == section_id,
        ),
    )
    slot = int(next_ord) + 1 if next_ord is not None else 0
    entry = Entry(section_id=section_id, description=desc, command=cmd, display_order=slot)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    entries_log.info(
        "Entry created id=%s section_id=%s user_id=%s",
        entry.id,
        section_id,
        user.id,
    )
    return templates.TemplateResponse(
        request,
        "partials/entry_row.html",
        {"entry": entry},
    )


@router.get("/entries/{entry_id}/edit")
async def entry_edit_partial(
    request: Request,
    entry_id: int,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Return an inline two-field edit row for a command entry.

    Parameters
    ----------
    request : Request
        Incoming HTTP request.
    entry_id : int
        Entry primary key.
    user : User
        Authenticated owner.
    db : Session
        Database session.

    Returns
    -------
    TemplateResponse
        Renders ``partials/entry_edit.html`` when authorized.
    Response
        **404** when the entry is absent or not owned.
    """
    entry = _entry_owned(db, entry_id, user.id)
    if entry is None:
        entries_log.warning(
            "Entry edit forbidden entry_id=%s user_id=%s",
            entry_id,
            user.id,
        )
        return Response(status_code=404)
    return templates.TemplateResponse(
        request,
        "partials/entry_edit.html",
        {"entry": entry},
    )


@router.get("/entries/{entry_id}/row")
async def entry_row_partial(
    request: Request,
    entry_id: int,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Return the read-only entry table row (used to cancel inline edits).

    Parameters
    ----------
    request : Request
        Incoming HTTP request.
    entry_id : int
        Entry primary key.
    user : User
        Authenticated owner.
    db : Session
        Database session.

    Returns
    -------
    TemplateResponse
        Renders ``partials/entry_row.html`` when authorized.
    Response
        **404** when the entry is absent or not owned.
    """
    entry = _entry_owned(db, entry_id, user.id)
    if entry is None:
        entries_log.warning(
            "Entry row forbidden entry_id=%s user_id=%s",
            entry_id,
            user.id,
        )
        return Response(status_code=404)
    return templates.TemplateResponse(
        request,
        "partials/entry_row.html",
        {"entry": entry},
    )


@router.put("/entries/reorder")
async def reorder_entries(
    entry_order: Annotated[str, Form()],
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Reorder entries inside one section from a SortableJS ID list.

    Parameters
    ----------
    entry_order : str
        Comma-separated entry IDs for a single section in display order.
    user : User
        Authenticated notebook owner.
    db : Session
        Database session.

    Returns
    -------
    Response
        **204** when successful, **400** for invalid lists, **404** when IDs do
        not belong to the user.
    """
    raw = [p.strip() for p in entry_order.split(",") if p.strip()]
    try:
        ids_ordered = [int(x) for x in raw]
    except ValueError:
        entries_log.warning("Entry reorder rejected bad ids user_id=%s", user.id)
        return Response(status_code=400)

    if not ids_ordered:
        entries_log.warning("Entry reorder rejected empty ids user_id=%s", user.id)
        return Response(status_code=400)

    first = _entry_owned(db, ids_ordered[0], user.id)
    if first is None:
        return Response(status_code=404)

    section_id = first.section_id
    owned = db.scalars(select(Entry.id).where(Entry.section_id == section_id)).all()
    if set(ids_ordered) != set(owned) or len(ids_ordered) != len(owned):
        entries_log.warning(
            "Entry reorder mismatched section_id=%s user_id=%s",
            section_id,
            user.id,
        )
        return Response(status_code=400)

    mapping = {eid: idx for idx, eid in enumerate(ids_ordered)}
    for row in db.scalars(select(Entry).where(Entry.section_id == section_id)).all():
        row.display_order = mapping[row.id]
    db.commit()
    entries_log.info(
        "Entries reordered section_id=%s user_id=%s count=%s",
        section_id,
        user.id,
        len(ids_ordered),
    )
    return Response(status_code=204)


@router.put("/entries/{entry_id}")
async def update_entry(
    request: Request,
    entry_id: int,
    description: Annotated[str, Form()],
    command: Annotated[str, Form()],
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Update an entry's description and command text.

    Parameters
    ----------
    request : Request
        Request used for template rendering.
    entry_id : int
        Entry primary key.
    description : str
        New description field.
    command : str
        New command field.
    user : User
        Authenticated owner.
    db : Session
        Database session.

    Returns
    -------
    TemplateResponse
        Fresh ``partials/entry_row.html`` on success.
    Response
        **404** when not found / unauthorized.
    """
    entry = _entry_owned(db, entry_id, user.id)
    if entry is None:
        entries_log.warning(
            "Entry update forbidden entry_id=%s user_id=%s",
            entry_id,
            user.id,
        )
        return Response(status_code=404)

    entry.description = (description or "").strip()
    entry.command = (command or "").strip()
    db.commit()
    db.refresh(entry)
    entries_log.info("Entry updated id=%s user_id=%s", entry_id, user.id)
    return templates.TemplateResponse(
        request,
        "partials/entry_row.html",
        {"entry": entry},
    )


@router.delete("/entries/{entry_id}")
async def delete_entry(
    entry_id: int,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Delete a command entry row.

    Parameters
    ----------
    entry_id : int
        Entry primary key.
    user : User
        Authenticated owner.
    db : Session
        Database session.

    Returns
    -------
    Response
        **200** empty body for HTMX ``delete`` swap, **404** when not allowed.
    """
    entry = _entry_owned(db, entry_id, user.id)
    if entry is None:
        entries_log.warning(
            "Entry delete forbidden entry_id=%s user_id=%s",
            entry_id,
            user.id,
        )
        return Response(status_code=404)
    sid = entry.section_id
    db.delete(entry)
    db.commit()
    entries_log.info("Entry deleted id=%s section_id=%s user_id=%s", entry_id, sid, user.id)
    return Response(status_code=200)
