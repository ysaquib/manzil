"""P3-7a deterministic image discovery and normalization."""

from __future__ import annotations

import io

import pytest
from manzil_shared.config import IMAGE_MAX_DIM
from manzil_worker.enrich.images import ImageError, discover_image_urls, normalize_image
from PIL import Image


def _png(width: int = 1600, height: int = 800, color: str = "#3b82f6") -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), color).save(output, format="PNG")
    return output.getvalue()


def test_discovery_combines_metadata_markup_srcset_and_jsonld_in_order() -> None:
    page = """
    <meta property="og:image" content="/primary.jpg">
    <img src="/primary.jpg" srcset="/small.jpg 400w, /large.jpg 1200w">
    <img data-src="https://cdn.example/unit.png">
    <script type="application/ld+json">
      {"@type":"ApartmentComplex","image":[
        {"@type":"ImageObject","url":"/kitchen.webp"}
      ]}
    </script>
    """
    assert discover_image_urls(page, "https://listing.example/property") == [
        "https://listing.example/primary.jpg",
        "https://listing.example/large.jpg",
        "https://cdn.example/unit.png",
        "https://listing.example/kitchen.webp",
    ]


def test_normalize_resizes_to_webp_and_hashes_normalized_bytes() -> None:
    image = normalize_image(_png())
    assert image.width == IMAGE_MAX_DIM
    assert image.height == IMAGE_MAX_DIM // 2
    assert image.webp.startswith(b"RIFF") and b"WEBP" in image.webp[:16]
    assert normalize_image(_png()).content_hash == image.content_hash


def test_normalize_rejects_non_image_bytes() -> None:
    with pytest.raises(ImageError, match="invalid image"):
        normalize_image(b"not an image")
