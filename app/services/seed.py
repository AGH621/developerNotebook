"""Import bundled developer-command rows into a user's notebook."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Entry, Section, Topic
from app.seed_data import STARTER_DATA, starter_topics_meta
from app.slug import allocate_topic_slug as _allocate_slug_for_user

logger = logging.getLogger("devnotebook.services.seed")


def starter_topics_for_user(db: Session, user_id: int) -> list[dict[str, int | str | bool]]:
    """Like :func:`starter_topics_meta` plus ``already_have`` per topic name (case-fold)."""
    existing = {
        str(n).casefold()
        for n in db.scalars(select(Topic.name).where(Topic.user_id == user_id)).all()
    }
    return [
        {
            **row,
            "already_have": str(row["name"]).casefold() in existing,
        }
        for row in starter_topics_meta()
    ]


def starter_topic_indices_available(db: Session, user_id: int) -> frozenset[int]:
    """Starter data indices the user does not already have as a topic title."""
    existing = {
        str(n).casefold()
        for n in db.scalars(select(Topic.name).where(Topic.user_id == user_id)).all()
    }
    return frozenset(
        i
        for i, blob in enumerate(STARTER_DATA)
        if str(blob["name"]).casefold() not in existing
    )


def populate_starter_data(
    db: Session,
    user_id: int,
    *,
    topic_indices: frozenset[int] | None = None,
    display_order_start: int | None = None,
) -> dict[str, int]:
    """Create topics, sections, and entries from :data:`STARTER_DATA`.

    Parameters
    ----------
    db : Session
        Active ORM session.
    user_id : int
        Primary key of the user who receives the cloned structure.
    topic_indices : frozenset[int] | None
        If provided, only topics whose index in ``STARTER_DATA`` is in this set
        are inserted (in ascending index order). If ``None``, all topics are
        inserted.
    display_order_start : int | None
        When ``None``, new topics use ``display_order`` ``0 .. n-1``. When set,
        the first inserted topic uses this value and each following topic
        increments by one (for appending to an existing notebook).

    Returns
    -------
    dict[str, int]
        Counts inserted under keys ``topics``, ``sections``, and ``entries``.

    Notes
    -----
    Leaves the transaction **uncommitted**. The caller must ``commit()`` (and
    handle rollback on error).
    """
    if topic_indices is None:
        blobs: list[dict] = list(STARTER_DATA)
    else:
        ordered = sorted(i for i in topic_indices if 0 <= i < len(STARTER_DATA))
        blobs = [STARTER_DATA[i] for i in ordered]

    order_base = 0 if display_order_start is None else display_order_start

    n_topics = n_sections = n_entries = 0
    for t_order, topic_blob in enumerate(blobs):
        name = str(topic_blob["name"])
        slug = _allocate_slug_for_user(db, user_id, name)
        topic = Topic(user_id=user_id, name=name, slug=slug, display_order=order_base + t_order)
        db.add(topic)
        db.flush()
        n_topics += 1

        for s_order, section_blob in enumerate(topic_blob["sections"]):
            section_name = section_blob.get("name")
            section = Section(
                topic_id=topic.id,
                name=section_name,
                display_order=s_order,
                notes=None,
            )
            db.add(section)
            db.flush()
            n_sections += 1

            for e_order, entry_blob in enumerate(section_blob["entries"]):
                db.add(
                    Entry(
                        section_id=section.id,
                        description=entry_blob["description"],
                        command=entry_blob["command"],
                        display_order=e_order,
                    ),
                )
                n_entries += 1

    logger.info(
        "Starter data staged for user_id=%s topics=%s sections=%s entries=%s",
        user_id,
        n_topics,
        n_sections,
        n_entries,
    )
    return {"topics": n_topics, "sections": n_sections, "entries": n_entries}
