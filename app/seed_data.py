"""Starter notebook catalog bundled with the app.

Used at startup to populate the global ``StarterTopic`` tables when empty, and
to add any bundled topics missing from an incomplete catalog. User notebooks
are filled from that database catalog (see ``app.services.seed``).

Regenerate ``app/bundled_starter_data.py`` after editing ``Developer_Commands.docx``::

    uv run python scripts/generate_starter_data.py
"""

from __future__ import annotations

from app.bundled_starter_data import STARTER_DATA

__all__ = ["STARTER_DATA"]
