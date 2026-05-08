"""Import bundled developer-command rows into a user's notebook."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models import Entry, Section, Topic
from app.seed_data import STARTER_DATA
from app.slug import allocate_topic_slug as _allocate_slug_for_user

logger = logging.getLogger("devnotebook.services.seed")


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
        slug = _allocate_slug_for_user(db, user_id, name)
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
