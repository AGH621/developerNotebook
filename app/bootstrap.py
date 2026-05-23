"""One-time startup tasks: env-admin account and starter catalog seed."""

from __future__ import annotations

import logging
import os
import secrets

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import hash_password, validate_password
from app.models import StarterEntry, StarterSection, StarterTopic, User
from app.seed_data import STARTER_DATA
from app.settings import ensure_app_settings
from app.slug import allocate_starter_topic_slug

logger = logging.getLogger("devnotebook.bootstrap")

DEFAULT_GUEST_USERNAME = "__guest__"


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
            logger.error(
                "Bootstrap admin NOT created: %s "
                "Set a stronger ADMIN_PASSWORD and redeploy.",
                pw_issue,
            )
            return
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


def _insert_starter_topics_from_blob(
    db: Session,
    topics_blob: list[dict],
    *,
    display_order_start: int,
) -> int:
    """Insert starter catalog rows from ``topics_blob``; return topics inserted."""
    for offset, topic_blob in enumerate(topics_blob):
        name = str(topic_blob["name"])
        topic = StarterTopic(
            name=name,
            slug=allocate_starter_topic_slug(db, name),
            display_order=display_order_start + offset,
        )
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

    return len(topics_blob)


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

    _insert_starter_topics_from_blob(db, topics_blob, display_order_start=0)
    logger.info(
        "Starter catalog seeded from bundled data (%s topics).",
        len(topics_blob),
    )
    return True


def ensure_missing_starter_topics(db: Session, topics_blob: list[dict]) -> int:
    """Add bundled topics that are not yet present in the starter catalog."""
    existing_names = {
        str(name).casefold()
        for name in db.scalars(select(StarterTopic.name)).all()
    }
    missing = [
        topic_blob
        for topic_blob in topics_blob
        if str(topic_blob["name"]).casefold() not in existing_names
    ]
    if not missing:
        return 0

    next_order = int(
        db.scalar(select(func.coalesce(func.max(StarterTopic.display_order), -1))) or -1,
    )
    added = _insert_starter_topics_from_blob(
        db,
        missing,
        display_order_start=next_order + 1,
    )
    logger.info("Starter catalog: added %s missing bundled topics.", added)
    return added


def ensure_starter_topic_slugs(db: Session) -> None:
    """Backfill missing slugs on starter catalog rows (legacy databases)."""
    topics = db.scalars(select(StarterTopic).order_by(StarterTopic.id.asc())).all()
    for topic in topics:
        slug = (topic.slug or "").strip()
        if slug:
            continue
        topic.slug = allocate_starter_topic_slug(db, topic.name, exclude_topic_id=topic.id)


def bootstrap_guest_user(db: Session) -> None:
    """Ensure a single read-only guest account exists for one-click browsing."""
    raw = os.environ.get("GUEST_USERNAME", DEFAULT_GUEST_USERNAME)
    username = raw.strip() or DEFAULT_GUEST_USERNAME

    existing_guest = db.scalars(select(User).where(User.is_guest.is_(True))).first()
    if existing_guest is not None:
        if existing_guest.username != username:
            logger.warning(
                "Guest account already exists as %r; GUEST_USERNAME=%r ignored.",
                existing_guest.username,
                username,
            )
        return

    name_taken = db.scalars(select(User.id).where(User.username == username)).first()
    if name_taken is not None:
        logger.warning(
            "Cannot create guest account: username %r is already taken by a non-guest user.",
            username,
        )
        return

    db.add(
        User(
            username=username,
            password_hash=hash_password(secrets.token_urlsafe(32)),
            is_guest=True,
            is_admin=False,
            is_suspended=False,
        ),
    )
    logger.info("Guest account created (username=%r).", username)


def run_startup_tasks(db: Session, *, starter_data: list[dict] | None = None) -> None:
    """Run admin bootstrap then optional starter-catalog seed."""
    ensure_app_settings(db)
    bootstrap_admin_from_env(db)
    blob = starter_data if starter_data is not None else STARTER_DATA
    seed_starter_catalog_if_empty(db, blob)
    ensure_missing_starter_topics(db, blob)
    ensure_starter_topic_slugs(db)
    bootstrap_guest_user(db)
