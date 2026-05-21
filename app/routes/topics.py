"""Topic CRUD routes (HTMX partials for the home-page topic grid)."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.auth import require_can_write
from app.database import get_db
from app.models import Section, Topic, User
from app.slug import allocate_topic_slug
from app.templating import templates

router = APIRouter()
topics_log = logging.getLogger("devnotebook.routes.topics")


def _topic_owned(db: Session, topic_id: int, user_id: int) -> Topic | None:
    return db.scalars(
        select(Topic).where(Topic.id == topic_id, Topic.user_id == user_id),
    ).first()


def _topic_with_sections(db: Session, topic_id: int) -> Topic | None:
    """Topic row with sections loaded (used by topic page partials)."""
    return db.scalars(
        select(Topic)
        .where(Topic.id == topic_id)
        .options(selectinload(Topic.sections)),
    ).first()


@router.post("/topics")
async def create_topic(
    request: Request,
    name: Annotated[str | None, Form()] = None,
    user: User = Depends(require_can_write),
    db: Session = Depends(get_db),
):
    """Create an empty topic with one default unnamed section.

    Parameters
    ----------
    request : Request
        Incoming request used for selective responses.
    name : str or None
        Optional display name from the ``name`` form field (defaults trimmed).
    user : User
        Authenticated user from :func:`app.auth.require_auth`.
    db : Session
        Database session from dependency injection.

    Returns
    -------
    TemplateResponse
        Renders ``partials/topic_card.html`` for the new topic (HTMX target).
    """
    label = (name or "").strip() or "New topic"
    next_ord = db.scalar(
        select(func.coalesce(func.max(Topic.display_order), -1)).where(Topic.user_id == user.id),
    )
    slot = int(next_ord) + 1 if next_ord is not None else 0
    slug = allocate_topic_slug(db, user.id, label)
    topic = Topic(user_id=user.id, name=label, slug=slug, display_order=slot)
    db.add(topic)
    db.flush()
    section = Section(topic_id=topic.id, name=None, display_order=0, notes=None)
    db.add(section)
    db.commit()
    db.refresh(topic)
    topics_log.info("Topic created id=%s user_id=%s", topic.id, user.id)
    return templates.TemplateResponse(
        request,
        "partials/topic_card.html",
        {"topic": topic},
    )


@router.get("/topics/{topic_id}/edit")
async def topic_edit_partial(
    request: Request,
    topic_id: int,
    user: User = Depends(require_can_write),
    db: Session = Depends(get_db),
):
    """Return an inline rename form replacing the topic card view.

    Parameters
    ----------
    request : Request
        Incoming HTTP request.
    topic_id : int
        Primary key for the topic to edit.
    user : User
        Authenticated notebook owner.
    db : Session
        Database session.

    Returns
    -------
    TemplateResponse
        Fragment ``topic_card_edit.html`` when authorized.
    Response
        **404** when the topic does not belong to ``user``.
    """
    topic = _topic_owned(db, topic_id, user.id)
    if topic is None:
        topics_log.warning(
            "Topic edit forbidden or missing topic_id=%s user_id=%s",
            topic_id,
            user.id,
        )
        return Response(status_code=404)
    return templates.TemplateResponse(
        request,
        "partials/topic_card_edit.html",
        {"topic": topic},
    )


@router.get("/topics/{topic_id}/card")
async def topic_card_partial(
    request: Request,
    topic_id: int,
    user: User = Depends(require_can_write),
    db: Session = Depends(get_db),
):
    """Return the read-only topic card partial (restore after cancelling edit).

    Parameters
    ----------
    request : Request
        Incoming HTTP request.
    topic_id : int
        Topic primary key.
    user : User
        Authenticated owner.
    db : Session
        Database session.

    Returns
    -------
    TemplateResponse
        Fragment ``topic_card.html`` when authorized.
    Response
        **404** when the topic is absent or owned by someone else.
    """
    topic = _topic_owned(db, topic_id, user.id)
    if topic is None:
        topics_log.warning(
            "Topic card fetch forbidden missing topic_id=%s user_id=%s",
            topic_id,
            user.id,
        )
        return Response(status_code=404)
    return templates.TemplateResponse(
        request,
        "partials/topic_card.html",
        {"topic": topic},
    )


@router.put("/topics/reorder")
async def reorder_topics(
    topic_order: Annotated[str, Form()],
    user: User = Depends(require_can_write),
    db: Session = Depends(get_db),
):
    """Reorder topic cards by assigning ``display_order`` from posted IDs.

    Parameters
    ----------
    topic_order : str
        Comma-separated integer topic IDs in presentation order (``id1,id2``).
    user : User
        Authenticated notebook owner.
    db : Session
        Database session.

    Returns
    -------
    Response
        **204** when all IDs matched the user's topics, **400** if the list is
        invalid or mismatched.

    Notes
    -----
    Called from SortableJS after drag-and-drop.
    """
    raw = [p.strip() for p in topic_order.split(",") if p.strip()]
    try:
        ids_ordered = [int(x) for x in raw]
    except ValueError:
        topics_log.warning("Topic reorder rejected bad ids user_id=%s", user.id)
        return Response(status_code=400)

    if not ids_ordered:
        topics_log.warning("Topic reorder rejected empty ids user_id=%s", user.id)
        return Response(status_code=400)

    owned = db.scalars(select(Topic.id).where(Topic.user_id == user.id)).all()
    if set(ids_ordered) != set(owned) or len(ids_ordered) != len(owned):
        topics_log.warning(
            "Topic reorder rejected mismatched set user_id=%s expected=%s got=%s",
            user.id,
            sorted(owned),
            ids_ordered,
        )
        return Response(status_code=400)

    mapping = {tid: idx for idx, tid in enumerate(ids_ordered)}
    for topic in db.scalars(select(Topic).where(Topic.user_id == user.id)).all():
        topic.display_order = mapping[topic.id]
    db.commit()
    topics_log.info("Topics reordered user_id=%s count=%s", user.id, len(ids_ordered))
    return Response(status_code=204)


@router.put("/topics/{topic_id}")
async def rename_topic(
    request: Request,
    topic_id: int,
    name: Annotated[str, Form()],
    user: User = Depends(require_can_write),
    db: Session = Depends(get_db),
):
    """Rename a topic and regenerate its slug.

    Parameters
    ----------
    request : Request
        Used for templated partial responses.
    topic_id : int
        Identifier of the topic to update.
    name : str
        New display title from ``name``.
    user : User
        Authenticated user.
    db : Session
        Database session.

    Returns
    -------
    TemplateResponse
        Fresh ``topic_card.html`` fragment on success.
    Response
        **404** when the topic is not owned by ``user``.
    """
    topic = _topic_owned(db, topic_id, user.id)
    if topic is None:
        topics_log.warning(
            "Topic rename forbidden missing topic_id=%s user_id=%s",
            topic_id,
            user.id,
        )
        return Response(status_code=404)
    label = name.strip()
    if not label:
        label = "Untitled topic"
    topic.name = label
    topic.slug = allocate_topic_slug(db, user.id, label, exclude_topic_id=topic.id)
    db.commit()
    topics_log.info(
        "Topic renamed id=%s user_id=%s slug=%s",
        topic.id,
        user.id,
        topic.slug,
    )
    return templates.TemplateResponse(
        request,
        "partials/topic_card.html",
        {"topic": topic},
    )


@router.delete("/topics/{topic_id}")
async def delete_topic(
    topic_id: int,
    user: User = Depends(require_can_write),
    db: Session = Depends(get_db),
):
    """Delete a topic and cascade-remove its sections and entries.

    Parameters
    ----------
    topic_id : int
        Topic to remove.
    user : User
        Authenticated user.
    db : Session
        Database session.

    Returns
    -------
    Response
        Empty **200** body for HTMX ``delete`` swap, or **404** when not found.
    """
    topic = _topic_owned(db, topic_id, user.id)
    if topic is None:
        topics_log.warning(
            "Topic delete forbidden missing topic_id=%s user_id=%s",
            topic_id,
            user.id,
        )
        return Response(status_code=404)
    db.delete(topic)
    db.commit()
    topics_log.info("Topic deleted id=%s user_id=%s", topic_id, user.id)
    return Response(status_code=200)