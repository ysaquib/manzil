# P3-7a2 / P3-7b — Kitchen-first VISION guide

P3-7a2 engineering and kitchen-quality scoring are live. Yusuf explicitly
overrode the external quality-benchmark gate on 2026-07-28: the approved
reference profile v1, VISION prompt v1, and `anthropic/claude-sonnet-5` are
released for scoring (cost-only pin, DESIGN v3.102). The external quality
benchmark remains owed and the current release is not described as
bench-validated. Flooring and bathroom are disabled.

## Pipeline and caching

New manifests preserve this order:

```text
… → IMAGE_FETCH → IMAGE_CLASSIFY → VISION → VERIFY → ENRICH → SCORE
```

Old manifests retain their recorded stage list and resume cursor. IMAGE_FETCH
retains up to 120 exact-normalized-hash-distinct candidate photos,
source-balanced, with Source/page order and DOM context. The visible gallery is
separately capped at 30 classified room/exterior photos; unclassified, `other`,
diagram, map, and unrelated assets consume no visible slot. A partial download
is additive and cannot retire prior images. A complete refresh marks missing
assets non-current.

IMAGE_CLASSIFY classifies up to 120 unstored ≤384 px WebP thumbnails in
deterministic batches of 30 through `call_vision` to
`openai/gpt-5.6-luna`. The canonical result is cached per
normalized image hash plus `model:prompt-<version>` under
`vision_assessment.classification`; it contains `primary_scene`, visibility,
framing, confidence, `irrelevant`, and `diagram`. An ONNX-shaped incumbent is
not a cache hit; it is rewritten and kept as `classification_onnx_legacy`.
The CLIP ONNX stack remains in tree but is not loaded, shadowed, or used as
fallback (DESIGN v3.102).

Quality selection uses those structured fields: high-confidence, assessable
kitchen, usable framing, not diagram/irrelevant; skip near-duplicates; cover
exact Floor Plan refs; take at most three. The anchored quality VISION call is
responsible for returning `not_visible` when none of the best available images
shows a rateable kitchen.

Quality caching keys the selected target/association digest, quality
model/prompt, and reference version independently from classification.

## Source-local image associations

Automatic association is allowed only from a Source-native plan ID, containing
Floor Plan card, or unambiguous nearby plan label. It never uses visual
similarity and never crosses Sources. Ordinary photos and diagrams share the
append-only `floor_plan_images` ledger. Partial refresh cannot append `unlink`.

## Reference profile

Keep third-party originals in the gitignored
`worker/prompts/vision_refs/originals/`. Commit only normalized anchors,
generated sheets, and `manifest.json`.

The manifest is criterion-specific:

```json
{
  "version": 1,
  "profiles": {
    "kitchen_quality": {
      "version": 1,
      "prompt_version": 1,
      "status": "approved",
      "quality_status": "approved",
      "quality_benchmark_status": "deferred_owner_override",
      "quality_model": "anthropic/claude-sonnet-5",
      "approved_by": "Yusuf",
      "approved_at": "YYYY-MM-DD",
      "anchors": [
        {
          "file": "normalized/kitchen-1-a.webp",
          "sha256": "...",
          "rating": 1,
          "source_url": "optional",
          "note": "Why this is a stable anchor"
        }
      ],
      "sheets": {
        "1": {
          "file": "kitchen_quality-rating-1.webp",
          "sha256": "...",
          "members": ["normalized/kitchen-1-a.webp"]
        }
      }
    }
  }
}
```

`status = approved` records that the anchors and sheets are approved.
`quality_status = approved` permits live kitchen VISION. The separate
`quality_benchmark_status = deferred_owner_override` records that the Owner
released scoring without accepting an external quality benchmark; it must not
be interpreted as benchmark evidence.

Use 3–5 anchors per level; the initial kitchen set uses all five current
anchors at every 1–5 level. Normalize targets with the production 1024 px WebP
profile. `build_reference_sheets()` produces five deterministic 1024×1024,
3-by-2 contain-fitted sheets: five examples plus one blank neutral cell. It does
not cover-crop or cosmetically change examples. `load_reference_manifest()`
checks every anchor hash, sheet hash, and exact membership order.

## Kitchen quality and aggregation

One quality call contains the five reference sheets and at most three full
targets. Each target result has original content hash, visibility, rating,
confidence, and a short visual rationale. Unknown/duplicate hashes, missing
targets, and ratings on `not_visible` results fail validation.

The aggregate is a confidence-weighted median: high=2, medium=1, low and
not-visible excluded; an exact half-weight tie chooses the lower rating. One
high assessment yields medium aggregate confidence. Two or more within one star
yield high if at least one is high. A two-star spread yields medium. A spread
greater than two emits no scored aggregate.

VISION writes a generalized Property-target Extraction with
`unit_scope_unspecified`, plus one exact Floor Plan Extraction for each reliably
associated represented plan. Rules are `vision_weighted_median_gallery` and
`vision_weighted_median_exact`. `extraction_images` links both candidate and
resolved Extractions to every contributing `property_images` row.

Exact values ignore the gallery policy and normally receive full Rubric
behavior; the low-confidence Gate exclusion below still applies. The Hunt's
`generalized_vision_policy` controls only generalized `vision:*` values:
`full_rubric` (default) affects points and Gates; `points_only` affects points
while Gates see unknown; `unknown` persists/displays but does not score. A
policy edit bumps `rubric_version` and enqueues a zero-LLM rescore.

VISION confidence is independent from the ordinary Extraction threshold.
`min_vision_confidence` defaults to `low`, so low-confidence image assessments
may remain visible and affect points. Low-confidence VISION never enters the
Gate-value map, exact or generalized. Medium/high generalized values still
follow `generalized_vision_policy`; Overrides are unaffected. Changing the
threshold bumps `rubric_version` and enqueues the same zero-LLM rescore.

## Local labeling and acceptance

The gitignored label kit belongs under
`worker/tests/fixtures/vision_labels/`. Build a contact sheet for 10 Properties
and roughly 200–300 real gallery photos. Human labels cover kitchen
presence/assessability, flooring visibility, bathroom presence,
irrelevant/diagram images, and near-duplicate groups.

The historical generative-classifier gate was:

- ≥95% precision among selected kitchen targets;
- ≥90% Property-level kitchen recall at three targets;
- zero high-confidence selections on labeled no-kitchen galleries;
- zero selected Floor Plan diagrams;
- <$0.005 classification cost per 30-image Property.

Kitchen-quality bench uses Properties outside the 25 anchors. Yusuf rates
targets before seeing model output. Every accepted aggregate must be within ±1.
Report exact and within-one agreement, unknown rate, confusion by level, cost,
latency, and every irrelevant/non-kitchen confident rating.

The 2026-07-28 sweep benchmarked Gemini 2.5 Flash Lite, Gemini 3.1 Flash Lite,
Gemini 3 Flash, and the prescribed Sonnet fallback. None passed exact 30-image
response completeness. That evidence and the old selector labels remain useful
historical inputs, but DESIGN v3.52 supersedes the Gemini runtime decision:
ONNX is now the exclusive classifier. The still-owed release evidence is a
representative-gallery review of the ONNX top-three target sets and the
external anchored-quality benchmark.

## Verification and rollout

Automated coverage must include normalization/thumbnail parity, sheet
determinism and hashes, ONNX artifact/cache/hash validation, quotas,
exact/generalized precedence, all three policies,
weighted-median edges, authoritative/partial refresh safety, RLS/same-Property
guards, record/replay, and zero calls on unchanged inputs.

```bash
uv sync --all-packages
supabase db reset
uv run --package manzil-shared pytest shared/tests
uv run --package manzil-worker pytest worker/tests
uv run --package manzil-api pytest api/tests
pnpm -C frontend test
pnpm -C frontend build
uv run ruff check .
```

The ONNX authority and kitchen-quality release are recorded Owner decisions.
Run the external quality report when time permits and append its actual results
to DESIGN §20; do not change the recorded benchmark status to passed unless the
acceptance criteria are met. Run one live ingest plus an unchanged retry. The
retry must show zero classifier and quality calls.
Do not activate flooring or bathroom without their own Catalog decision,
references, quality bench, quota activation, and Decision Log entry.
