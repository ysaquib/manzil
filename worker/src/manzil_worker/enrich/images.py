"""P3-7 image ingestion primitives.

Discovery is deterministic, downloads reuse the fetcher's SSRF discipline, and
normalization produces content-addressed WebP objects.  VISION consumes only
these stored objects; it never fetches arbitrary model-supplied URLs.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urljoin, urlsplit

import httpx
from lxml import etree, html
from manzil_shared.config import (
    DIAGRAM_MAX_DIM,
    DIAGRAM_WEBP_QUALITY,
    FETCH_MAX_REDIRECTS,
    IMAGE_CLASSIFY_MAX_DIM,
    IMAGE_CLASSIFY_WEBP_QUALITY,
    IMAGE_FETCH_TIMEOUT_SECONDS,
    IMAGE_MAX_DIM,
    IMAGE_MAX_DOWNLOAD_BYTES,
    IMAGE_MAX_PIXELS,
    IMAGE_WEBP_QUALITY,
    MAX_STORED_IMAGES,
)
from manzil_shared.errors import PrivateAddressRefused
from PIL import Image, ImageOps, UnidentifiedImageError

from manzil_worker.fetching.ssrf import pin_target, screen_url

_IMAGE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ManzilImageFetcher/1.0)",
    "Accept": "image/avif,image/webp,image/png,image/jpeg,*/*;q=0.2",
}


class ImageError(ValueError):
    """A candidate is not a safe, decodable image and should be skipped."""


@dataclass(frozen=True)
class NormalizedImage:
    content_hash: str
    webp: bytes
    width: int
    height: int


@dataclass(frozen=True)
class DiscoveredImage:
    """One image candidate plus evidence available without visual inference."""

    url: str
    page_order: int
    discovery_mechanism: str
    alt: str | None = None
    title: str | None = None
    caption: str | None = None
    containing_floor_plan_card: bool = False
    source_native_plan_id: str | None = None
    nearby_plan_label: str | None = None
    # P3-SC5: listing pages routinely wrap a small diagram thumbnail in an
    # anchor pointing at the full-size asset. That link is the legible copy;
    # IMAGE_FETCH prefers it for diagrams and ignores it for ordinary photos.
    full_size_url: str | None = None


class ImageObjectStore(Protocol):
    async def put(self, path: str, content: bytes) -> None: ...
    async def get(self, path: str) -> bytes: ...
    # Only the explicit P3-SC5 purge path calls this. Nothing in the pipeline
    # deletes stored bytes — inactive evidence is retained while its Property
    # exists (§9.3 third-party diagram posture).
    async def delete(self, path: str) -> None: ...


DownloadImage = Callable[[str], Awaitable[bytes]]


def _absolute_http_url(value: str | None, base_url: str) -> str | None:
    if not value or value.startswith("data:"):
        return None
    url = urljoin(base_url, value.strip())
    if not url.startswith(("http://", "https://")):
        return None
    return url


def _srcset_urls(value: str | None) -> Iterable[str]:
    """Return the largest variant from a srcset/data-srcset attribute.

    Candidates are `url [descriptor]` pairs separated by commas, but a URL may
    itself contain commas — Cloudinary and Imgix put their transform segment in
    the path (`c_fill,f_auto,q_auto,w_640`). Splitting the attribute on every
    comma therefore shatters such URLs into fragments, and the trailing fragment
    resolves against the page base into a URL that never existed and 404s. Walk
    whitespace-separated tokens instead and treat only a *trailing* comma as a
    candidate boundary, which is where the separator actually sits.
    """
    if not value:
        return ()
    candidates: list[str] = []
    expect_url = True
    for token in value.split():
        boundary = token.endswith(",")
        token = token.rstrip(",")
        if expect_url and token:
            candidates.append(token)
        # Otherwise this token is a width/density descriptor — carries no URL.
        expect_url = boundary
    # srcset is conventionally ordered from smaller to larger. Keep the best
    # variant instead of spending the Property cap on multiple resolutions of
    # the same photo.
    return candidates[-1:]


_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".bmp", ".tif", ".tiff")


def _image_href(value: str | None) -> str | None:
    """Return `value` only when it points at an image asset, else None.

    A floor-plan thumbnail is often wrapped in a link to the full-size file,
    but just as often in a link to the plan's detail *page*. Suffix-checking
    the path keeps the second case out — following it would download HTML.
    """
    if not value:
        return None
    path = urlsplit(value).path.lower()
    return value if path.endswith(_IMAGE_SUFFIXES) else None


def _json_image_urls(value: object, *, image_context: bool = False) -> Iterable[str]:
    """Walk JSON-LD while only treating image-shaped fields as image URLs."""
    if isinstance(value, list):
        for item in value:
            yield from _json_image_urls(item, image_context=image_context)
    elif isinstance(value, dict):
        node_type = value.get("@type")
        in_image = image_context or node_type in {"ImageObject", "https://schema.org/ImageObject"}
        for key, item in value.items():
            if key.lower() in {"image", "images", "thumbnailurl", "contenturl"}:
                if isinstance(item, str):
                    yield item
                else:
                    yield from _json_image_urls(item, image_context=True)
            elif key.lower() == "url" and in_image and isinstance(item, str):
                yield item
            elif isinstance(item, (dict, list)):
                yield from _json_image_urls(item, image_context=in_image)


def discover_images(
    document: str, base_url: str, *, limit: int = MAX_STORED_IMAGES * 4
) -> list[DiscoveredImage]:
    """Return de-duplicated candidates with Source-local DOM context.

    The wider discovery cap leaves room for download failures and byte-level
    duplicates; IMAGE_FETCH applies the final ``MAX_STORED_IMAGES`` cap after
    hashing.
    """
    try:
        root = html.fromstring(document, base_url=base_url)
    except (ValueError, etree.ParserError):
        return []

    raw_candidates: list[tuple[str, dict[str, object]]] = []
    raw_candidates.extend(
        (value, {"discovery_mechanism": "metadata"})
        for value in root.xpath("//meta[@property='og:image']/@content")
    )
    raw_candidates.extend(
        (value, {"discovery_mechanism": "metadata"})
        for value in root.xpath("//meta[@name='twitter:image']/@content")
    )
    raw_candidates.extend(
        (value, {"discovery_mechanism": "metadata"})
        for value in root.xpath("//link[@rel='image_src']/@href")
    )
    for node in root.xpath("//img | //source"):
        card = next(
            iter(
                node.xpath(
                    "ancestor::*[contains(translate(@class,'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
                    "'abcdefghijklmnopqrstuvwxyz'),'floor-plan') or @data-plan-id or "
                    "@data-floor-plan-id][1]"
                )
            ),
            None,
        )
        native_id = None
        label = None
        caption = None
        if card is not None:
            native_id = card.get("data-plan-id") or card.get("data-floor-plan-id")
            labels = card.xpath(
                ".//*[self::h1 or self::h2 or self::h3 or self::h4 or "
                "contains(@class,'plan-name')]/text()"
            )
            label = next((str(value).strip() for value in labels if str(value).strip()), None)
        figure = next(iter(node.xpath("ancestor::figure[1]")), None)
        if figure is not None:
            captions = figure.xpath(".//figcaption//text()")
            joined = " ".join(str(value).strip() for value in captions if str(value).strip())
            caption = joined or None
        # An enclosing anchor whose target is itself an image is the full-size
        # copy of this thumbnail. Only image-suffixed targets qualify — a plan
        # detail page is a navigation link, not an asset.
        anchor = next(iter(node.xpath("ancestor::a[@href][1]")), None)
        full_size = _image_href(anchor.get("href")) if anchor is not None else None
        context: dict[str, object] = {
            "discovery_mechanism": "markup",
            "alt": node.get("alt"),
            "title": node.get("title"),
            "caption": caption,
            "containing_floor_plan_card": card is not None,
            "source_native_plan_id": native_id,
            "nearby_plan_label": label,
            "full_size_url": full_size,
        }
        for value in (node.get("src"), node.get("data-src"), node.get("data-lazy-src")):
            if value:
                raw_candidates.append((value, context))
        raw_candidates.extend(
            (value, {**context, "discovery_mechanism": "srcset"})
            for value in _srcset_urls(node.get("srcset") or node.get("data-srcset"))
        )
    for raw in root.xpath("//script[@type='application/ld+json']/text()"):
        try:
            raw_candidates.extend(
                (value, {"discovery_mechanism": "json_ld"})
                for value in _json_image_urls(json.loads(raw))
            )
        except (json.JSONDecodeError, TypeError):
            continue

    seen: set[str] = set()
    output: list[DiscoveredImage] = []
    for candidate, context in raw_candidates:
        url = _absolute_http_url(candidate, base_url)
        if url is None or url in seen:
            continue
        seen.add(url)
        output.append(
            DiscoveredImage(
                url=url,
                page_order=len(output),
                discovery_mechanism=str(context["discovery_mechanism"]),
                alt=context.get("alt") if isinstance(context.get("alt"), str) else None,
                title=context.get("title") if isinstance(context.get("title"), str) else None,
                caption=context.get("caption") if isinstance(context.get("caption"), str) else None,
                containing_floor_plan_card=bool(context.get("containing_floor_plan_card", False)),
                source_native_plan_id=(
                    context.get("source_native_plan_id")
                    if isinstance(context.get("source_native_plan_id"), str)
                    else None
                ),
                nearby_plan_label=(
                    context.get("nearby_plan_label")
                    if isinstance(context.get("nearby_plan_label"), str)
                    else None
                ),
                full_size_url=(
                    _absolute_http_url(str(context["full_size_url"]), base_url)
                    if isinstance(context.get("full_size_url"), str)
                    else None
                ),
            )
        )
        if len(output) >= limit:
            break
    return output


def discover_image_urls(
    document: str, base_url: str, *, limit: int = MAX_STORED_IMAGES * 4
) -> list[str]:
    """Compatibility wrapper for callers that need only URLs."""
    return [candidate.url for candidate in discover_images(document, base_url, limit=limit)]


def _normalize(data: bytes, *, max_dim: int, quality: int) -> NormalizedImage:
    """Decode, orient, resize, and encode one image as deterministic-ish WebP.

    Byte and decompression-bomb limits are profile-independent: a diagram gets
    more pixels, never more trust.
    """
    if not data or len(data) > IMAGE_MAX_DOWNLOAD_BYTES:
        raise ImageError("image is empty or exceeds IMAGE_MAX_DOWNLOAD_BYTES")
    try:
        with Image.open(io.BytesIO(data)) as opened:
            if opened.width * opened.height > IMAGE_MAX_PIXELS:
                raise ImageError("image exceeds IMAGE_MAX_PIXELS")
            image = ImageOps.exif_transpose(opened)
            image.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGBA" if "transparency" in image.info else "RGB")
            output = io.BytesIO()
            image.save(output, format="WEBP", quality=quality, method=6)
            webp = output.getvalue()
            return NormalizedImage(
                content_hash=hashlib.sha256(webp).hexdigest(),
                webp=webp,
                width=image.width,
                height=image.height,
            )
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as error:
        raise ImageError(f"invalid image: {error}") from error


def normalize_image(data: bytes) -> NormalizedImage:
    """Ordinary listing-photo profile (§P3-7a)."""
    return _normalize(data, max_dim=IMAGE_MAX_DIM, quality=IMAGE_WEBP_QUALITY)


def normalize_diagram(data: bytes) -> NormalizedImage:
    """Floor Plan diagram profile (§P3-SC5): more pixels, higher quality.

    Diagrams carry room labels and dimensions that the photo profile renders
    unreadable. The exact numbers stay provisional until the §7.5 legibility
    comparison fixes them.
    """
    return _normalize(data, max_dim=DIAGRAM_MAX_DIM, quality=DIAGRAM_WEBP_QUALITY)


def classification_thumbnail(data: bytes) -> bytes:
    """Create an unstored low-resolution classifier input."""
    try:
        with Image.open(io.BytesIO(data)) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            image.thumbnail(
                (IMAGE_CLASSIFY_MAX_DIM, IMAGE_CLASSIFY_MAX_DIM),
                Image.Resampling.LANCZOS,
            )
            output = io.BytesIO()
            image.save(
                output,
                format="WEBP",
                quality=IMAGE_CLASSIFY_WEBP_QUALITY,
                method=6,
            )
            return output.getvalue()
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as error:
        raise ImageError(f"invalid classifier image: {error}") from error


def difference_hash(data: bytes) -> str:
    """Return a deterministic 64-bit dHash as 16 lowercase hex chars."""
    try:
        with Image.open(io.BytesIO(data)) as opened:
            gray = ImageOps.exif_transpose(opened).convert("L").resize(
                (9, 8), Image.Resampling.LANCZOS
            )
            pixels = list(gray.get_flattened_data())
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as error:
        raise ImageError(f"invalid perceptual-hash image: {error}") from error
    bits = 0
    for row in range(8):
        for column in range(8):
            bits = (bits << 1) | int(
                pixels[row * 9 + column] > pixels[row * 9 + column + 1]
            )
    return f"{bits:016x}"


async def download_image(url: str) -> bytes:
    """Download one image with redirect screening and IP pinning (§16)."""
    current = url
    try:
        async with httpx.AsyncClient(
            headers=_IMAGE_HEADERS,
            follow_redirects=False,
            timeout=IMAGE_FETCH_TIMEOUT_SECONDS,
        ) as client:
            for _ in range(FETCH_MAX_REDIRECTS + 1):
                addresses = await screen_url(current)
                pinned, host_header, sni = pin_target(current, addresses[0])
                async with client.stream(
                    "GET",
                    pinned,
                    headers={"Host": host_header},
                    extensions={"sni_hostname": sni},
                ) as response:
                    if response.is_redirect and response.has_redirect_location:
                        current = urljoin(current, response.headers["location"])
                        continue
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").lower()
                    if content_type and not content_type.startswith("image/"):
                        raise ImageError(f"non-image content type {content_type!r}")
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > IMAGE_MAX_DOWNLOAD_BYTES:
                            raise ImageError("image exceeds IMAGE_MAX_DOWNLOAD_BYTES")
                        chunks.append(chunk)
                    return b"".join(chunks)
    except PrivateAddressRefused:
        raise
    except httpx.HTTPError as error:
        raise ImageError(f"image download failed: {error}") from error
    raise ImageError(f"too many redirects (> {FETCH_MAX_REDIRECTS})")


class SupabaseImageStore:
    """Private Storage bucket writer using the service-role REST surface."""

    def __init__(self, url: str, service_role_key: str, bucket: str = "property-images") -> None:
        self._url = url.rstrip("/")
        self._key = service_role_key
        self._bucket = bucket

    @classmethod
    def from_env(cls) -> SupabaseImageStore | None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        return cls(url, key) if url and key else None

    async def put(self, path: str, content: bytes) -> None:
        endpoint = f"{self._url}/storage/v1/object/{self._bucket}/{path}"
        headers = {
            "Authorization": f"Bearer {self._key}",
            "apikey": self._key,
            "Content-Type": "image/webp",
            "x-upsert": "true",
        }
        async with httpx.AsyncClient(timeout=IMAGE_FETCH_TIMEOUT_SECONDS) as client:
            response = await client.post(endpoint, headers=headers, content=content)
            response.raise_for_status()

    async def get(self, path: str) -> bytes:
        endpoint = f"{self._url}/storage/v1/object/{self._bucket}/{path}"
        headers = {"Authorization": f"Bearer {self._key}", "apikey": self._key}
        async with httpx.AsyncClient(timeout=IMAGE_FETCH_TIMEOUT_SECONDS) as client:
            response = await client.get(endpoint, headers=headers)
            response.raise_for_status()
            return response.content

    async def delete(self, path: str) -> None:
        """Remove one stored object. Purge path only (P3-SC5)."""
        endpoint = f"{self._url}/storage/v1/object/{self._bucket}/{path}"
        headers = {"Authorization": f"Bearer {self._key}", "apikey": self._key}
        async with httpx.AsyncClient(timeout=IMAGE_FETCH_TIMEOUT_SECONDS) as client:
            response = await client.delete(endpoint, headers=headers)
            if response.status_code != 404:
                response.raise_for_status()
