"""Parse ``Developer_Commands.docx`` into the ``STARTER_DATA`` structure."""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph


def _resolve_docx_path(candidates: tuple[Path, ...] | None = None) -> Path:
    """Return the first existing path among known Word document locations."""
    if candidates is None:
        root = Path(__file__).resolve().parent.parent
        candidates = (
            root / "Developer_Commands.docx",
            root / "Developer Commands.docx",
        )
    for path in candidates:
        if path.is_file():
            return path
    names = ", ".join(str(p) for p in candidates)
    raise FileNotFoundError(
        f"No developer-commands Word file found at: {names}",
    )


def _cell_text(cell: object) -> str:
    """Collapse whitespace inside a single table cell."""
    text = getattr(cell, "text", "") or ""
    return " ".join(text.replace("\xa0", " ").split())


def _paragraph_style_and_text(paragraph: Paragraph) -> tuple[str, str]:
    """Return stripped text and normalized style name."""
    text = paragraph.text.strip() if paragraph.text else ""
    style = ""
    if paragraph.style and paragraph.style.name:
        style = paragraph.style.name
    return text, style


def _paragraph_skip(style: str, text: str) -> bool:
    """Return True when a paragraph carries no substantive structure."""
    if not text.strip():
        return True
    st = style or ""
    if st.lower().startswith("toc"):
        return True
    if st == "TOC Heading":
        return True
    if st == "Intense Quote" and "TABLE OF CONTENTS" in text.upper():
        return True
    if text.strip() == "Return to ToC":
        return True
    return False


def _finalize_pending(
    sections: list[dict],
    pending: dict[str, object] | None,
) -> None:
    """Append pending section dict if it has at least one entry."""
    if pending is None:
        return
    entries = pending.get("entries") or []
    if not entries:
        return
    sections.append(
        {"name": pending["name"], "entries": list(entries)},
    )


def parse_developer_commands_docx(docx_path: Path | None = None) -> list[dict]:
    """Build starter topic rows from the Word cheatsheet layout.

    The document is expected to use **Heading 1** for topic titles,
    **Heading 2**/**Heading 3** for section titles, and two-column tables
    (description, command). Topics whose first table arrives before any
    section heading receive one section named ``None``.

    Parameters
    ----------
    docx_path : Path or None
        Explicit ``.docx`` location. Defaults to bundled repository paths.

    Returns
    -------
    list of dict
        Same nested shape as legacy ``STARTER_DATA`` (``name``, ``sections``,
        entries with ``description`` and ``command``).

    Raises
    ------
    FileNotFoundError
        If no readable ``.docx`` exists under the default filenames.
    """
    path = _resolve_docx_path() if docx_path is None else docx_path
    if not path.is_file():
        raise FileNotFoundError(f"Word document not found: {path}")

    document = Document(str(path))
    topics_out: list[dict] = []
    current_topic: str | None = None
    topic_sections: list[dict] = []
    pending: dict[str, object] | None = None

    for el in document.element.body:
        tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if tag == "p":
            para = Paragraph(el, document)
            text, style = _paragraph_style_and_text(para)
            if _paragraph_skip(style, text):
                continue

            if style == "Heading 1":
                _finalize_pending(topic_sections, pending)
                pending = None
                if current_topic is not None and topic_sections:
                    topics_out.append(
                        {"name": current_topic, "sections": list(topic_sections)},
                    )
                current_topic = text
                topic_sections = []
                continue

            if style in ("Heading 2", "Heading 3"):
                if current_topic is None:
                    continue
                _finalize_pending(topic_sections, pending)
                pending = {"name": text, "entries": []}
                continue

            continue

        if tag != "tbl":
            continue

        if current_topic is None:
            continue

        tbl = Table(el, document)
        if pending is None:
            pending = {"name": None, "entries": []}
        rows = tbl.rows
        for row in rows:
            cells = row.cells
            if len(cells) < 2:
                continue
            desc = _cell_text(cells[0])
            cmd = _cell_text(cells[1])
            if not desc and not cmd:
                continue
            if not desc:
                desc = cmd
            pend_entries = pending.setdefault("entries", [])
            pend_entries.append({"description": desc, "command": cmd})

    _finalize_pending(topic_sections, pending)
    if current_topic is not None and topic_sections:
        topics_out.append(
            {"name": current_topic, "sections": list(topic_sections)},
        )

    return [t for t in topics_out if t.get("sections")]
