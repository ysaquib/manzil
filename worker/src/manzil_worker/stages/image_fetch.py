"""IMAGE_FETCH (P3-7a): normalize/store listing photos and hash-gate VISION."""

from __future__ import annotations

import structlog
from manzil_shared.config import (
    DIAGRAM_NORMALIZATION_PROFILE,
    MAX_FLOOR_PLAN_DIAGRAMS_PER_PLAN,
    MAX_FLOOR_PLAN_DIAGRAMS_PER_PROPERTY,
    MAX_STORED_IMAGES,
)
from manzil_shared.errors import PrivateAddressRefused, StageRetryable

from manzil_worker.enrich.diagram_signals import looks_like_diagram
from manzil_worker.enrich.images import (
    ImageError,
    NormalizedImage,
    difference_hash,
    download_image,
    normalize_diagram,
    normalize_image,
)
from manzil_worker.stages.base import StageCtx
from manzil_worker.state import PropertyImageIn, RunState, StageWarning

log = structlog.get_logger()

# The default `PropertyImageIn.normalization_profile`, named here so the two
# profiles sit side by side at the point of choice.
PHOTO_NORMALIZATION_PROFILE = "webp-1024-q82-v1"


def _field(candidate: object, name: str) -> object:
    """Read one field from a model or the equivalent mapping."""
    if hasattr(candidate, name):
        return getattr(candidate, name)
    if isinstance(candidate, dict):
        return candidate.get(name)
    return None


def _refs_from_accessible_text(context: dict, state: RunState) -> list[str]:
    """Link a diagram by the plan name inside its own alt/title/caption.

    Returns a single ref only when exactly one known Floor Plan name occurs in
    the text; anything else is ambiguous and stays unmatched. Very short plan
    names are ignored — a plan called "A" would match almost any sentence.
    """
    text = " ".join(
        str(context.get(field) or "") for field in ("alt", "title", "caption")
    ).casefold()
    if not text.strip():
        return []
    matches = [
        (len(name), plan.response_key)
        for plan in state.floor_plans
        if plan.response_key
        and plan.plan_name
        and len(name := plan.plan_name.strip()) >= 3
        and name.casefold() in text
    ]
    if not matches:
        return []
    # Most specific wins: `alt="Floor plan Studio Deluxe"` matches both "Studio"
    # and "Studio Deluxe", and the longer name is the one the page meant. Only a
    # tie between equally-specific names is genuinely ambiguous, and that stays
    # unmatched rather than guessing.
    longest = max(length for length, _ in matches)
    best = [key for length, key in matches if length == longest]
    return best if len(best) == 1 else []


def _skip_vision(state: RunState, why: str) -> None:
    if state.plan is not None:
        state.plan.skipped["VISION"] = why


def _apply_fetch_completion(
    state: RunState, *, incomplete: bool, photo_count: int
) -> bool:
    """Return whether the pass is strict-complete (no failed downloads)."""
    strict_complete = not incomplete
    cap_saturated = photo_count >= MAX_STORED_IMAGES
    state.image_fetch_strict_complete = strict_complete
    state.image_fetch_completed = strict_complete or cap_saturated
    return strict_complete


async def image_fetch_stage(state: RunState, ctx: StageCtx) -> RunState:
    state.replace_warnings("IMAGE_FETCH", [])
    # Round-robin Sources so one large gallery cannot exhaust the Property cap
    # before later Slate members contribute.
    candidates_by_source = []
    for source in state.sources:
        candidates = source.image_candidates or [
            {
                "url": url,
                "page_order": index,
                "discovery_mechanism": "legacy_url",
            }
            for index, url in enumerate(source.image_urls)
        ]
        candidates_by_source.append((source, list(candidates)))
    ordered: list[tuple[object, object]] = []
    index = 0
    # Admit enough candidates to fill both budgets. Capping this at the photo
    # limit alone would starve diagrams that appear late in a long gallery —
    # the exact eviction the separate diagram budget exists to prevent.
    while len(ordered) < MAX_STORED_IMAGES + MAX_FLOOR_PLAN_DIAGRAMS_PER_PROPERTY:
        added = False
        for source, candidates in candidates_by_source:
            if index < len(candidates):
                ordered.append((source, candidates[index]))
                added = True
        if not added:
            break
        index += 1
    if not ordered:
        state.property_images = []
        _apply_fetch_completion(state, incomplete=False, photo_count=0)
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
    prepared: list[tuple[object, object, NormalizedImage, bool]] = []
    seen: set[str] = set()
    incomplete = False
    failed_candidates = 0
    photo_count = 0
    diagram_count = 0
    for source, candidate in ordered:
        # Two budgets, deliberately independent (§P3-SC5): photo ordering must
        # not evict a diagram found late in a page, and diagrams must not
        # consume the photo cap that feeds the gallery and VISION.
        is_diagram = looks_like_diagram(candidate)
        if is_diagram:
            if diagram_count >= MAX_FLOOR_PLAN_DIAGRAMS_PER_PROPERTY:
                continue
        elif photo_count >= MAX_STORED_IMAGES:
            continue
        url = _field(candidate, "url")
        # A diagram's enclosing anchor usually points at the legible original;
        # fall back to the thumbnail when that download fails.
        full_size = _field(candidate, "full_size_url") if is_diagram else None
        normalize = normalize_diagram if is_diagram else normalize_image
        normalized = None
        for attempt in ([full_size] if full_size else []) + [url]:
            try:
                normalized = normalize(await fetch(attempt))
                break
            except PrivateAddressRefused:
                log.warning("image_refused", url=attempt, reason="ssrf_guard")
            except (ImageError, OSError) as error:
                log.warning("image_rejected", url=attempt, error=str(error))
        if normalized is None:
            incomplete = True
            failed_candidates += 1
            continue
        if normalized.content_hash in seen:
            continue
        seen.add(normalized.content_hash)
        prepared.append((source, candidate, normalized, is_diagram))
        if is_diagram:
            diagram_count += 1
        else:
            photo_count += 1

    # A known-partial set is stored; underfilled partials stay non-authoritative
    # for diagram/vision lifecycle, while a cap-saturated gallery still advances
    # the images freshness marker. Persistence keys photo retirement off
    # `image_fetch_completed`, so an underfilled partial write stays additive.
    cap_saturated = photo_count >= MAX_STORED_IMAGES
    if incomplete:
        if cap_saturated:
            message = (
                f"{failed_candidates} image candidate"
                f"{'s' if failed_candidates != 1 else ''} could not be downloaded; "
                f"the gallery is at capacity ({MAX_STORED_IMAGES} photos) so this "
                "pass is treated as complete."
            )
            detail: dict[str, object] = {
                "failed_candidates": failed_candidates,
                "prepared_images": len(prepared),
                "cap_saturated": True,
            }
        else:
            message = (
                f"{failed_candidates} image candidate"
                f"{'s' if failed_candidates != 1 else ''} could not be downloaded; "
                "usable images were kept and prior images were not retired."
            )
            detail = {
                "failed_candidates": failed_candidates,
                "prepared_images": len(prepared),
            }
        state.replace_warnings(
            "IMAGE_FETCH",
            [
                StageWarning(
                    stage="IMAGE_FETCH",
                    code="image_fetch_partial",
                    message=message,
                    detail=detail,
                )
            ],
        )
    if not prepared:
        state.property_images = []
        _apply_fetch_completion(state, incomplete=incomplete, photo_count=photo_count)
        _skip_vision(state, "no_usable_images")
        return state

    previous_hashes = await ctx.existing_image_hashes(state.property_id)
    images: list[PropertyImageIn] = []
    refs_per_plan: dict[str, int] = {}
    for source, candidate, normalized, is_diagram in prepared:
        url = _field(candidate, "url")
        context = (
            candidate.model_dump(exclude={"url", "page_order"})
            if hasattr(candidate, "model_dump")
            else {k: v for k, v in candidate.items() if k not in {"url", "page_order"}}
        )
        page_order = _field(candidate, "page_order")
        exact_refs: list[str] = []
        native_id = context.get("source_native_plan_id")
        label = context.get("nearby_plan_label")
        if native_id:
            exact_refs = [
                plan.response_key
                for plan in state.floor_plans
                if plan.response_key and plan.source_native_id == native_id
            ]
        elif context.get("containing_floor_plan_card") and label:
            normalized_label = str(label).strip().casefold()
            exact_refs = [
                plan.response_key
                for plan in state.floor_plans
                if plan.response_key
                and plan.plan_name
                and plan.plan_name.strip().casefold() == normalized_label
            ]
        elif is_diagram:
            # Real listing pages overwhelmingly name the plan in the diagram's
            # own alt text — "Floor plan Studio", "Savoy diagram" — rather than
            # in a sibling label or a data attribute. Workbook §7.2 permits "an
            # unambiguous nearby plan label", and the image's own accessible
            # name is the nearest label there is.
            #
            # Unambiguous is enforced literally: exactly one known plan name may
            # appear in the text. "Studio" against both "Studio" and "Studio
            # Deluxe" yields two matches and therefore no link, which is the
            # correct outcome — the diagram falls to the unmatched gallery.
            exact_refs = _refs_from_accessible_text(context, state)
        exact_refs = [ref for ref in exact_refs if ref is not None]
        # Per-plan diagram cap. Applied to the association, not the asset: a
        # diagram shared by several plans is stored once and may exhaust a
        # different plan's allowance than its neighbour.
        if is_diagram:
            allowed: list[str] = []
            for ref in exact_refs:
                if refs_per_plan.get(ref, 0) < MAX_FLOOR_PLAN_DIAGRAMS_PER_PLAN:
                    refs_per_plan[ref] = refs_per_plan.get(ref, 0) + 1
                    allowed.append(ref)
            exact_refs = allowed
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
                source_url_page=source.url,
                source_page_order=page_order,
                perceptual_hash=difference_hash(normalized.webp),
                discovery_context=context,
                exact_floor_plan_refs=exact_refs,
                kind="floor_plan_diagram" if is_diagram else "listing_photo",
                normalization_profile=(
                    DIAGRAM_NORMALIZATION_PROFILE if is_diagram else PHOTO_NORMALIZATION_PROFILE
                ),
            )
        )

    state.property_images = images
    strict_complete = _apply_fetch_completion(
        state, incomplete=incomplete, photo_count=photo_count
    )
    current_hashes = {image.content_hash for image in images}
    log.info(
        "images_prepared",
        property_id=str(state.property_id),
        count=len(images),
        complete=state.image_fetch_completed,
        strict_complete=strict_complete,
        changed=bool(current_hashes - previous_hashes),
    )
    return state
