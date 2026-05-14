"""Import bundled developer-command rows into a user's notebook."""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import Entry, Section, StarterEntry, StarterSection, StarterTopic, Topic
from app.slug import allocate_topic_slug as _allocate_slug_for_user

logger = logging.getLogger("devnotebook.services.seed")


def _starter_topics_ordered(db: Session) -> list[StarterTopic]:
    """Starter catalog rows in display order (matches bundled seed / admin ordering)."""
    return list(
        db.scalars(
            select(StarterTopic)
            .options(
                selectinload(StarterTopic.sections).selectinload(StarterSection.entries),
            )
            .order_by(StarterTopic.display_order.asc(), StarterTopic.id.asc()),
        ).all(),
    )


def _sorted_sections(topic: StarterTopic) -> list[StarterSection]:
    return sorted(topic.sections, key=lambda s: (s.display_order, s.id))


def _sorted_entries(section: StarterSection) -> list[StarterEntry]:
    return sorted(section.entries, key=lambda e: (e.display_order, e.id))


def starter_catalog_topic_count(db: Session) -> int:
    """Number of rows in the global starter catalog (``StarterTopic`` table)."""
    return int(db.scalar(select(func.count(StarterTopic.id))) or 0)


def starter_topics_meta(db: Session) -> list[dict[str, int | str]]:
    """Metadata for each starter topic (for onboarding and seed-topics UI).

    Rows are ordered alphabetically by topic name (Unicode case-fold) for
    display. Each ``index`` is the topic's position in catalog display order
    (``display_order``, then ``id``) and is the value submitted in ``topic``
    form fields.
    """
    topics = _starter_topics_ordered(db)
    result: list[dict[str, int | str]] = []
    for i, topic in enumerate(topics):
        sections = _sorted_sections(topic)
        n_entries = sum(len(_sorted_entries(s)) for s in sections)
        result.append(
            {
                "index": i,
                "name": str(topic.name),
                "n_sections": len(sections),
                "n_entries": n_entries,
            },
        )
    result.sort(key=lambda m: str(m["name"]).casefold())
    return result


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
        for row in starter_topics_meta(db)
    ]


def starter_topic_indices_available(db: Session, user_id: int) -> frozenset[int]:
    """Catalog indices the user does not already have as a topic title."""
    existing = {
        str(n).casefold()
        for n in db.scalars(select(Topic.name).where(Topic.user_id == user_id)).all()
    }
    topics = _starter_topics_ordered(db)
    return frozenset(
        i
        for i, t in enumerate(topics)
        if str(t.name).casefold() not in existing
    )


def populate_starter_data(
    db: Session,
    user_id: int,
    *,
    topic_indices: frozenset[int] | None = None,
    display_order_start: int | None = None,
) -> dict[str, int]:
    """Create topics, sections, and entries by copying the DB starter catalog.

    Parameters
    ----------
    db : Session
        Active ORM session.
    user_id : int
        Primary key of the user who receives the cloned structure.
    topic_indices : frozenset[int] | None
        If provided, only catalog topics whose index in display order is in this
        set are inserted (in ascending index order). If ``None``, the full
        catalog is copied.
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
    topics_orm = _starter_topics_ordered(db)
    if not topics_orm:
        logger.warning("Starter catalog is empty; nothing to copy for user_id=%s", user_id)
        return {"topics": 0, "sections": 0, "entries": 0}

    if topic_indices is None:
        selected = topics_orm
    else:
        ordered = sorted(i for i in topic_indices if 0 <= i < len(topics_orm))
        selected = [topics_orm[i] for i in ordered]

    order_base = 0 if display_order_start is None else display_order_start

    n_topics = n_sections = n_entries = 0
    for t_order, starter_topic in enumerate(selected):
        name = str(starter_topic.name)
        slug = _allocate_slug_for_user(db, user_id, name)
        topic = Topic(user_id=user_id, name=name, slug=slug, display_order=order_base + t_order)
        db.add(topic)
        db.flush()
        n_topics += 1

        for s_order, st_sec in enumerate(_sorted_sections(starter_topic)):
            sec = Section(
                topic_id=topic.id,
                name=st_sec.name,
                display_order=s_order,
                notes=st_sec.notes,
            )
            db.add(sec)
            db.flush()
            n_sections += 1

            for e_order, st_ent in enumerate(_sorted_entries(st_sec)):
                db.add(
                    Entry(
                        section_id=sec.id,
                        description=st_ent.description,
                        command=st_ent.command,
                        display_order=e_order,
                    ),
                )
                n_entries += 1

    logger.info(
        "Starter catalog staged for user_id=%s topics=%s sections=%s entries=%s",
        user_id,
        n_topics,
        n_sections,
        n_entries,
    )
    return {"topics": n_topics, "sections": n_sections, "entries": n_entries}
