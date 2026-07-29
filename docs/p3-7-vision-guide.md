# P3-7a2 / P3-7b — Kitchen-first VISION guide

P3-7a2 engineering and kitchen-quality scoring are live. Yusuf explicitly
overrode the external quality-benchmark gate on 2026-07-28: the approved
reference profile v1, VISION prompt v1, and `anthropic/claude-sonnet-4.6` are
released for scoring. The external quality benchmark remains owed and the
current release is not described as bench-validated. Flooring and bathroom are
disabled.

## Pipeline and caching

New manifests preserve this order:

```text
… → IMAGE_FETCH → IMAGE_CLASSIFY → VISION → VERIFY → ENRICH → SCORE
```

Old manifests retain their recorded stage list and resume cursor. IMAGE_FETCH
stores up to 30 exact-normalized-hash-distinct photos, source-balanced, with
Source/page order and DOM context. A partial download is additive and cannot
retire prior images. A complete refresh marks missing assets non-current.

IMAGE_CLASSIFY makes one structured call with up to 30 separately labeled,
unstored ≤384 px WebP thumbnails. Its result is cached per normalized image hash
plus classifier model/prompt version. It asks for every requested original hash
exactly once and no unknown hash, and it tolerates a small shortfall rather
than throwing the batch away (DESIGN §20, 2026-07-28 v3.22): at most
`IMAGE_CLASSIFY_ANOMALY_TOLERANCE = 2` unanswered hashes and at most two
surplus records (unknown hashes + repeats). Anything past either bound still
fails closed.

Tolerated anomalies are recorded, never smoothed over:

- **Unanswered** → `vision_assessment.classification.status = "missing"`.
- **Irreconcilable repeats** → `status = "disputed"`.
- **Surplus unknown hashes** → dropped.

Neither marker carries a `cache_key`, so the next run asks about the image
again, and neither has an `assessment`, so no quality target can select it.
Repeated records for one hash resolve by higher confidence; on a tie the
sharper reading of the same picture wins (`other` loses to any real scene,
`living` loses to a specific interior room) and everything else — kitchen vs
exterior, or a disagreement about `diagram`/`irrelevant` — is disputed.
Every anomaly becomes a `jobs.warnings` entry on the task card; a warning
never halts, parks, retries, or fails the run.

The Owner-selected shadow pin is `google/gemini-3-flash-preview` (DESIGN §20,
2026-07-28). Its live 30-image smoke returned 29/30 requested hashes, and every
other candidate also failed the strict completeness contract — which is what
the tolerance above exists to survive. The pin does not approve live kitchen
quality. `manzil bench-classifier` deliberately keeps the **strict** check: it
measures model behavior for selection, not the pipeline's operating contract.

Quality selection is deterministic: high-confidence assessable kitchens only;
no irrelevant images or diagrams; one representative per dHash cluster
(Hamming distance ≤5); exact Source-local Floor Plan evidence and distinct-plan
coverage first; then full-room framing and stable Source/page order; maximum
three kitchen targets. Quality caching keys the selected target/association
digest, quality model/prompt, and reference version independently from
classification.

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
      "quality_model": "anthropic/claude-sonnet-4.6",
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

Classifier gate:

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
response completeness. Yusuf selected Gemini 3 Flash Preview anyway; preserve
that decision and the strict fail-closed contract unless a later Decision Log
entry changes either.

## Verification and rollout

Automated coverage must include normalization/thumbnail parity, sheet
determinism and hashes, classifier hash validation, provider-limit chunking,
dHash clusters, quotas, exact/generalized precedence, all three policies,
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

Both model selection and kitchen-quality release are recorded Owner overrides.
Run the external quality report when time permits and append its actual results
to DESIGN §20; do not change the recorded benchmark status to passed unless the
acceptance criteria are met. Run one live ingest plus an unchanged retry. The
retry must show zero classifier and quality calls.
Do not activate flooring or bathroom without their own Catalog decision,
references, quality bench, quota activation, and Decision Log entry.
