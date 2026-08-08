"""Static assertions for production browser defenses owned by render.yaml."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BLUEPRINT = (ROOT / "render.yaml").read_text()
INDEX_HTML = (ROOT / "frontend" / "index.html").read_text()


def test_executable_javascript_is_external_and_same_origin() -> None:
    assert '<script src="/color-scheme.js"></script>' in INDEX_HTML
    assert "<script>" not in INDEX_HTML

    script_policy = BLUEPRINT.split("script-src", 1)[1].split(";", 1)[0]
    assert "'self'" in script_policy
    assert "'unsafe-inline'" not in script_policy
    assert "'unsafe-eval'" not in script_policy


def test_response_only_browser_defenses_are_versioned() -> None:
    assert "frame-ancestors 'none'" in BLUEPRINT
    assert "name: Referrer-Policy\n        value: no-referrer" in BLUEPRINT
    assert "name: X-Frame-Options\n        value: DENY" in BLUEPRINT
    assert "name: X-Content-Type-Options\n        value: nosniff" in BLUEPRINT
    assert "name: Strict-Transport-Security" in BLUEPRINT
    assert "value: max-age=31536000" in BLUEPRINT
