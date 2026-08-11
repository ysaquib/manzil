from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


def _load_release_script() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts" / "bump_version.py"
    spec = importlib.util.spec_from_file_location("manzil_bump_version", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


release_script = _load_release_script()
next_version: Any = release_script.next_version
prepare_release: Any = release_script.prepare_release


@pytest.mark.parametrize(
    ("bump", "expected"),
    [("major", "2.0.0"), ("minor", "1.5.0"), ("patch", "1.4.10")],
)
def test_semver_bumps_are_deliberate_and_independent(
    bump: str,
    expected: str,
) -> None:
    assert next_version("1.4.9", bump) == expected  # type: ignore[arg-type]


def test_prepare_release_rolls_only_the_current_unreleased_section(tmp_path: Path) -> None:
    (tmp_path / "VERSION").write_text("0.1.0\n")
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## Unreleased — Phase 3\n\n- One change.\n\n"
        "## Unreleased — Phase 2\n\n- Historical section.\n"
    )

    version = prepare_release(tmp_path, "minor", "2026-08-11")

    assert version == "0.2.0"
    assert (tmp_path / "VERSION").read_text() == "0.2.0\n"
    changelog = (tmp_path / "CHANGELOG.md").read_text()
    assert "## Unreleased — Phase 3\n\n_No changes yet._" in changelog
    assert "## v0.2.0 — 2026-08-11\n\n- One change." in changelog
    assert "## Unreleased — Phase 2\n\n- Historical section." in changelog


def test_prepare_release_refuses_an_empty_changelog(tmp_path: Path) -> None:
    (tmp_path / "VERSION").write_text("0.1.0\n")
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## Unreleased — Phase 3\n\n_No changes yet._\n"
    )

    with pytest.raises(ValueError, match="no unreleased"):
        prepare_release(tmp_path, "patch", "2026-08-11")
