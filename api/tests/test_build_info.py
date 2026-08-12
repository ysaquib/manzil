from __future__ import annotations

from manzil_api.build_info import api_build_info, build_sha, feedback_build_context, release_version


def test_build_sha_prefers_render_then_ci_then_local(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    assert build_sha() == "dev"

    monkeypatch.setenv("GITHUB_SHA", "ci123456789")
    assert build_sha() == "ci123456789"

    monkeypatch.setenv("RENDER_GIT_COMMIT", "render123456789")
    assert build_sha() == "render123456789"


def test_build_info_exposes_only_public_release_identity(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("RENDER_GIT_COMMIT", "abcdef0123456789")
    info = api_build_info("production").model_dump()
    release = release_version()

    assert info == {
        "service": "api",
        "release_version": release,
        "build_sha": "abcdef0123456789",
        "build_id": f"{release}+abcdef0",
        "environment": "production",
    }


def test_feedback_context_replaces_a_spoofed_api_suffix_and_keeps_api_build(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("GITHUB_SHA", "abcdef0123456789")
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)

    context = feedback_build_context(
        "frontend 0.1.0+1234567 · api spoofed",
        "staging",
    )

    assert context == f"frontend 0.1.0+1234567 · api {release_version()}+abcdef0"
    assert len(context) <= 100
