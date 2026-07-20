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


def test_srcset_keeps_largest_variant_when_urls_contain_commas() -> None:
    """Cloudinary-style transform segments carry internal commas (c_fill,w_640).

    Splitting the srcset on every comma shattered each URL into fragments and
    resolved the trailing fragment against the page base, fabricating a URL
    that never existed and 404s.
    """
    small = "https://cdn.example/image/upload/c_fill,f_auto,q_auto,w_320/abc.jpg"
    large = "https://cdn.example/image/upload/c_fill,f_auto,q_auto,w_640/abc.jpg"
    page = f'<img srcset="{small} 320w, {large} 640w">'

    assert discover_image_urls(page, "https://listing.example/property") == [large]


def test_srcset_handles_density_descriptors_and_missing_descriptors() -> None:
    page = (
        '<img srcset="https://cdn.example/a,b/one.jpg 1x, https://cdn.example/a,b/two.jpg 2x">'
        '<img srcset="https://cdn.example/x,y/bare.jpg">'
    )
    assert discover_image_urls(page, "https://listing.example/p") == [
        "https://cdn.example/a,b/two.jpg",
        "https://cdn.example/x,y/bare.jpg",
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
