"""Security and rendering contracts for Admin-managed Demo publication."""

from __future__ import annotations

import httpx
import pytest
from manzil_worker.ops.demo_publication import _render_map


@pytest.mark.asyncio
async def test_static_maps_failure_never_leaks_the_server_key() -> None:
    secret = "maps-server-secret-that-must-not-reach-admin"

    async def fail(request: httpx.Request) -> httpx.Response:
        assert secret in str(request.url)  # proves the risky request shape exists
        return httpx.Response(403, request=request, text="denied")

    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
        with pytest.raises(RuntimeError) as caught:
            await _render_map(client, (42.33, -83.05), 15, (640, 260), False, secret)

    assert str(caught.value) == "Google Static Maps returned HTTP 403"
    assert secret not in str(caught.value)


@pytest.mark.asyncio
async def test_static_maps_refuses_a_successful_non_image_response() -> None:
    async def not_an_image(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request, content=b"quota exceeded")

    async with httpx.AsyncClient(transport=httpx.MockTransport(not_an_image)) as client:
        with pytest.raises(RuntimeError, match="non-PNG"):
            await _render_map(client, (42.33, -83.05), 15, (640, 260), False, "secret")
