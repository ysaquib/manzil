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
from urllib.parse import urljoin

import httpx
from lxml import etree, html
from manzil_shared.config import (
    FETCH_MAX_REDIRECTS,
    IMAGE_FETCH_TIMEOUT_SECONDS,
    IMAGE_MAX_DIM,
    IMAGE_MAX_DOWNLOAD_BYTES,
    IMAGE_MAX_PIXELS,
    IMAGE_WEBP_QUALITY,
    MAX_IMAGES,
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


class ImageObjectStore(Protocol):
    async def put(self, path: str, content: bytes) -> None: ...


DownloadImage = Callable[[str], Awaitable[bytes]]


def _absolute_http_url(value: str | None, base_url: str) -> str | None:
    if not value or value.startswith("data:"):
        return None
    url = urljoin(base_url, value.strip())
    if not url.startswith(("http://", "https://")):
        return None
    return url


def _srcset_urls(value: str | None) -> Iterable[str]:
    if not value:
        return ()
    candidates = [
        candidate.strip().split()[0]
        for candidate in value.split(",")
        if candidate.strip()
    ]
    # srcset is conventionally ordered from smaller to larger. Keep the best
    # variant instead of spending the Property cap on multiple resolutions of
    # the same photo.
    return candidates[-1:]


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


def discover_image_urls(document: str, base_url: str, *, limit: int = MAX_IMAGES * 4) -> list[str]:
    """Return de-duplicated listing image candidates in page order.

    The wider discovery cap leaves room for download failures and byte-level
    duplicates; IMAGE_FETCH applies the final ``MAX_IMAGES`` cap after hashing.
    """
    try:
        root = html.fromstring(document, base_url=base_url)
    except (ValueError, etree.ParserError):
        return []

    candidates: list[str] = []
    candidates.extend(root.xpath("//meta[@property='og:image']/@content"))
    candidates.extend(root.xpath("//meta[@name='twitter:image']/@content"))
    candidates.extend(root.xpath("//link[@rel='image_src']/@href"))
    for node in root.xpath("//img | //source"):
        candidates.extend(
            value
            for value in (
                node.get("src"),
                node.get("data-src"),
                node.get("data-lazy-src"),
            )
            if value
        )
        candidates.extend(_srcset_urls(node.get("srcset") or node.get("data-srcset")))
    for raw in root.xpath("//script[@type='application/ld+json']/text()"):
        try:
            candidates.extend(_json_image_urls(json.loads(raw)))
        except (json.JSONDecodeError, TypeError):
            continue

    seen: set[str] = set()
    output: list[str] = []
    for candidate in candidates:
        url = _absolute_http_url(candidate, base_url)
        if url is None or url in seen:
            continue
        seen.add(url)
        output.append(url)
        if len(output) >= limit:
            break
    return output


def normalize_image(data: bytes) -> NormalizedImage:
    """Decode, orient, resize, and encode one image as deterministic-ish WebP."""
    if not data or len(data) > IMAGE_MAX_DOWNLOAD_BYTES:
        raise ImageError("image is empty or exceeds IMAGE_MAX_DOWNLOAD_BYTES")
    try:
        with Image.open(io.BytesIO(data)) as opened:
            if opened.width * opened.height > IMAGE_MAX_PIXELS:
                raise ImageError("image exceeds IMAGE_MAX_PIXELS")
            image = ImageOps.exif_transpose(opened)
            image.thumbnail((IMAGE_MAX_DIM, IMAGE_MAX_DIM), Image.Resampling.LANCZOS)
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGBA" if "transparency" in image.info else "RGB")
            output = io.BytesIO()
            image.save(output, format="WEBP", quality=IMAGE_WEBP_QUALITY, method=6)
            webp = output.getvalue()
            return NormalizedImage(
                content_hash=hashlib.sha256(webp).hexdigest(),
                webp=webp,
                width=image.width,
                height=image.height,
            )
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as error:
        raise ImageError(f"invalid image: {error}") from error


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
