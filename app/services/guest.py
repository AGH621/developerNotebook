"""Read-only guest access to admin-selected starter catalog topics."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import StarterEntry, StarterSection, StarterTopic


def guest_visible_topics(db: Session) -> list[StarterTopic]:
    """Starter topics marked visible to guest accounts, in display order."""
    return list(
        db.scalars(
            select(StarterTopic)
            .where(StarterTopic.guest_visible.is_(True))
            .order_by(StarterTopic.display_order.asc(), StarterTopic.id.asc()),
        ).all(),
    )


def guest_topic_by_slug(db: Session, slug: str) -> StarterTopic | None:
    """Load one guest-visible starter topic with sections and entries."""
    return db.scalars(
        select(StarterTopic)
        .where(StarterTopic.slug == slug, StarterTopic.guest_visible.is_(True))
        .options(
            selectinload(StarterTopic.sections).selectinload(StarterSection.entries),
        ),
    ).first()


def sorted_starter_sections(topic: StarterTopic) -> list[StarterSection]:
    return sorted(topic.sections, key=lambda s: (s.display_order, s.id))


def sorted_starter_entries(section: StarterSection) -> list[StarterEntry]:
    return sorted(section.entries, key=lambda e: (e.display_order, e.id))
