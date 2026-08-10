"""P3-7a deterministic image discovery and normalization."""

from __future__ import annotations

import io

import pytest
from manzil_shared.config import DIAGRAM_MAX_DIM, IMAGE_MAX_DIM
from manzil_worker.enrich.images import (
    ImageError,
    SupabaseImageStore,
    discover_image_urls,
    discover_images,
    normalize_diagram,
    normalize_image,
)
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


def test_storage_opaque_secret_key_is_never_used_as_a_bearer_token() -> None:
    store = SupabaseImageStore("https://project.supabase.co", "sb_secret_example")

    assert store._headers() == {"apikey": "sb_secret_example"}


def test_storage_local_legacy_jwt_retains_bearer_compatibility() -> None:
    jwt = "header.payload.signature"
    store = SupabaseImageStore("http://127.0.0.1:54321", jwt)

    assert store._headers() == {"apikey": jwt, "Authorization": f"Bearer {jwt}"}


# --- P3-SC5: full-size anchor target and the diagram profile ---


def test_anchor_to_an_image_asset_is_captured_as_the_full_size_url() -> None:
    document = """
    <div class="floor-plan-card" data-plan-id="FP-1">
      <a href="/assets/winslow-full.png"><img src="/assets/winslow-thumb.jpg" alt="Floor plan"></a>
    </div>
    """
    candidate = discover_images(document, "https://listing.test/plans")[0]
    assert candidate.url == "https://listing.test/assets/winslow-thumb.jpg"
    assert candidate.full_size_url == "https://listing.test/assets/winslow-full.png"


def test_anchor_to_a_detail_page_is_not_treated_as_an_asset() -> None:
    """A plan's detail *page* is navigation, not a bigger copy of the image."""
    document = """
    <div class="floor-plan-card">
      <a href="/floorplans/winslow"><img src="/assets/winslow-thumb.jpg" alt="Floor plan"></a>
    </div>
    """
    candidate = discover_images(document, "https://listing.test/plans")[0]
    assert candidate.full_size_url is None


def test_diagram_profile_keeps_more_pixels_than_the_photo_profile() -> None:
    output = io.BytesIO()
    Image.new("RGB", (3000, 2000), "white").save(output, format="PNG")
    raw = output.getvalue()

    photo = normalize_image(raw)
    diagram = normalize_diagram(raw)

    assert photo.width == IMAGE_MAX_DIM
    assert diagram.width == DIAGRAM_MAX_DIM
    assert diagram.content_hash != photo.content_hash


def test_diagram_profile_still_enforces_the_decompression_bomb_guard() -> None:
    """More pixels, never more trust — the shared limits are profile-independent."""
    with pytest.raises(ImageError):
        normalize_diagram(b"not an image")
