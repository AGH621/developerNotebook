"""Import bundled developer-command rows into a user's notebook."""

from __future__ import annotations

import logging
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Entry, Section, Topic
from app.seed_data import STARTER_DATA

logger = logging.getLogger("devnotebook.services.seed")


def _slug_base(name: str) -> str:
    """Normalize a topic title to a hyphenated slug stem.

    Parameters
    ----------
    name : str
        Topic display title.

    Returns
    -------
    str
        Lowercase slug fragment; literal ``topic`` when nothing alphanumeric remains.
    """
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s or "topic"


def _allocate_slug(session: Session, user_id: int, topic_name: str) -> str:
    """Return a slug for ``topic_name`` that is unique for ``user_id``.

    Parameters
    ----------
    session : Session
        Open ORM session for collision checks.
    user_id : int
        Owner scope for uniqueness.
    topic_name : str
        Source title used to build the base slug.

    Returns
    -------
    str
        Unused slug, appending ``-2``, ``-3``, … if the base is taken.
    """
    base = _slug_base(topic_name)
    candidate = base
    n = 2
    while True:
        clash = session.scalars(
            select(Topic.id).where(Topic.user_id == user_id, Topic.slug == candidate),
        ).first()
        if clash is None:
            return candidate
        candidate = f"{base}-{n}"
        n += 1


def populate_starter_data(db: Session, user_id: int) -> dict[str, int]:
    """Create topics, sections, and entries from :data:`STARTER_DATA`.

    Parameters
    ----------
    db : Session
        Active ORM session.
    user_id : int
        Primary key of the user who receives the cloned structure.

    Returns
    -------
    dict[str, int]
        Counts inserted under keys ``topics``, ``sections``, and ``entries``.

    Notes
    -----
    Leaves the transaction **uncommitted**. The caller must ``commit()`` (and
    handle rollback on error).
    """
    n_topics = n_sections = n_entries = 0
    for t_order, topic_blob in enumerate(STARTER_DATA):
        name = str(topic_blob["name"])
        slug = _allocate_slug(db, user_id, name)
        topic = Topic(user_id=user_id, name=name, slug=slug, display_order=t_order)
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
