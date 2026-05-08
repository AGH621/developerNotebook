"""URL slug helpers for topic titles (unique per user)."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Topic


def slug_base(name: str) -> str:
    """Normalize a topic title to a hyphenated slug stem.

    Parameters
    ----------
    name : str
        Topic display title.

    Returns
    -------
    str
        Lowercase fragment; literal ``topic`` when no alphanumeric remains.
    """
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s or "topic"


def allocate_topic_slug(
    session: Session,
    user_id: int,
    topic_name: str,
    *,
    exclude_topic_id: int | None = None,
) -> str:
    """Return a slug unique among ``user_id``'s topics for ``topic_name``.

    Parameters
    ----------
    session : Session
        Open ORM session for collision queries.
    user_id : int
        Owner scope.
    topic_name : str
        Source title for the base slug.
    exclude_topic_id : int or None
        Topic row to ignore when checking collisions (rename flow).

    Returns
    -------
    str
        Available slug, suffixing ``-2``, ``-3``, … as needed.
    """
    base = slug_base(topic_name)
    candidate = base
    n = 2
    while True:
        q = select(Topic.id).where(Topic.user_id == user_id, Topic.slug == candidate)
        if exclude_topic_id is not None:
            q = q.where(Topic.id != exclude_topic_id)
        clash = session.scalars(q).first()
        if clash is None:
            return candidate
        candidate = f"{base}-{n}"
        n += 1
