"""IMAGE_FETCH (P3-7a): normalize/store listing photos and hash-gate VISION."""

from __future__ import annotations

import structlog
from manzil_shared.config import MAX_IMAGES
from manzil_shared.errors import PrivateAddressRefused, StageRetryable

from manzil_worker.enrich.images import (
    ImageError,
    NormalizedImage,
    download_image,
    normalize_image,
)
from manzil_worker.stages.base import StageCtx
from manzil_worker.state import PropertyImageIn, RunState

log = structlog.get_logger()


def _skip_vision(state: RunState, why: str) -> None:
    if state.plan is not None:
        state.plan.skipped["VISION"] = why


async def image_fetch_stage(state: RunState, ctx: StageCtx) -> RunState:
    urls = list(dict.fromkeys(url for source in state.sources for url in source.image_urls))
    if not urls:
        state.property_images = []
        state.image_fetch_completed = True
        _skip_vision(state, "no_images")
        return state
    if state.property_id is None:
        _skip_vision(state, "property_identity_unavailable")
        return state
    if ctx.image_store is None:
        _skip_vision(state, "image_storage_unconfigured")
        log.warning("image_fetch_skipped", reason="image_storage_unconfigured")
        return state

    fetch = ctx.download_image or download_image
    prepared: list[tuple[str, NormalizedImage]] = []
    seen: set[str] = set()
    incomplete = False
    for url in urls:
        if len(prepared) >= MAX_IMAGES:
            break
        try:
            normalized = normalize_image(await fetch(url))
        except PrivateAddressRefused:
            log.warning("image_refused", url=url, reason="ssrf_guard")
            incomplete = True
            continue
        except (ImageError, OSError) as error:
            log.warning("image_rejected", url=url, error=str(error))
            incomplete = True
            continue
        if normalized.content_hash in seen:
            continue
        seen.add(normalized.content_hash)
        prepared.append((url, normalized))

    # Never compare or replace a partial set: one transiently failed candidate
    # could otherwise look like a deletion and trigger spend/data loss.
    if incomplete and len(prepared) < MAX_IMAGES:
        state.property_images = []
        state.image_fetch_completed = False
        _skip_vision(state, "image_set_incomplete")
        return state

    previous_hashes = await ctx.existing_image_hashes(state.property_id)
    images: list[PropertyImageIn] = []
    for url, normalized in prepared:
        path = f"properties/{state.property_id}/{normalized.content_hash}.webp"
        if normalized.content_hash not in previous_hashes:
            try:
                await ctx.image_store.put(path, normalized.webp)
            except Exception as error:
                raise StageRetryable(f"image Storage upload failed: {error}") from error
        images.append(
            PropertyImageIn(
                source_url=url,
                storage_path=path,
                content_hash=normalized.content_hash,
                width=normalized.width,
                height=normalized.height,
                byte_size=len(normalized.webp),
            )
        )

    state.property_images = images
    state.image_fetch_completed = True
    current_hashes = {image.content_hash for image in images}
    if not current_hashes:
        _skip_vision(state, "no_usable_images")
    elif current_hashes == previous_hashes:
        _skip_vision(state, "images_unchanged")
    elif state.plan is not None and state.plan.skipped.get("VISION") == "images_unchanged":
        state.plan.skipped.pop("VISION")
    log.info(
        "images_prepared",
        property_id=str(state.property_id),
        count=len(images),
        changed=current_hashes != previous_hashes,
    )
    return state
