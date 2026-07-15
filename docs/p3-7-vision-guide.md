# P3-7 Images + VISION completion guide

Status: **P3-7a substrate implemented; P3-7b remains intentionally fail-closed.**

The repository can now discover listing images, download them through the
fetcher-layer SSRF guard, normalize them to content-addressed WebP objects,
persist their metadata, and prove that unchanged bytes cause no VISION call.
It must not produce `kitchen_quality` or `flooring_quality` ratings until Yusuf
approves the versioned reference set and its bench result.

## 1. What is implemented

- `FETCH` extracts ordered image candidates from Open Graph/Twitter metadata,
  `img`/`source` markup and JSON-LD, and persists the URLs on `SourceState` and
  `property_sources.image_urls`.
- `IMAGE_FETCH` runs after DEDUPE, so Storage paths use the canonical Property.
  It downloads at most the candidate budget, rejects private/non-http targets,
  non-images, oversized inputs and decompression bombs, applies EXIF orientation,
  resizes within 1024 px, encodes WebP, de-duplicates normalized bytes, and keeps
  at most `MAX_IMAGES` (currently 8).
- Objects use `properties/{property_id}/{sha256}.webp` in the private
  `property-images` bucket. `property_images` records source URL, normalized-byte
  hash, dimensions, byte size, kind and the future per-image assessment.
- `IMAGE_FETCH` compares the complete current normalized-hash set with the
  Property's persisted set. Equality writes `VISION: images_unchanged` into
  `plan.skipped`; the runner honors the skip before opening a cost tally or model
  call. A reused URL whose bytes changed therefore reruns VISION; a changed URL
  with identical normalized bytes does not.
- `call_vision` supports forced-schema OpenRouter calls, NFR6 Langfuse tracing,
  cost tallying, and record/replay. Recordings contain input hashes, never image
  bytes. There is deliberately no `vision.md` prompt yet.
- PLAN writes `VISION: missing_reference_set` while the reference gate is not
  complete. `stages/vision.py` has a second fail-closed guard.

Not implemented yet: anchored rating prompt, VISION response/aggregation,
assessment projection into Extractions, gallery UI, tier-2 screenshot persistence,
or the 30-day Storage cleanup tick.

## 2. Why IMAGE_FETCH is a separate boundary

PLAN runs before the page is fetched, so it cannot know whether an image at a
URL now has different bytes. `IMAGE_FETCH` is the deterministic P2 boundary that
learns those hashes. The manifest retains the ordered `VISION` entry and uses the
pinned `skipped` map to suppress it. This keeps the cursor stable across crashes:
IMAGE_FETCH output and the skip reason persist before the runner advances.

Current P3-7a sequence (P3-5/P3-6 are not in the runner yet):

```text
FETCH (discover URLs)
  → DEDUPE (canonical Property)
  → IMAGE_FETCH (download → normalize → hash → private Storage)
      ├─ same complete hash set → plan.skipped.VISION = images_unchanged
      ├─ no usable images       → plan.skipped.VISION = no_usable_images
      └─ changed hash set       → VISION remains eligible
  → VISION (skipped while the reference gate is closed)
  → VERIFY → SCORE
```

When P3-5/P3-6 add sibling sources, new manifests move IMAGE_FETCH/VISION to
the final DESIGN §10.1 position after per-source VERIFY and RECONCILE, so the
batch contains the settled slate's images. Existing manifests keep their own
recorded order and resume safely. At P3-7b rollout, confirm the placement against
the then-current runner; do not accidentally leave VISION ahead of an already
landed sibling fan-out.

## 3. Build and approve the reference set (human gate)

Create `worker/prompts/vision_refs/manifest.json` plus its WebP assets. A single
photo may anchor both criteria; its `ratings` object says which dimensions Yusuf
personally rated. The validator requires 3–4 examples for every value 1–5 of
both criteria and verifies every file hash.

Example (illustrative hashes only):

```json
{
  "version": 1,
  "prompt_version": 1,
  "status": "approved",
  "approved_by": "Yusuf",
  "approved_at": "2026-07-13",
  "references": [
    {
      "file": "kitchen-floor-01.webp",
      "sha256": "<sha256-of-exact-file>",
      "source_url": "https://source-listing.example/...",
      "ratings": {"kitchen_quality": 1, "flooring_quality": 2},
      "note": "Short reason this is a stable anchor."
    }
  ]
}
```

Selection checklist:

1. Select real listing photos Yusuf has rated, not generated stand-ins.
2. Cover meaningful variation within a level (lighting, angle, occupied/vacant,
   carpet/hard floor, cabinet/appliance styles) without letting photographic
   quality become the rating.
3. Crop only to remove irrelevant content; do not cosmetically enhance finishes.
4. Normalize reference assets with the same 1024 px/WebP policy as target images.
5. Record provenance and confirm the repository/storage location is acceptable
   for those third-party images before committing them.
6. Have Yusuf review the contact sheet and set `status: approved` only after all
   10 criterion/level cells have 3–4 examples.
7. Validate the asset alone with `load_reference_manifest()`. After §4.1 adds
   the matching prompt, run `vision_references_ready()`; a missing file, changed
   hash, invalid rating, incomplete coverage, non-approved status, absent prompt,
   or prompt-version mismatch must return false.

Changing any file, rating, or anchor note that affects interpretation is a
reviewed migration: increment reference `version` and prompt `version`, re-run
the bench, inspect diffs, then accept or roll back. Never edit an approved set in
place under the same version.

## 4. Implement P3-7b after approval

### 4.1 Prompt and response schema

Add `worker/src/manzil_worker/llm/prompts/vision.md` with matching front matter:

```text
---
id: vision
version: 1
cacheable_prefix_marker: <!-- PER-CALL -->
---
```

The stable prefix must define the two 1–5 scales, tell the model to compare only
against supplied anchors, allow `not_visible`, and prohibit inferring quality
from text, rent, neighborhood, staging, camera quality, or exterior appearance.
Reference images should be labeled `reference:<criterion>:<rating>`; target
images should be labeled `target:<content_hash>`.

Define a forced-schema result with one record per target image:

- `content_hash`
- `kind`: kitchen | flooring | mixed | irrelevant
- `kitchen_quality`: 1–5 or null
- `flooring_quality`: 1–5 or null
- `confidence`: high | medium | low | not_found
- a short visual rationale (not textual-listing evidence)

Reject unknown hashes, duplicates, ratings outside 1–5, and results for reference
images. Keep the model output in `property_images.vision_assessment`.

### 4.2 Aggregation and Extractions

Aggregate each criterion independently over relevant target images. The exact
tie/outlier rule must be deterministic and added to DESIGN §10.8 before enabling
the stage. Recommended bench candidate: confidence-weighted median, requiring at
least one medium-or-higher assessment; otherwise emit unknown. Do not silently
choose this rule—the first labeled bench should decide it.

Write the aggregate as an append-only global Extraction:

- criterion key `kitchen_quality` or `flooring_quality`
- integer value 1–5
- confidence derived by the approved deterministic rule
- `model` and prompt/reference versions
- contributing Storage paths as structured visual evidence
- a VISION-specific `resolution_rule`

Then let SCORE consume those effective values exactly like other catalog facts.
Do not route VISION through EXTRACT or give it tools.

### 4.3 Storage reads and projection

Extend the injected image store with a `get(path)` operation, load normalized
targets and approved local references, construct `VisionImage` blocks, and call
`ctx.call_vision`/the client seam once per Property batch. Never hand the model
remote image URLs. Keep the service-role key out of state, events and traces.

On success, project per-image assessments and the two aggregate Extractions in
the same terminal transaction as the DONE flip. A replay fixture must list image
hashes and structured output only.

### 4.4 Frontend gallery

Add the detail-drawer gallery only after rows exist. Read the private bucket with
short-lived signed URLs (or authenticated Storage requests), show the aggregate
rating first, and expose per-image assessment/rationale as provenance. Broken or
expired image URLs must not break the drawer. Respect RLS; client visibility is
UX, not the security boundary.

### 4.5 Screenshots and retention

Tier-2 already can capture a screenshot but P3-7a does not request/persist it.
When P3-11 supplies the scheduler tick:

1. request a compressed full-page WebP only for browser-tier fetches that need it;
2. store its path in `property_sources.screenshot_path` (separate from rating
   inputs—debug screenshots must not accidentally enter VISION);
3. delete screenshots older than 30 days;
4. delete content-addressed Property image objects only when no
   `property_images.storage_path` references them and the retention grace has
   elapsed.

## 5. Validation and rollout gates

Automated gates:

- discovery order, URL normalization, duplicate suppression and cap;
- SSRF redirect refusal, content-type/size/pixel/decode rejection;
- EXIF orientation, max dimension, WebP output and deterministic content hash;
- same URL/different bytes reruns; different URL/same bytes skips;
- two identical complete hash sets produce `images_unchanged`, zero calls and
  zero VISION cost;
- record→replay round trip with no image bytes in the fixture;
- crash after IMAGE_FETCH save resumes without uploading/spending twice;
- DB projection is idempotent and DEDUPE merge/split behavior remains correct.

Human/bench gates:

1. Choose at least five representative Properties outside the reference set,
   including weak/ambiguous imagery.
2. Yusuf rates both criteria blind before seeing model output.
3. Run the same normalized targets against prompt/reference v1 in record mode.
4. Require each aggregate within ±1 of Yusuf's rating; report exact agreement,
   within-one agreement, unknown rate, per-level confusion, cost and latency.
5. Review every >1 disagreement and any confident rating of an irrelevant image.
6. Adjust anchors/prompt only with a version bump and rerun the complete bench.
7. Enable live VISION only after the report is accepted and recorded in the
   DESIGN decision log.

Operational rollout:

```bash
uv sync --all-packages
supabase db reset
uv run --package manzil-worker pytest worker/tests
uv run ruff check .
```

Then run one local ingest with images, inspect the private bucket and
`property_images`, retry unchanged and confirm the job manifest says
`VISION: images_unchanged` with no Langfuse VISION generation. Finally change one
served image at the same URL and confirm the hash and VISION eligibility change.

## 6. Definition of done

P3-7 is complete only when all of these are true:

- the approved versioned reference set and matching prompt exist;
- the accepted bench meets the ±1 gate and its report/version are recorded;
- per-image assessments and aggregate Extractions persist with provenance;
- the authenticated gallery renders;
- unchanged second runs show zero VISION calls and zero VISION spend;
- changed bytes at a stable URL rerun VISION;
- screenshot and unreferenced-object retention cleanup is live;
- DESIGN/IMPLEMENTATION status changes from P3-7a partial to P3-7 complete.
