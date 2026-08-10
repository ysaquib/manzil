#!/usr/bin/env python3
"""Check that every auth email template `supabase start` will read actually resolves.

Why this exists: the CLI resolves `content_path` from two *different* base
directories depending on which block the entry is in, and it validates them
eagerly — before Docker is contacted — so a wrong prefix fails the whole `test`
job at its first step with a message that names a random entry (the CLI iterates
a Go map). Verified against CLI 2.98.2:

    [auth.email.template.*]      relative to the PROCESS WORKING DIRECTORY
                                 (the repo root, which is where CI and
                                 AGENTS.md both run the CLI from)
    [auth.email.notification.*]  relative to the CONFIG DIRECTORY (supabase/)

"Fixing" one block to match the other is the exact mistake this guards, and it
has been made in both directions now. Run from the repo root:

    uv run python scripts/check_supabase_config.py
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG = REPO_ROOT / "supabase" / "config.toml"

# section → the directory the CLI joins its `content_path` against.
BASE_DIRS = {
    "template": REPO_ROOT,
    "notification": CONFIG.parent,
}


def problems() -> list[str]:
    email = tomllib.loads(CONFIG.read_text()).get("auth", {}).get("email", {})
    found: list[str] = []
    for section, base in BASE_DIRS.items():
        for name, entry in (email.get(section) or {}).items():
            path = entry.get("content_path")
            if not path:
                continue
            resolved = (base / path).resolve()
            if resolved.is_file():
                continue
            found.append(
                f"auth.email.{section}.{name}.content_path = {path!r}\n"
                f"    resolves to {resolved}, which does not exist.\n"
                f"    {section} paths are relative to {base.relative_to(REPO_ROOT) or '.'}/"
            )
    return found


def main() -> int:
    if not CONFIG.is_file():
        print(f"error: {CONFIG} not found", file=sys.stderr)
        return 1
    found = problems()
    if found:
        print(
            "supabase/config.toml points at email templates that do not exist.\n"
            "`supabase start` fails on these before it reaches Docker.\n",
            file=sys.stderr,
        )
        for problem in found:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "\nSee the comment above the template blocks in supabase/config.toml:\n"
            "  auth.email.template.*     → ./supabase/templates/<file>\n"
            "  auth.email.notification.* → ./templates/<file>",
            file=sys.stderr,
        )
        return 1
    print("supabase/config.toml: every auth email template resolves.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
