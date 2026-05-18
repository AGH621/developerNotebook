"""One-time startup tasks: env-admin account and starter catalog seed."""

from __future__ import annotations

import logging
import os

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import hash_password, validate_password
from app.models import StarterEntry, StarterSection, StarterTopic, User
from app.seed_data import STARTER_DATA

logger = logging.getLogger("devnotebook.bootstrap")


def bootstrap_admin_from_env(db: Session) -> None:
    """Create or promote the bootstrap admin from ``ADMIN_USERNAME`` / ``ADMIN_PASSWORD``.

    When both variables are unset or blank, does nothing. When only one is
    set, logs a warning and skips (misconfiguration). Existing users matching
    the username are promoted to ``is_admin`` without changing their password.
    """
    raw_u = os.environ.get("ADMIN_USERNAME", "")
    raw_p = os.environ.get("ADMIN_PASSWORD", "")
    username = raw_u.strip()
    password = raw_p.strip() if isinstance(raw_p, str) else ""
    any_u = raw_u.strip() != ""
    any_p = password != ""

    if not any_u and not any_p:
        return
    if not any_u or not any_p:
        logger.warning(
            "ADMIN_USERNAME and ADMIN_PASSWORD must both be set to bootstrap "
            "an admin; ignoring partial configuration.",
        )
        return

    existing = db.scalars(select(User).where(User.username == username)).first()
    if existing is None:
        pw_issue = validate_password(password)
        if pw_issue:
            logger.warning("Bootstrap admin: %s", pw_issue)
        db.add(
            User(
                username=username,
                password_hash=hash_password(password),
                is_admin=True,
                is_suspended=False,
            ),
        )
        logger.info("Bootstrap admin user created (username=%r).", username)
        return

    promoted = False
    if not existing.is_admin:
        existing.is_admin = True
        promoted = True

    logger.info(
        "Bootstrap admin: user %r already exists%s.",
        username,
        "; promoted to admin" if promoted else "",
    )


def seed_starter_catalog_if_empty(db: Session, topics_blob: list[dict]) -> bool:
    """If the starter catalog has no topics, insert rows from ``topics_blob``.

    Returns
    -------
    bool
        ``True`` if rows were inserted, ``False`` if the catalog was already
        populated.
    """
    n = db.scalar(select(func.count(StarterTopic.id))) or 0
    if n > 0:
        return False

    for t_order, topic_blob in enumerate(topics_blob):
        topic = StarterTopic(name=str(topic_blob["name"]), display_order=t_order)
        db.add(topic)
        db.flush()

        for s_order, section_blob in enumerate(topic_blob["sections"]):
            section_name = section_blob.get("name")
            notes_raw = section_blob.get("notes")
            notes_val = notes_raw if isinstance(notes_raw, str) else None
            section = StarterSection(
                topic_id=topic.id,
                name=section_name,
                display_order=s_order,
                notes=notes_val,
            )
            db.add(section)
            db.flush()

            for e_order, entry_blob in enumerate(section_blob["entries"]):
                db.add(
                    StarterEntry(
                        section_id=section.id,
                        description=entry_blob["description"],
                        command=entry_blob["command"],
                        display_order=e_order,
                    ),
                )

    logger.info(
        "Starter catalog seeded from bundled data (%s topics).",
        len(topics_blob),
    )
    return True


def run_startup_tasks(db: Session, *, starter_data: list[dict] | None = None) -> None:
    """Run admin bootstrap then optional starter-catalog seed."""
    bootstrap_admin_from_env(db)
    seed_starter_catalog_if_empty(db, starter_data if starter_data is not None else STARTER_DATA)
