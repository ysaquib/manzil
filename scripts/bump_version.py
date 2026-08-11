#!/usr/bin/env python3
"""Prepare VERSION and CHANGELOG.md for an intentional product release."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

Bump = Literal["major", "minor", "patch"]
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
UNRELEASED_HEADING = "## Unreleased — Phase 3"
EMPTY_UNRELEASED = "_No changes yet._"


@dataclass(frozen=True, order=True)
class Version:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, value: str) -> Version:
        match = SEMVER.fullmatch(value.strip())
        if match is None:
            raise ValueError(f"VERSION must be SemVer X.Y.Z, got {value!r}")
        return cls(*(int(part) for part in match.groups()))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def next_version(current: str, bump: Bump) -> str:
    version = Version.parse(current)
    if bump == "major":
        return str(Version(version.major + 1, 0, 0))
    if bump == "minor":
        return str(Version(version.major, version.minor + 1, 0))
    if bump == "patch":
        return str(Version(version.major, version.minor, version.patch + 1))
    raise ValueError(f"unknown bump: {bump}")


def roll_changelog(changelog: str, version: str, release_date: str) -> str:
    heading = f"## v{version} — {release_date}"
    if heading in changelog:
        raise ValueError(f"CHANGELOG.md already contains {heading}")
    marker = f"{UNRELEASED_HEADING}\n"
    start = changelog.find(marker)
    if start < 0:
        raise ValueError(f"CHANGELOG.md is missing {UNRELEASED_HEADING!r}")
    body_start = start + len(marker)
    next_section = changelog.find("\n## ", body_start)
    if next_section < 0:
        next_section = len(changelog)
    unreleased = changelog[body_start:next_section].strip()
    if not unreleased or unreleased == EMPTY_UNRELEASED:
        raise ValueError("CHANGELOG.md has no unreleased Phase 3 changes to release")
    replacement = f"{UNRELEASED_HEADING}\n\n{EMPTY_UNRELEASED}\n\n{heading}\n\n{unreleased}\n"
    return changelog[:start] + replacement + changelog[next_section:]


def prepare_release(root: Path, bump: Bump, release_date: str) -> str:
    version_path = root / "VERSION"
    changelog_path = root / "CHANGELOG.md"
    version = next_version(version_path.read_text(), bump)
    changelog = roll_changelog(changelog_path.read_text(), version, release_date)
    version_path.write_text(f"{version}\n")
    changelog_path.write_text(changelog)
    return version


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bump", choices=("major", "minor", "patch"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--date", default=datetime.now(UTC).date().isoformat())
    args = parser.parse_args()
    print(prepare_release(args.root, args.bump, args.date))


if __name__ == "__main__":
    main()
