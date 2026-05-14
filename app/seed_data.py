"""
FIXME: Ask Cursor about whether the Word file data can be loaded into the database rather than parsed fresh for each new user. If not, how does it make it over to the deployment host?

TODO: STARTER_DATA is built by parsing the .docx at import time. This means:

The .docx file must be present on the deployment host (bundled in the Docker image).
The parsing runs once when the module is first imported, then the result is cached in memory for the process lifetime -- so it's not re-parsed per user, just re-read from the in-memory list.
This will work fine as long as the Developer_Commands.docx is included in the Docker image (via COPY in the Dockerfile). But it's a runtime dependency on a binary file, which is a bit fragile. The alternative the FIXME hints at -- pre-parsing the data into a static Python dict -- would be more robust for deployment. That said, this is a design tradeoff, not a bug.

Starter notebook data loaded from the Word cheatsheet. Used at startup to
populate the global ``StarterTopic`` catalog when empty; user notebooks are
then filled from that database catalog (see ``app.services.seed``).
"""

from __future__ import annotations

from docx.opc.exceptions import PackageNotFoundError

from app.docx_seed import parse_developer_commands_docx

# Used when no Word file is present (minimal checkout, CI, tests).
_FALLBACK_STARTER_DATA: list[dict] = [
    {
        "name": "Git",
        "sections": [
            {
                "name": "Branches",
                "entries": [
                    {"description": "Delete a local branch", "command": "git branch -d <branch>"},
                ],
            },
        ],
    },
    {
        "name": "Flask",
        "sections": [
            {
                "name": None,
                "entries": [
                    {"description": "Run dev server", "command": "flask run --debug"},
                ],
            },
        ],
    },
]

try:
    # Resolved at import time from ``Developer_Commands.docx`` when available.
    STARTER_DATA: list[dict] = parse_developer_commands_docx()
except (FileNotFoundError, PackageNotFoundError):
    STARTER_DATA = _FALLBACK_STARTER_DATA
