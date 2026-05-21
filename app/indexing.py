"""SQLite FTS5 shadow index (optional sync) and alphabetized global index grouping.

``entries_fts`` backs nothing at read time; search queries ``entries`` with SQL substring
matching so results stay correct even if the FTS table is empty or stale. Entry writes
still update ``entries_fts`` for possible future use.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from sqlalchemy import or_, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models import Entry, Section, StarterEntry, StarterSection, StarterTopic, Topic

FTS_VIRTUAL_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
    description,
    command
)
"""

VERB_SYNONYMS: dict[str, str] = {
    "remove": "delete",
    "rm": "delete",
    "create": "add",
    "new": "add",
    "mk": "add",
    "show": "view",
    "display": "view",
    "print": "view",
    "exec": "run",
    "execute": "run",
}

_CANONICAL_VERBS: frozenset[str] = frozenset(
    {
        "add",
        "delete",
        "list",
        "view",
        "run",
        "get",
        "set",
        "push",
        "pull",
        "clone",
        "commit",
        "merge",
        "branch",
        "checkout",
        "install",
        "update",
        "download",
        "copy",
        "move",
        "rename",
        "start",
        "stop",
        "build",
        "test",
        "lint",
        "format",
        "fix",
        "open",
        "close",
        "find",
        "grep",
        "search",
        "save",
        "load",
        "export",
        "import",
        "clear",
        "reset",
        "sync",
        "connect",
        "attach",
        "detach",
    },
)


def ensure_fts_table(engine: Engine) -> None:
    """Create the FTS5 external-content shadow table ``entries_fts`` if absent."""
    with engine.begin() as conn:
        conn.execute(text(FTS_VIRTUAL_DDL))


def fts_insert(db: Session, entry_id: int, description: str, command: str) -> None:
    db.execute(
        text(
            "INSERT INTO entries_fts(rowid, description, command) "
            "VALUES (:rowid, :description, :command)",
        ),
        {"rowid": entry_id, "description": description, "command": command},
    )


def fts_delete(db: Session, entry_id: int, description: str, command: str) -> None:
    del description, command
    db.execute(
        text("DELETE FROM entries_fts WHERE rowid = :rowid"),
        {"rowid": entry_id},
    )


def fts_update(
    db: Session,
    entry_id: int,
    old_description: str,
    old_command: str,
    new_description: str,
    new_command: str,
) -> None:
    fts_delete(db, entry_id, old_description, old_command)
    fts_insert(db, entry_id, new_description, new_command)


def fts_rebuild(db: Session) -> None:
    db.execute(text("DELETE FROM entries_fts"))
    db.execute(
        text(
            "INSERT INTO entries_fts(rowid, description, command) "
            "SELECT id, description, command FROM entries",
        ),
    )


def _sql_like_escape(fragment: str) -> str:
    """Escape ``\\``, ``%``, and ``_`` for LIKE patterns using ``ESCAPE '\\'``."""
    return fragment.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_entries(db: Session, user_id: int, query: str) -> list[dict[str, Any]]:
    """Return entry rows matching ``query`` (tokens AND semantics), scoped to ``user_id``.

    Uses case-insensitive substring matching on description and command so results do not
    depend on the FTS shadow table staying in sync with ``entries``.
    """
    trimmed = query.strip()
    if not trimmed:
        return []
    tokens = [p.strip() for p in re.split(r"\s+", trimmed) if p.strip()]
    if not tokens:
        return []

    stmt = (
        select(
            Entry.id.label("entry_id"),
            Entry.description,
            Entry.command,
            Topic.name.label("topic_name"),
            Topic.slug.label("topic_slug"),
            Section.name.label("section_name"),
        )
        .join(Section, Entry.section_id == Section.id)
        .join(Topic, Section.topic_id == Topic.id)
        .where(Topic.user_id == user_id)
    )

    for tok in tokens:
        pattern = f"%{_sql_like_escape(tok)}%"
        stmt = stmt.where(
            or_(
                Entry.description.ilike(pattern, escape="\\"),
                Entry.command.ilike(pattern, escape="\\"),
            ),
        )

    stmt = stmt.order_by(Entry.description.asc(), Entry.id.asc()).limit(50)

    rows = db.execute(stmt).mappings().all()
    return [
        {
            "entry_id": row["entry_id"],
            "description": row["description"],
            "command": row["command"],
            "topic_name": row["topic_name"],
            "topic_slug": row["topic_slug"],
            "section_name": row["section_name"] or "",
        }
        for row in rows
    ]


def search_guest_entries(db: Session, query: str) -> list[dict[str, Any]]:
    """Search guest-visible starter catalog entries matching ``query``."""
    trimmed = query.strip()
    if not trimmed:
        return []
    tokens = [p.strip() for p in re.split(r"\s+", trimmed) if p.strip()]
    if not tokens:
        return []

    stmt = (
        select(
            StarterEntry.id.label("entry_id"),
            StarterEntry.description,
            StarterEntry.command,
            StarterTopic.name.label("topic_name"),
            StarterTopic.slug.label("topic_slug"),
            StarterSection.name.label("section_name"),
        )
        .join(StarterSection, StarterEntry.section_id == StarterSection.id)
        .join(StarterTopic, StarterSection.topic_id == StarterTopic.id)
        .where(StarterTopic.guest_visible.is_(True))
    )

    for tok in tokens:
        pattern = f"%{_sql_like_escape(tok)}%"
        stmt = stmt.where(
            or_(
                StarterEntry.description.ilike(pattern, escape="\\"),
                StarterEntry.command.ilike(pattern, escape="\\"),
            ),
        )

    stmt = stmt.order_by(StarterEntry.description.asc(), StarterEntry.id.asc()).limit(50)

    rows = db.execute(stmt).mappings().all()
    return [
        {
            "entry_id": row["entry_id"],
            "description": row["description"],
            "command": row["command"],
            "topic_name": row["topic_name"],
            "topic_slug": row["topic_slug"],
            "section_name": row["section_name"] or "",
        }
        for row in rows
    ]


def _first_word(description: str) -> str | None:
    parts = description.strip().split(None, 1)
    return parts[0] if parts else None


def extract_action(description: str) -> str:
    """Return a canonical verb for the opening token of ``description``, or ``other``."""
    token = _first_word(description)
    if not token:
        return "other"

    token = token.strip(".,!?;:()[]{}'\"/")
    if not token:
        return "other"

    head = token.split("-", 1)[0]
    lc = "".join(ch for ch in head.casefold() if ch.isalnum())
    if not lc:
        return "other"

    if lc in VERB_SYNONYMS:
        return VERB_SYNONYMS[lc]
    if lc in _CANONICAL_VERBS:
        return lc
    return "other"


def _browse_letter(description: str) -> str:
    s = description.strip()
    if not s:
        return "#"
    ch = s[0]
    return ch.upper() if ch.isalpha() else "#"


def _description_first_word_key(description: str) -> str:
    """Lowercase comparable form of the first whitespace-delimited word."""
    s = description.strip()
    if not s:
        return ""
    token = s.split()[0].strip(".,!?;:()[]{}'\"/")
    return token.casefold()


def build_global_index(db: Session, user_id: int) -> dict[str, list[dict[str, Any]]]:
    """Entries grouped by extracted action verb, ordered alphabetically by action."""
    rows = db.execute(
        select(
            Entry.id,
            Entry.description,
            Entry.command,
            Topic.name.label("topic_name"),
            Topic.slug.label("topic_slug"),
            Section.name.label("section_name"),
        )
        .select_from(Entry)
        .join(Section, Entry.section_id == Section.id)
        .join(Topic, Section.topic_id == Topic.id)
        .where(Topic.user_id == user_id)
        .order_by(Entry.description.asc(), Entry.id.asc()),
    ).all()

    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        desc = row.description
        item = {
            "entry_id": row.id,
            "description": desc,
            "command": row.command,
            "topic_name": row.topic_name,
            "topic_slug": row.topic_slug,
            "section_name": row.section_name or "",
            "action": extract_action(desc),
        }
        grouped[item["action"]].append(item)

    for action_rows in grouped.values():
        action_rows.sort(
            key=lambda r: (
                str(r["description"]).casefold(),
                r["entry_id"],
            ),
        )

    return {action: grouped[action] for action in sorted(grouped.keys(), key=str.casefold)}


def build_index_page_sections(db: Session, user_id: int) -> list[dict[str, Any]]:
    """Letter headings with a single sorted table per letter (first word of description)."""

    stmt = (
        select(
            Entry.id,
            Entry.description,
            Entry.command,
            Topic.name.label("topic_name"),
            Topic.slug.label("topic_slug"),
            Section.name.label("section_name"),
        )
        .select_from(Entry)
        .join(Section, Entry.section_id == Section.id)
        .join(Topic, Section.topic_id == Topic.id)
        .where(Topic.user_id == user_id)
        .order_by(Entry.description.asc(), Entry.id.asc())
    )

    by_letter: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in db.execute(stmt).all():
        desc = row.description
        item = {
            "entry_id": row.id,
            "description": desc,
            "command": row.command,
            "topic_name": row.topic_name,
            "topic_slug": row.topic_slug,
            "section_name": row.section_name or "",
        }
        by_letter[_browse_letter(desc)].append(item)

    sections: list[dict[str, Any]] = []
    for letter in sorted(
        by_letter.keys(),
        key=lambda L: ("\uffff", L.lower()) if L == "#" else (L.casefold(), L),
    ):
        rows_here = by_letter[letter]
        rows_here.sort(
            key=lambda r: (
                _description_first_word_key(str(r["description"])),
                str(r["description"]).casefold(),
                int(r["entry_id"]),
            ),
        )
        anchor = "sym" if letter == "#" else letter
        sections.append({"letter": letter, "anchor": anchor, "entries": rows_here})

    return sections


def build_index_page_sections_guest(db: Session) -> list[dict[str, Any]]:
    """Letter-grouped index for guest-visible starter catalog entries."""
    stmt = (
        select(
            StarterEntry.id,
            StarterEntry.description,
            StarterEntry.command,
            StarterTopic.name.label("topic_name"),
            StarterTopic.slug.label("topic_slug"),
            StarterSection.name.label("section_name"),
        )
        .select_from(StarterEntry)
        .join(StarterSection, StarterEntry.section_id == StarterSection.id)
        .join(StarterTopic, StarterSection.topic_id == StarterTopic.id)
        .where(StarterTopic.guest_visible.is_(True))
        .order_by(StarterEntry.description.asc(), StarterEntry.id.asc())
    )

    by_letter: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in db.execute(stmt).all():
        desc = row.description
        item = {
            "entry_id": row.id,
            "description": desc,
            "command": row.command,
            "topic_name": row.topic_name,
            "topic_slug": row.topic_slug,
            "section_name": row.section_name or "",
        }
        by_letter[_browse_letter(desc)].append(item)

    sections: list[dict[str, Any]] = []
    for letter in sorted(
        by_letter.keys(),
        key=lambda L: ("\uffff", L.lower()) if L == "#" else (L.casefold(), L),
    ):
        rows_here = by_letter[letter]
        rows_here.sort(
            key=lambda r: (
                _description_first_word_key(str(r["description"])),
                str(r["description"]).casefold(),
                int(r["entry_id"]),
            ),
        )
        anchor = "sym" if letter == "#" else letter
        sections.append({"letter": letter, "anchor": anchor, "entries": rows_here})

    return sections
