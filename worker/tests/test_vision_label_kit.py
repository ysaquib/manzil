"""P3-7 classifier human-label kit stays local, explicit, and reproducible."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest
from manzil_worker.evals.vision_label_kit import (
    LABEL_COLUMNS,
    LabelKitError,
    VisionLabelImage,
    collect_corpus_images,
    write_duplicate_suggestions,
    write_label_kit,
)
from PIL import Image


async def _image_bytes(path: str) -> bytes:
    return f"webp:{path}".encode()


def _png(color: tuple[int, int, int]) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (32, 24), color).save(output, format="PNG")
    return output.getvalue()


@pytest.mark.asyncio
async def test_writes_contact_sheet_blank_labels_and_private_image_copies(tmp_path) -> None:  # type: ignore[no-untyped-def]
    images = [
        VisionLabelImage(
            image_id="image-1",
            property_id="property-1",
            property_name="Maple Court",
            content_hash="a" * 64,
            storage_path="properties/property-1/a.webp",
            source_page_order=2,
        ),
        VisionLabelImage(
            image_id="image-2",
            property_id="property-2",
            property_name="Oak House",
            content_hash="b" * 64,
            storage_path="properties/property-2/b.webp",
            kind="floor_plan_diagram",
        ),
    ]

    result = await write_label_kit(images, _image_bytes, out_dir=tmp_path)

    assert result.image_count == 2
    assert result.property_count == 2
    assert result.contact_sheet.is_file()
    assert "image-1" in result.contact_sheet.read_text()
    with result.labels_csv.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert tuple(rows[0]) == LABEL_COLUMNS
    assert rows[0]["kitchen_visible"] == ""
    assert rows[1]["content_kind"] == ""
    manifest = json.loads(result.manifest.read_text())
    assert manifest["images"][0]["asset_file"] == "images/0001-aaaaaaaaaaaa.webp"
    second_asset = tmp_path / manifest["images"][1]["asset_file"]
    assert second_asset.read_bytes() == b"webp:properties/property-2/b.webp"


@pytest.mark.asyncio
async def test_refuses_to_replace_an_existing_label_kit_without_force(tmp_path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "existing.txt").write_text("do not overwrite")
    image = VisionLabelImage(
        image_id="image-1",
        property_id="property-1",
        property_name="Maple Court",
        content_hash="a" * 64,
        storage_path="properties/property-1/a.webp",
    )

    with pytest.raises(LabelKitError, match="pass --force"):
        await write_label_kit([image], _image_bytes, out_dir=tmp_path)


@pytest.mark.asyncio
async def test_collects_source_balanced_normalized_images_from_saved_corpus(tmp_path) -> None:  # type: ignore[no-untyped-def]
    for source, image_url in (
        ("one", "https://example.com/one.png"),
        ("two", "https://example.com/two.png"),
    ):
        page = tmp_path / f"{source}.test--maple-court"
        page.mkdir()
        (page / "meta.json").write_text(json.dumps({"url": f"https://{source}.test/listing"}))
        (page / "raw.html").write_text(f'<img src="{image_url}">')

    async def fetch(url: str) -> bytes:
        return _png((220, 10, 10) if "one" in url else (10, 10, 220))

    result = await collect_corpus_images(
        fetch, corpus_dir=Path(tmp_path), max_images_per_property=2
    )

    assert len(result.images) == 2
    assert all(image.property_id == "corpus:maple-court" for image in result.images)
    assert all(image.content_hash for image in result.images)
    assert all(path.endswith(".webp") for path in result.contents)


@pytest.mark.asyncio
async def test_replaces_an_underfilled_property_with_the_next_usable_one(tmp_path) -> None:  # type: ignore[no-untyped-def]
    for slug, urls in {
        "bad": ("same.png", "same.png", "same.png"),
        "good": ("red.png", "blue.png"),
    }.items():
        page = tmp_path / f"source.test--{slug}"
        page.mkdir()
        (page / "meta.json").write_text(json.dumps({"url": "https://source.test/listing"}))
        (page / "raw.html").write_text("".join(f'<img src="{url}">' for url in urls))

    async def fetch(url: str) -> bytes:
        return _png((220, 10, 10) if "red" in url else (10, 10, 220))

    result = await collect_corpus_images(
        fetch, corpus_dir=Path(tmp_path), max_properties=1, max_images_per_property=2
    )

    assert {image.property_id for image in result.images} == {"corpus:good"}


@pytest.mark.asyncio
async def test_duplicate_suggestions_keep_human_labels_unchanged(tmp_path) -> None:  # type: ignore[no-untyped-def]
    images = [
        VisionLabelImage(
            image_id="image-1",
            property_id="property-1",
            property_name="Maple Court",
            content_hash="a" * 64,
            storage_path="properties/property-1/a.webp",
        ),
        VisionLabelImage(
            image_id="image-2",
            property_id="property-1",
            property_name="Maple Court",
            content_hash="b" * 64,
            storage_path="properties/property-1/b.webp",
        ),
    ]

    async def same_image(_: str) -> bytes:
        return _png((220, 10, 10))

    await write_label_kit(images, same_image, out_dir=tmp_path)
    result = write_duplicate_suggestions(tmp_path)

    assert result.cluster_count == 1
    assert result.image_count == 2
    assert "D001" in result.review_sheet.read_text()
    with result.suggestions_csv.open(newline="") as handle:
        suggestions = list(csv.DictReader(handle))
    assert {row["suggested_group"] for row in suggestions} == {"D001"}
    with (tmp_path / "labels.csv").open(newline="") as handle:
        labels = list(csv.DictReader(handle))
    assert all(not row["duplicate_group"] for row in labels)
