#!/usr/bin/env python3
"""Regenerate ``app/bundled_starter_data.py`` from ``Developer_Commands.docx``."""

from __future__ import annotations

import pprint
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.docx_seed import parse_developer_commands_docx  # noqa: E402


def main() -> int:
    data = parse_developer_commands_docx()
    out = ROOT / "app" / "bundled_starter_data.py"
    generated = datetime.now(UTC).strftime("%Y-%m-%d")
    body = pprint.pformat(data, width=100, sort_dicts=False)
    out.write_text(
        f'''"""Bundled starter catalog parsed from ``Developer_Commands.docx``.

Regenerate after editing the Word file::

    uv run python scripts/generate_starter_data.py

Generated: {generated}
"""

from __future__ import annotations

STARTER_DATA: list[dict] = {body}
''',
        encoding="utf-8",
    )
    n_entries = sum(len(s["entries"]) for t in data for s in t["sections"])
    print(f"Wrote {out.relative_to(ROOT)} ({len(data)} topics, {n_entries} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
