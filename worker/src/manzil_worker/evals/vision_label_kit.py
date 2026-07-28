"""Local human-labeling kit for the P3-7 image-classifier benchmark.

The kit is deliberately generated from private, normalized Property images and
lives under the gitignored ``tests/fixtures/vision_labels`` directory.  It is
not a production data path and never calls an LLM.
"""

from __future__ import annotations

import asyncio
import csv
import html
import json
import shutil
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from manzil_shared.config import IMAGE_PERCEPTUAL_HASH_DISTANCE

from manzil_worker.enrich.images import (
    DiscoveredImage,
    ImageError,
    difference_hash,
    discover_images,
    normalize_image,
)
from manzil_worker.fetching.corpus import CORPUS_DIR

VISION_LABELS_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "vision_labels"
LABEL_COLUMNS = (
    "image_id",
    "property_id",
    "property_name",
    "content_hash",
    "source_url",
    "source_page_order",
    "kind",
    "kitchen_visible",
    "kitchen_assessable",
    "flooring_visible",
    "bathroom_visible",
    "content_kind",
    "duplicate_group",
    "notes",
)


class LabelKitError(ValueError):
    """The local kit cannot be safely generated."""


@dataclass(frozen=True)
class VisionLabelImage:
    """One current, normalized Property image selected for human labeling."""

    image_id: str
    property_id: str
    property_name: str
    content_hash: str
    storage_path: str
    source_url: str | None = None
    source_page_order: int | None = None
    kind: str = "listing_photo"


@dataclass(frozen=True)
class LabelKitResult:
    """The local files written for one labeling session."""

    out_dir: Path
    image_count: int
    property_count: int
    contact_sheet: Path
    labels_csv: Path
    manifest: Path


@dataclass(frozen=True)
class DuplicateSuggestionResult:
    """Human-review artifacts for deterministic near-duplicate candidates."""

    cluster_count: int
    image_count: int
    review_sheet: Path
    suggestions_csv: Path


FetchImageBytes = Callable[[str], Awaitable[bytes]]


@dataclass(frozen=True)
class CorpusImageCandidate:
    """An image discovered from one saved local corpus page."""

    property_key: str
    property_name: str
    source_key: str
    source_url: str
    image: DiscoveredImage


@dataclass(frozen=True)
class CorpusImageSet:
    """Normalized local copies ready to feed into ``write_label_kit``."""

    images: tuple[VisionLabelImage, ...]
    contents: dict[str, bytes]


class ImageQueryConnection(Protocol):
    async def fetch(self, query: str, *args: Any) -> Sequence[Any]: ...


def _safe_asset_name(index: int, content_hash: str) -> str:
    short_hash = "".join(char for char in content_hash.lower() if char in "0123456789abcdef")[:12]
    if not short_hash:
        short_hash = f"image{index:04d}"
    return f"{index:04d}-{short_hash}.webp"


def _hamming_distance(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()


def _duplicate_clusters(manifest: dict[str, Any], out_dir: Path) -> list[list[dict[str, Any]]]:
    records = manifest.get("images")
    if not isinstance(records, list):
        raise LabelKitError("label-kit manifest has no image list")
    by_property: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise LabelKitError("label-kit manifest contains an invalid image record")
        property_id = record.get("property_id")
        asset_file = record.get("asset_file")
        if not isinstance(property_id, str) or not isinstance(asset_file, str):
            raise LabelKitError("label-kit manifest image record lacks property_id or asset_file")
        asset = out_dir / asset_file
        if not asset.is_file():
            raise LabelKitError(f"label-kit asset is missing: {asset_file}")
        record = {**record, "perceptual_hash": difference_hash(asset.read_bytes())}
        by_property.setdefault(property_id, []).append(record)

    clusters: list[list[dict[str, Any]]] = []
    for property_records in by_property.values():
        parents = list(range(len(property_records)))

        def find(index: int, parents: list[int] = parents) -> int:
            while parents[index] != index:
                parents[index] = parents[parents[index]]
                index = parents[index]
            return index

        def join(left: int, right: int, parents: list[int] = parents) -> None:
            left, right = find(left), find(right)
            if left != right:
                parents[right] = left

        for left, record in enumerate(property_records):
            for right in range(left + 1, len(property_records)):
                if (
                    _hamming_distance(
                        record["perceptual_hash"], property_records[right]["perceptual_hash"]
                    )
                    <= IMAGE_PERCEPTUAL_HASH_DISTANCE
                ):
                    join(left, right)
        grouped: dict[int, list[dict[str, Any]]] = {}
        for index, record in enumerate(property_records):
            grouped.setdefault(find(index), []).append(record)
        clusters.extend(group for group in grouped.values() if len(group) > 1)
    return clusters


def _duplicate_review_sheet(clusters: Sequence[Sequence[dict[str, Any]]]) -> str:
    sections = []
    for index, cluster in enumerate(clusters, 1):
        group_id = f"D{index:03d}"
        property_name = html.escape(str(cluster[0]["property_name"]))
        cards = []
        for record in cluster:
            asset_file = html.escape(str(record["asset_file"]), quote=True)
            image_id = html.escape(str(record["image_id"]), quote=True)
            cards.append(
                '<article class="card">'
                f'<img src="{asset_file}" alt="{image_id}">'
                f"<strong>{image_id}</strong>"
                "</article>"
            )
        sections.append(
            f"<section><h2>{group_id} · {property_name}</h2>"
            f'<div class="grid">{"".join(cards)}</div></section>'
        )
    return (
        """<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">
<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>Duplicate-group review</title><style>
body { margin: 24px; font: 15px/1.4 system-ui, sans-serif; background: #f4f1ec; color: #292622; }
section { margin: 28px 0; } h1, h2 { margin-bottom: 8px; }
.grid { display: flex; flex-wrap: wrap; gap: 12px; }
.card { width: 230px; overflow: hidden; padding-bottom: 8px; border: 1px solid #d6cec2;
  border-radius: 8px; background: #fffdfa; }
.card img { display: block; width: 100%; aspect-ratio: 4 / 3; object-fit: contain;
  background: #e8e5df; }
.card strong { display: block; padding: 8px 8px 0; overflow-wrap: anywhere; font-size: 11px; }
</style></head><body><h1>Suggested near-duplicate groups</h1>
<p>These are suggestions from the selector's dHash <=5 rule, not labels. For
each group that truly shows the same or near-identical view, copy its D-number
into <code>duplicate_group</code> in <code>labels.csv</code>. Split or leave
blank any suggestion that is visually meaningfully different.</p>"""
        + "".join(sections)
        + "</body></html>\n"
    )


def write_duplicate_suggestions(
    out_dir: Path = VISION_LABELS_DIR,
) -> DuplicateSuggestionResult:
    """Write human-reviewable dHash suggestions without changing ground truth."""
    manifest_path = out_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise LabelKitError(f"cannot read label-kit manifest: {error}") from error
    if not isinstance(manifest, dict):
        raise LabelKitError("label-kit manifest must be an object")
    clusters = _duplicate_clusters(manifest, out_dir)
    review_sheet = out_dir / "duplicate-review.html"
    review_sheet.write_text(_duplicate_review_sheet(clusters))
    suggestions_csv = out_dir / "duplicate-suggestions.csv"
    with suggestions_csv.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("suggested_group", "image_id", "property_name", "content_hash"),
        )
        writer.writeheader()
        for index, cluster in enumerate(clusters, 1):
            for record in cluster:
                writer.writerow(
                    {
                        "suggested_group": f"D{index:03d}",
                        "image_id": record["image_id"],
                        "property_name": record["property_name"],
                        "content_hash": record["content_hash"],
                    }
                )
    return DuplicateSuggestionResult(
        cluster_count=len(clusters),
        image_count=sum(len(cluster) for cluster in clusters),
        review_sheet=review_sheet,
        suggestions_csv=suggestions_csv,
    )


def _property_name(key: str) -> str:
    return key.replace("-", " ").title()


def _round_robin_candidates(
    candidates_by_source: dict[str, list[CorpusImageCandidate]],
) -> list[CorpusImageCandidate]:
    """Keep corpus sampling source-balanced, like IMAGE_FETCH's future fan-out."""
    ordered_sources = sorted(candidates_by_source)
    positions = {source: 0 for source in ordered_sources}
    result: list[CorpusImageCandidate] = []
    while True:
        added = False
        for source in ordered_sources:
            position = positions[source]
            candidates = candidates_by_source[source]
            if position >= len(candidates):
                continue
            result.append(candidates[position])
            positions[source] += 1
            added = True
        if not added:
            return result


def discover_corpus_candidates(
    corpus_dir: Path = CORPUS_DIR,
) -> dict[str, list[CorpusImageCandidate]]:
    """Read saved corpus HTML only; no network access occurs in this step."""
    grouped: dict[str, list[CorpusImageCandidate]] = {}
    if not corpus_dir.is_dir():
        return grouped
    for page_dir in sorted(corpus_dir.iterdir()):
        raw_path = page_dir / "raw.html"
        meta_path = page_dir / "meta.json"
        if not raw_path.is_file() or not meta_path.is_file() or "--" not in page_dir.name:
            continue
        try:
            source_url = str(json.loads(meta_path.read_text())["url"])
        except (KeyError, TypeError, json.JSONDecodeError, OSError):
            continue
        _, property_key = page_dir.name.split("--", 1)
        try:
            discovered = discover_images(raw_path.read_text(errors="replace"), source_url)
        except (OSError, ValueError):
            continue
        candidates = grouped.setdefault(property_key, [])
        candidates.extend(
            CorpusImageCandidate(
                property_key=property_key,
                property_name=_property_name(property_key),
                source_key=page_dir.name,
                source_url=source_url,
                image=image,
            )
            for image in discovered
        )
    return grouped


async def collect_corpus_images(
    fetch_image: FetchImageBytes,
    *,
    corpus_dir: Path = CORPUS_DIR,
    max_properties: int = 10,
    max_images_per_property: int = 30,
) -> CorpusImageSet:
    """Download a source-balanced sample from local corpus pages and normalize it.

    The raw pages are already local. Downloaded bytes are immediately reduced
    to the same production WebP profile and copied only to the gitignored kit.
    """
    if max_properties < 1 or max_images_per_property < 1:
        raise LabelKitError("max_properties and max_images_per_property must be positive")
    discovered = discover_corpus_candidates(corpus_dir)
    ordered_properties = sorted(discovered, key=lambda key: (-len(discovered[key]), key))
    selected: list[VisionLabelImage] = []
    contents: dict[str, bytes] = {}
    minimum_images = min(20, max_images_per_property)
    for property_key in ordered_properties:
        if len({image.property_id for image in selected}) >= max_properties:
            break
        by_source: dict[str, list[CorpusImageCandidate]] = {}
        for candidate in discovered[property_key]:
            by_source.setdefault(candidate.source_key, []).append(candidate)
        seen_hashes: set[str] = set()
        property_images: list[VisionLabelImage] = []
        property_contents: dict[str, bytes] = {}
        for candidate in _round_robin_candidates(by_source):
            if len(seen_hashes) >= max_images_per_property:
                break
            try:
                normalized = normalize_image(await fetch_image(candidate.image.url))
            except (ImageError, OSError):
                continue
            if normalized.content_hash in seen_hashes:
                continue
            seen_hashes.add(normalized.content_hash)
            storage_path = f"corpus/{property_key}/{normalized.content_hash}.webp"
            property_contents[storage_path] = normalized.webp
            property_images.append(
                VisionLabelImage(
                    image_id=f"corpus:{property_key}:{normalized.content_hash[:12]}",
                    property_id=f"corpus:{property_key}",
                    property_name=candidate.property_name,
                    content_hash=normalized.content_hash,
                    storage_path=storage_path,
                    source_url=candidate.source_url,
                    source_page_order=candidate.image.page_order,
                )
            )
        if len(property_images) < minimum_images:
            continue
        selected.extend(property_images)
        contents.update(property_contents)
    if not selected:
        raise LabelKitError("no corpus gallery images could be downloaded and normalized")
    return CorpusImageSet(images=tuple(selected), contents=contents)


def _kit_readme() -> str:
    return """# VISION classifier labels

Open `contact-sheet.html` in a browser and enter one row per image in
`labels.csv`. Keep the image ID and provenance columns unchanged.

Use `yes` or `no` for the four visibility columns:

- `kitchen_visible`: any recognisable kitchen is visible.
- `kitchen_assessable`: cabinetry, counters, and major appliances are visible
  enough to judge kitchen quality. This must be `no` when `kitchen_visible` is
  `no`.
- `flooring_visible` / `bathroom_visible`: the relevant area is visible enough
  to assess.

Set `content_kind` to exactly one of `listing_photo`, `floor_plan_diagram`, or
`irrelevant`. Use the same non-empty `duplicate_group` value for near-identical
images of the same scene; leave it blank when an image has no near duplicate.
Use `notes` only for ambiguity worth preserving for the benchmark.

These files are local evaluation data: do not commit them.
"""


def _contact_sheet(images: Sequence[VisionLabelImage], asset_names: Sequence[str]) -> str:
    cards = []
    for image, asset_name in zip(images, asset_names, strict=True):
        escaped_asset = html.escape(asset_name, quote=True)
        escaped_id = html.escape(image.image_id, quote=True)
        page_order = image.source_page_order if image.source_page_order is not None else "—"
        cards.append(
            '<article class="card">'
            f'<img src="images/{escaped_asset}" alt="{escaped_id}">'
            '<div class="meta">'
            f"<strong>{html.escape(image.image_id)}</strong><br>"
            f"{html.escape(image.property_name)}<br>"
            f"<small>{html.escape(image.kind)} · page {page_order}</small>"
            "</div></article>"
        )
    return (
        """<!doctype html>
<html lang=\"en\"><head>
<meta charset=\"utf-8\">
<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>VISION classifier labeling kit</title>
<style>
body { margin: 24px; font: 15px/1.4 system-ui, sans-serif; background: #f4f1ec; color: #292622; }
h1 { margin: 0 0 6px; } p { max-width: 72ch; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 14px; }
.card { overflow: hidden; border: 1px solid #d6cec2; border-radius: 8px; background: #fffdfa; }
.card img { display: block; width: 100%; aspect-ratio: 4 / 3; object-fit: contain;
  background: #e8e5df; }
.meta { padding: 9px 10px 11px; } small { color: #655e56; }
</style></head><body>
<h1>VISION classifier labeling kit</h1>
<p>Use each image ID in <code>labels.csv</code>. Label what is visible in the
image, not what you infer about the Property.</p>
<section class=\"grid\">"""
        + "".join(cards)
        + "</section></body></html>\n"
    )


async def collect_current_images(
    conn: ImageQueryConnection,
    *,
    property_ids: Sequence[str] = (),
    max_properties: int = 10,
    max_images_per_property: int = 30,
) -> list[VisionLabelImage]:
    """Read a deterministic local benchmark sample without mutating the database."""
    if max_properties < 1 or max_images_per_property < 1:
        raise LabelKitError("max_properties and max_images_per_property must be positive")

    if property_ids:
        property_rows = await conn.fetch(
            """
            select p.id, p.name
            from unnest($1::uuid[]) with ordinality as requested(id, position)
            join properties p on p.id = requested.id
            where exists (
                select 1 from property_images pi
                where pi.property_id = p.id and pi.is_current and pi.storage_path <> ''
            )
            order by requested.position
            """,
            list(property_ids),
        )
    else:
        property_rows = await conn.fetch(
            """
            select p.id, p.name
            from properties p
            join property_images pi on pi.property_id = p.id
            where pi.is_current and pi.storage_path <> ''
            group by p.id, p.name
            order by max(pi.created_at) desc, p.id
            limit $1
            """,
            max_properties,
        )

    images: list[VisionLabelImage] = []
    for property_row in property_rows:
        rows = await conn.fetch(
            """
            select id, property_id, content_hash, storage_path, source_url,
                   source_page_order, kind
            from property_images
            where property_id = $1 and is_current and storage_path <> ''
            order by source_page_order nulls last, created_at, id
            limit $2
            """,
            property_row["id"],
            max_images_per_property,
        )
        for row in rows:
            images.append(
                VisionLabelImage(
                    image_id=str(row["id"]),
                    property_id=str(row["property_id"]),
                    property_name=str(property_row["name"]),
                    content_hash=str(row["content_hash"]),
                    storage_path=str(row["storage_path"]),
                    source_url=str(row["source_url"]) if row["source_url"] else None,
                    source_page_order=row["source_page_order"],
                    kind=str(row["kind"]),
                )
            )
    return images


async def write_label_kit(
    images: Sequence[VisionLabelImage],
    fetch_image: FetchImageBytes,
    *,
    out_dir: Path = VISION_LABELS_DIR,
    force: bool = False,
) -> LabelKitResult:
    """Copy selected private images and write blank human-labeling artifacts."""
    if not images:
        raise LabelKitError("no current Property images were found")
    if out_dir.exists() and any(out_dir.iterdir()):
        if not force:
            raise LabelKitError(
                f"{out_dir} already contains a label kit; pass --force to replace it"
            )
        shutil.rmtree(out_dir)
    images_dir = out_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    asset_names = [
        _safe_asset_name(index, image.content_hash) for index, image in enumerate(images, 1)
    ]
    contents = await asyncio.gather(*(fetch_image(image.storage_path) for image in images))
    for asset_name, content in zip(asset_names, contents, strict=True):
        if not content:
            raise LabelKitError(f"Storage returned an empty image for {asset_name}")
        (images_dir / asset_name).write_bytes(content)

    labels_path = out_dir / "labels.csv"
    with labels_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LABEL_COLUMNS)
        writer.writeheader()
        for image in images:
            writer.writerow(
                {
                    "image_id": image.image_id,
                    "property_id": image.property_id,
                    "property_name": image.property_name,
                    "content_hash": image.content_hash,
                    "source_url": image.source_url or "",
                    "source_page_order": (
                        image.source_page_order if image.source_page_order is not None else ""
                    ),
                    "kind": image.kind,
                    "kitchen_visible": "",
                    "kitchen_assessable": "",
                    "flooring_visible": "",
                    "bathroom_visible": "",
                    "content_kind": "",
                    "duplicate_group": "",
                    "notes": "",
                }
            )

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "image_count": len(images),
                "property_count": len({image.property_id for image in images}),
                "images": [
                    {**asdict(image), "asset_file": f"images/{asset_name}"}
                    for image, asset_name in zip(images, asset_names, strict=True)
                ],
            },
            indent=2,
        )
        + "\n"
    )
    contact_sheet = out_dir / "contact-sheet.html"
    contact_sheet.write_text(_contact_sheet(images, asset_names))
    (out_dir / "README.md").write_text(_kit_readme())
    return LabelKitResult(
        out_dir=out_dir,
        image_count=len(images),
        property_count=len({image.property_id for image in images}),
        contact_sheet=contact_sheet,
        labels_csv=labels_path,
        manifest=manifest_path,
    )
