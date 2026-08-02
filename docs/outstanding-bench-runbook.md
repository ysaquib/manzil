# Outstanding Benchmark Runbook

**Status:** operational inventory as of 2026-07-29  
**Authority:** `DESIGN.md` defines intent and acceptance commitments;
`IMPLEMENTATION.md` defines current mechanics. This document consolidates the
remaining benchmark work without changing either.

## 1. Purpose

This runbook answers four questions for every benchmark Manzil still owes:

1. What claim is the benchmark meant to support?
2. What human ground truth must be labeled?
3. What tooling exists today, and what must be built before the benchmark can
   produce valid evidence?
4. What commands and review steps complete the benchmark?

The outstanding work falls into five active benchmark obligations:

| ID | Benchmark | Current status | Human labeling status | Runnable today? |
|---|---|---|---|---|
| B1 | Canonical-ten scoped Extraction, Floor Plan association, and Gate regression | Owner-waived technical debt from P3-SC4; expanded by P3-SC6/SC7 | 10 legacy labels are gradeable, but none contain the required scoped or diagram truth; 11 additional skeletons are unfinished | Partly. Scoped claims are graded; diagram associations are only coverage-audited |
| B2 | Auxiliary EXTRACT blocks: fees, utilities, heating, contacts, and related schema growth | Broad EXTRACT/VERIFY regression reruns occurred, but the new auxiliary outputs remain ungraded | No authoritative auxiliary-block label contract is implemented | No. Label and grading support must be added |
| B3 | P3-6 RECONCILE semantic-equivalence model comparison | Owner-waived technical debt | No reconciliation-specific human dataset exists | No dedicated harness or CLI exists |
| B4 | IMAGE_CLASSIFY selection benchmark | Model selected by Owner override after every candidate failed strict response completeness | Kitchen/content-kind labels are complete: 294 images across 10 Properties | Yes, but strict runs abort on malformed response identity before reporting accuracy |
| B5 | External kitchen-quality VISION benchmark | Kitchen scoring released by Owner override; no accuracy claim | Holdout kitchen ratings have not been collected | No dedicated quality-bench harness or CLI exists |

Two future benches are conditional rather than current shipping debt:

- flooring-quality VISION;
- bathroom image routing/quality, if a bathroom Criterion is approved.

They remain disabled and must not be activated merely to complete this runbook.

## 2. Rules shared by every benchmark

### 2.1 Human labels are page or image truth

Never generate ground truth from a model response. Tooling may:

- scaffold a label;
- surface candidate evidence;
- produce contact sheets;
- validate shape and controlled vocabulary;
- identify missing coverage.

The human must decide the value, scope, target, association, or rating before
seeing the candidate model's output.

For page benchmarks, label **Source truth**, not world truth or Hunt preference.
If a frozen page states a stale date or a disputed amenity, the label records
what that Source states. RECONCILE and SCORE are separate concerns.

### 2.2 Freeze inputs before comparing models

Every comparison must use:

- the same saved corpus pages or normalized images;
- the same human labels;
- the same prompt version;
- the same generated schema;
- the same deterministic preprocessing;
- the same date basis;
- the same acceptance calculation.

Do not compare one model on newly fetched pages with another on old snapshots.

### 2.3 Preserve the local eval kit

The real corpus and labels are intentionally gitignored. Before every labeling
session and every record-mode run, copy these directories to a private,
recoverable location outside the repository:

```text
worker/tests/fixtures/corpus/
worker/tests/fixtures/bench/labels/
worker/tests/fixtures/vision_labels/
worker/evals/reports/
```

Do not rely on the repository, a listing remaining online, or a hostile Source
remaining fetchable as the backup.

### 2.4 Resolve model configuration before spending

Before any live benchmark:

```bash
uv run --package manzil-worker python -c \
  "from manzil_worker.llm.config import MODEL_PRICES, model_for_stage; \
print({s: (model_for_stage(s), model_for_stage(s) in MODEL_PRICES) \
for s in ('extract', 'verify', 'reconcile_equivalence', 'image_classify', 'vision')})"
```

Every selected model must:

- match the intended pin or explicit benchmark override;
- appear in `MODEL_PRICES`;
- route through OpenRouter;
- support the required structured/vision call;
- be traced by Langfuse.

At the time this document was written, the uncommitted working tree assigned
`google/gemini-3.6-flash` to IMAGE_CLASSIFY and VISION even though that slug was
not in `MODEL_PRICES`, contradicting the recorded pins. Resolve that conflict
before running B4 or B5.

### 2.5 Use record and replay deliberately

Live record mode spends money and creates local recordings:

```bash
MANZIL_LLM_MODE=record uv run --package manzil-worker manzil <bench-command>
```

Replay proves that the captured requests are reproducible without another
provider call:

```bash
MANZIL_LLM_MODE=replay uv run --package manzil-worker manzil <bench-command>
```

A replay pass is a reproducibility check, not new model evidence. The evidence
comes from the live traced call and frozen human labels.

### 2.6 Review raw counts, not only percentages

Every report should retain:

- number of eligible inputs;
- number actually graded;
- skipped/incomplete inputs;
- failures and malformed responses;
- numerator and denominator for every accuracy metric;
- token counts, cost, and latency;
- prompt/model/reference versions;
- zero-tolerance error lists.

A high percentage over a silently reduced denominator is not a pass.

## 3. B1 — Canonical-ten scoped Extraction and Gate benchmark

### 3.1 Claim this benchmark supports

B1 determines whether the current EXTRACT/VERIFY path can correctly recover:

- Property versus exact Floor Plan targets;
- `all_units`, `select_units`, and `unit_scope_unspecified` applicability;
- explicit positive and negative claims;
- Source-local references shared by several Floor Plans;
- abstention when the Source is silent;
- the P3-SC6 objective unit features;
- P3-SC7 `flooring_materials`;
- diagram association truth;
- Gate-bearing values without regressions.

It is the missing human evidence behind P3-SC4, P3-SC6, and P3-SC7. P3-6 was
allowed to ship without it by an explicit Owner waiver; the waiver did not make
the accuracy claim true.

### 3.2 Existing assets and current audit

The local kit contains 21 label JSON files:

- 10 are gradeable legacy labels;
- 11 are unfinished skeletons.

Run the current audit:

```bash
uv run --package manzil-worker manzil bench-audit-scoped
```

As of 2026-07-29, every required scoped/diagram coverage class is missing:

- exact;
- all units;
- select units;
- unspecified unit scope;
- negative;
- missing;
- one claim shared by several Floor Plans;
- ambiguous diagram;
- unambiguous diagram.

The audit also reports missing positive/negative/scope/silence coverage for:

- `walk_in_closets`;
- `pantry`;
- `disposal`;
- `fireplace`;
- `ceiling_fans`;
- `stainless_steel_appliances`;
- `flooring_materials`.

### 3.3 Select the canonical ten before labeling

Do not label all 21 pages by default. Select exactly ten frozen Sources that,
together, cover the matrix.

Prefer a small set-cover approach:

1. Search each `cleaned.txt` for the scoped Criterion vocabulary and qualifiers
   such as “all,” “every,” “select,” “some,” “certain,” “varies,” and Floor Plan
   names.
2. Inspect the saved page structure or local HTML for the actual association.
3. Record which required cases each Source can truthfully cover.
4. Choose ten Sources spanning several site templates and fetch tiers.
5. Fill the corresponding rows in
   `worker/tests/fixtures/bench/manifest.md`: page traits, why the page earned a
   slot, and the eventual labeling date.

Use `--label <slug>` repeatedly with the audit and run commands when the
directory still contains non-canonical labels. The selected set, not incidental
directory contents, must contain exactly ten finished labels.

### 3.4 Label format

Each label lives at:

```text
worker/tests/fixtures/bench/labels/<slug>.json
```

The main fields are:

```json
{
  "slug": "domain--property",
  "url": "https://source.example/property",
  "labeled_at": "2026-07-29",
  "notes": "Human notes about ambiguity",
  "criteria": {},
  "unknown": [],
  "floor_plans": [],
  "scoped_claims": {},
  "diagram_associations": []
}
```

Label ordinary Property/page fields in `criteria`. Put a key in `unknown` only
when the Source genuinely does not state it. Keys absent from both are not
graded.

For multi-plan pages, do not put one Property-wide `beds`, `baths`, or `sqft`
value in `criteria`. Put those facts on the appropriate `floor_plans`.

Each labeled Floor Plan needs a stable response-local `response_key`. Scoped
exact claims refer to those keys:

```json
{
  "scoped_claims": {
    "dishwasher": [
      {
        "value": true,
        "applicability": "specific_floor_plans",
        "floor_plan_refs": ["plan_a1"]
      }
    ],
    "fireplace": [
      {
        "value": true,
        "applicability": "select_units",
        "floor_plan_refs": []
      }
    ],
    "ceiling_fans": []
  }
}
```

Interpret applicability conservatively:

| Source evidence | Label |
|---|---|
| Explicitly tied to named/card/native-ID Floor Plans | `specific_floor_plans` with those refs |
| Explicitly says all/every unit | `all_units`, no refs |
| Explicitly says select/some/certain units or the feature varies | `select_units`, no refs |
| Advertises a unit feature without saying which units | `unit_scope_unspecified`, no refs |
| Says nothing about the Criterion | An empty list for that Criterion |

Never infer exact applicability because a feature appears near a Floor Plan in
the cleaned text. The page structure itself must establish the association.

For diagrams:

```json
{
  "diagram_associations": [
    {
      "candidate_ref": "stable-local-candidate-reference",
      "floor_plan_refs": ["plan_a1"],
      "ambiguous": false
    },
    {
      "candidate_ref": "another-candidate",
      "floor_plan_refs": [],
      "ambiguous": true
    }
  ]
}
```

An ambiguous diagram must have no Floor Plan refs. A diagram may name several
refs only when the Source explicitly establishes that association.

### 3.5 Labeling workflow

For each selected Source:

1. Open `cleaned.txt`, `meta.json`, and the saved HTML.
2. Write the true Floor Plan list first, including `response_key`.
3. Label existing scoped Criteria:
   patio/balcony, private entry, laundry, parking, cooling, dishwasher, and
   heating.
4. Label every P3-SC6/SC7 key, using an empty list for genuine Source silence.
5. Inspect diagram context and label ambiguous/unambiguous associations.
6. Fill ordinary Gate/rent/fee fields that the existing label already grades.
7. Set `labeled_at` only after the complete file has been reviewed.
8. Run `bench-audit-scoped` against the selected ten.

Suggested review discipline:

- first pass labels values and scope;
- second pass checks every exact Floor Plan ref against page structure;
- final pass checks every empty list really means silence, not overlooked
  evidence.

### 3.6 Tooling gap: diagram grading

`bench-audit-scoped` counts diagram coverage, but `bench-run` currently does
not grade `diagram_associations`. Therefore B1 cannot produce diagram-association
accuracy from the current harness.

Before claiming B1 complete, extend the corpus result and harness to compare:

- expected versus discovered diagram candidates;
- correct exact associations;
- missed associations;
- wrong associations;
- correct abstentions on ambiguous candidates.

Wrong diagram-to-Floor-Plan associations must be a raw zero-tolerance count.

### 3.7 Run the current-pin baseline

After the audit passes and diagram grading exists:

```bash
MANZIL_LLM_MODE=record uv run --package manzil-worker manzil bench-run \
  --name scoped-current-pin \
  --label <slug-1> \
  --label <slug-2> \
  --label <slug-3> \
  --label <slug-4> \
  --label <slug-5> \
  --label <slug-6> \
  --label <slug-7> \
  --label <slug-8> \
  --label <slug-9> \
  --label <slug-10>
```

Then run the identical replay command.

Review at minimum:

- failures and skipped labels;
- Criterion and Gate accuracy;
- Floor Plan field accuracy;
- scoped-claim accuracy;
- exact-target recall;
- `wrong_exact_associations`;
- diagram association errors;
- VERIFY evidence-flag rate;
- schema retries/failures;
- input/output/cache tokens;
- total and per-Source cost;
- truncation or unusually large outputs.

### 3.8 Completion criteria

Existing design commitments require:

- exactly ten finished canonical labels;
- every audit coverage class present;
- zero wrong exact Floor Plan associations;
- no Gate regression hidden by missing/unknown coercion;
- diagram ambiguity handled without invented associations;
- current model/prompt/schema versions recorded;
- report reviewed and retained;
- actual outcome recorded in `DESIGN.md` §20 before the debt is called passed.

The design does not currently pin one universal minimum scoped-claim percentage.
Record raw per-Criterion results and make an explicit Owner decision if the
observed errors require a threshold or block rollout.

## 4. B2 — Auxiliary EXTRACT-block benchmark

### 4.1 Claim this benchmark supports

EXTRACT gained important non-Catalog blocks after the original Phase 0 label
contract:

- `pet_costs`;
- `utilities`;
- `mandatory_fees`;
- `one_time_fees`;
- `heating` / scoped `heating_type`;
- `property_identity`;
- `property_contact`.

These fields affect all-in monthly cost, move-in cost, utility composition,
Property identity, and contact display. The standing rule says an
output-affecting schema or prompt change requires a bench rerun.

Later prompt-v8 record runs exercised the enlarged schema and measured
regression on the fields the harness already knows. They did **not** establish
accuracy for most auxiliary blocks because `BenchLabel` and `bench-run` do not
grade them.

### 4.2 Required tooling

Extend the label contract with optional human-truth sections for the auxiliary
blocks. Keep them separate from `criteria`; they are not Rubric Criteria.

A suitable shape should cover:

```json
{
  "auxiliary": {
    "property_identity": {},
    "property_contact": {},
    "pet_costs": {},
    "utilities": {},
    "mandatory_fees": {},
    "one_time_fees": {},
    "heating": {}
  }
}
```

The exact schema should reuse the production Pydantic input models rather than
introducing a second hand-maintained vocabulary.

The grader must report each block independently:

- exact field matches;
- missing expected entries;
- invented entries;
- amount accuracy;
- fee basis accuracy (`flat`, `per_person`, `per_pet`, and so on);
- refundable/required status accuracy;
- normalized phone/contact URL accuracy;
- evidence flags;
- downstream composed all-in and move-in results where enough labeled inputs
  exist.

For lists of fees, match by normalized fee name plus basis, not list position.
Amounts and required/refundable semantics remain separately graded.

### 4.3 Labeling process

Use the same canonical frozen pages where possible, adding a Source only for a
real coverage gap.

For each page:

1. Label only what that Source states.
2. Separate recurring mandatory fees from one-time fees.
3. Record fee basis exactly; do not convert per-person/per-pet fees into a
   household total in the Source label.
4. Preserve null/unstated refundable status rather than guessing.
5. Record utilities as included only when inclusion is explicit.
6. Record heating type and applicability from the Source evidence.
7. Record only Property-level business contact details—never a named
   individual, personal email, or personal direct line.
8. Label identity exactly as the page presents it; DEDUPE/geocoding are outside
   this bench.

Include deliberate negative/silence cases so the model is penalized for
inventing fees or contacts.

### 4.4 Run procedure

Once the label/harness extension lands, use the ordinary `bench-run` current-pin
record and replay workflow from B1. The report should include both existing
Catalog metrics and the new auxiliary-block section so schema growth cannot
improve one surface while regressing another.

### 4.5 Completion criteria

- All cost-critical auxiliary fields have positive and silence/unknown cases.
- No invented mandatory or one-time fee is accepted.
- No fee basis is silently flattened.
- The composed all-in and move-in goldens agree exactly where the labeled
  inputs are complete.
- Contact output contains only approved business-level fields.
- Current EXTRACT/VERIFY pins, prompt versions, cost, and failures are recorded.
- P3-9/P3-21 no longer carry an unqualified “bench rerun owed” note.

## 5. B3 — RECONCILE semantic-equivalence model comparison

### 5.1 Claim this benchmark supports

P3-6 uses deterministic reconciliation except for one narrow model judgment:
semantic equivalence normalization before comparison. Examples include:

- “W/D in unit” versus “in-unit laundry”;
- equivalent parking or cooling wording;
- wording that looks similar but must remain distinct, such as hookups versus
  an installed washer/dryer;
- positive versus negative statements;
- exact Floor Plan versus generalized applicability.

Gemini 3 Flash Preview was approved for this work under the P3-6 waiver, but no
reconciliation-specific model comparison established that it is the best pin
or measured its dangerous false-equivalence rate.

### 5.2 Required dataset

Build a gitignored reconciliation label set from Properties with multiple saved
Sources. The existing corpus already contains useful multi-Source groups such
as Springs at Canton, Bainbridge Park, Pilgrim Village, and Village of Canton.

Each case should contain:

```json
{
  "case_id": "stable-id",
  "criterion_key": "in_unit_laundry",
  "target_scope": "property",
  "floor_plan_ref": null,
  "claims": [
    {
      "text": "W/D in unit",
      "value": "in_unit",
      "applicability": "unit_scope_unspecified"
    },
    {
      "text": "In-unit washer and dryer",
      "value": "in_unit",
      "applicability": "unit_scope_unspecified"
    }
  ],
  "equivalence_groups": [[0, 1]],
  "must_not_merge": []
}
```

The human labels equivalence groups. The dataset must deliberately include:

- true paraphrases;
- negation;
- installed equipment versus hookups;
- amenity room versus in-unit feature;
- `none` versus missing/unknown;
- same value with different applicability;
- different typed variants that may coexist;
- numeric cases that should never need the model;
- Floor Plan-specific claims that must never become Property-wide through
  equivalence.

### 5.3 Required tooling

No dedicated command exists. Add a `reconcile-equivalence-bench` harness that:

1. Sends the identical labeled claim batches through
   `call_structured("reconcile_equivalence", ...)`.
2. Applies the production response parser.
3. Compares predicted groups to human groups.
4. Optionally runs the deterministic ladder with the predicted groups to expose
   downstream resolution differences.
5. Supports repeatable model overrides through
   `MANZIL_MODEL_RECONCILE_EQUIVALENCE`.
6. Writes a versioned JSON report and Langfuse trace IDs.

Report:

- pairwise equivalence precision and recall;
- harmful false merges;
- missed equivalences;
- protocol/schema failures;
- end-to-end resolution agreement;
- changes to `disputed` and checkpoint outcomes;
- wrong target/applicability effects;
- calls, tokens, cost, and latency.

### 5.4 Run procedure

After labeling and implementing the harness:

```bash
MANZIL_LLM_MODE=record \
MANZIL_MODEL_RECONCILE_EQUIVALENCE=<candidate-model> \
uv run --package manzil-worker manzil reconcile-equivalence-bench \
  --name <candidate-name>
```

Run every candidate over the same cases. Then replay each report and compare
them with a dedicated comparison table or a small report script.

### 5.5 Completion criteria

The original waiver does not define a numeric pass threshold. Before declaring
a winner:

- treat harmful false equivalence as the primary safety metric;
- require zero target/applicability widening;
- inspect every false merge manually;
- compare cost and latency only after safety/accuracy;
- retain the deterministic exact-match fallback behavior;
- record any pin change in `DESIGN.md` §20.

## 6. B4 — IMAGE_CLASSIFY selection benchmark

### 6.1 Claim this benchmark supports

B4 measures whether IMAGE_CLASSIFY plus the deterministic selector chooses the
right kitchen images for the expensive quality call.

It is not a kitchen-quality rating benchmark. It measures routing:

- is a kitchen visible?
- is it assessable?
- is the image irrelevant or a Floor Plan diagram?
- does the selector choose at most three useful, non-duplicate targets?

### 6.2 Existing labels

The local kit at `worker/tests/fixtures/vision_labels/` already contains:

- 294 normalized images;
- 10 Properties;
- 74 kitchen-visible images;
- 68 kitchen-assessable images;
- 17 Floor Plan diagrams;
- 65 irrelevant images;
- human-reviewed duplicate groups for 158 images.

Kitchen and `content_kind` labeling is complete. `flooring_visible` and
`bathroom_visible` are blank for all 294 rows; that does not block B4 because
those features are disabled.

### 6.3 How to create or refresh the label kit

Only regenerate the kit when intentionally replacing the frozen dataset:

```bash
uv run --package manzil-worker manzil vision-label-kit \
  --from-corpus \
  --max-properties 10 \
  --max-images-per-property 30
```

Or, with configured database and private image Storage, omit `--from-corpus`
to use current Property images.

Open:

```text
worker/tests/fixtures/vision_labels/contact-sheet.html
```

Fill `labels.csv`:

| Column | Human rule |
|---|---|
| `kitchen_visible` | `TRUE` when any recognizable kitchen is visible |
| `kitchen_assessable` | `TRUE` only when cabinetry, counters, and major appliances are sufficiently visible to compare finish quality |
| `content_kind` | exactly `listing_photo`, `floor_plan_diagram`, or `irrelevant` |
| `duplicate_group` | same non-empty ID for genuinely near-identical views; blank otherwise |
| `notes` | ambiguity worth retaining in the report |

`kitchen_assessable` cannot be true when `kitchen_visible` is false.

Generate deterministic duplicate candidates:

```bash
uv run --package manzil-worker manzil vision-duplicate-suggestions
```

Open `duplicate-review.html`, review every suggested cluster, and copy only
true near-duplicate group IDs into `labels.csv`. The dHash suggestion is not
ground truth.

### 6.4 Current protocol problem

The strict candidate runs did not reach accuracy scoring:

- Gemini 3 Flash Preview returned 29 of 30 requested hashes;
- Gemini 3.1 Flash Lite returned a duplicate;
- Gemini 2.5 Flash Lite returned one missing and one unknown hash;
- Sonnet 4.6 returned a duplicate.

The interface presents both a thumbnail SHA-256 and the original Property-image
hash. A model can classify the pixels correctly but return the wrong hash.

Before spending on another sweep, change the per-call identity contract to
short IDs such as `img_01` through `img_30`, constrained by the generated
schema. Map those IDs back to trusted hashes in code. Keep hash validation and
caching internal.

The benchmark should then separate:

- strict response completeness;
- production-tolerated response reconciliation;
- classification/selection accuracy.

A model that misses one ID should receive a protocol penalty without erasing
the accuracy evidence from the other 29 images.

### 6.5 Run the benchmark

For the default candidate set:

```bash
MANZIL_LLM_MODE=record uv run --package manzil-worker \
  manzil vision-classifier-bench \
  --out worker/evals/reports/vision-classifier-bench.json
```

For an explicit model:

```bash
MANZIL_LLM_MODE=record uv run --package manzil-worker \
  manzil vision-classifier-bench \
  --model <openrouter-model-slug> \
  --out worker/evals/reports/vision-classifier-<model-name>.json
```

The model must be present in `MODEL_PRICES`.

After a successful record run, repeat in replay mode.

### 6.6 Required metrics and pass gate

The existing gate is:

- at least 95% precision among selected kitchen targets;
- at least 90% Property-level kitchen recall with the three-target quota;
- zero selections on labeled no-kitchen Properties;
- zero selected Floor Plan diagrams;
- zero duplicate-target violations;
- classification cost below $0.005 per 30-image Property.

Also retain:

- assessable precision;
- missing/unknown/duplicate response counts;
- selected image IDs;
- per-Property errors;
- confidence distribution;
- batch size;
- latency.

Run slice analysis for open-plan rooms, partial kitchens, low-resolution images,
renderings, amenity kitchens, and images combining living/kitchen areas.

### 6.7 Completion criteria

- One frozen human label set and one versioned report.
- Strict protocol behavior reported independently from accuracy.
- All gate denominators include all ten Properties.
- Every selected false positive manually reviewed.
- Owner-selected pin either passes or remains explicitly recorded as an
  override without an accuracy claim.
- Any pin or protocol change that affects production is reflected in design and
  prompt/model versioning as required.

## 7. B5 — External kitchen-quality VISION benchmark

### 7.1 Claim this benchmark supports

B5 measures the final subjective rating produced after B4 chooses kitchen
targets. It answers whether the anchored VISION model agrees consistently with
Yusuf's 1–5 kitchen-quality judgment.

Kitchen scoring is currently live using:

- approved kitchen reference profile v1;
- VISION prompt v1;
- the recorded Sonnet 4.6 quality pin;
- an explicit `deferred_owner_override` benchmark status.

That status means the feature is usable, not bench-validated.

### 7.2 Holdout selection

Use Properties/images outside the 25 approved reference anchors.

The holdout should contain:

- every quality level 1–5;
- older but clean kitchens;
- renovated kitchens;
- partial visibility;
- open-plan rooms;
- renderings if production may encounter them;
- images that should be `not_visible`;
- irrelevant/non-kitchen images as adversarial controls;
- exact Floor Plan-associated and generalized gallery examples.

Do not let the model select the only images the human rates. Freeze the
candidate/target set first, using either human selection or the already-frozen
B4 selector output.

### 7.3 Human labeling

Create a blind contact sheet that shows:

- one target image or the production group of up to three targets;
- an opaque target ID;
- no model output;
- no listing price, address, score, or marketing copy.

For each target/group, Yusuf records:

```json
{
  "target_id": "kq-001",
  "rating": 3,
  "visible": true,
  "acceptable_range": [2, 4],
  "notes": "Optional reason for an ambiguous boundary"
}
```

Use `visible=false` instead of inventing a rating when cabinetry, counters, and
major appliances cannot be judged.

Rate the complete holdout before running or opening model output. If references
are adjusted during labeling, discard the affected holdout run and begin again;
the holdout cannot also become training/reference material.

### 7.4 Required tooling

No dedicated kitchen-quality bench command exists today. Add a harness that:

1. Loads the approved reference manifest and validates every asset/sheet hash.
2. Loads frozen holdout images and human ratings.
3. Calls the production `call_vision("vision", ...)` path.
4. Validates missing/duplicate/unknown target IDs.
5. Applies the production weighted-median aggregation unchanged.
6. Grades per-target ratings and final aggregates.
7. Emits model, prompt, reference, token, cost, latency, and trace metadata.

Provide a CLI such as:

```text
manzil vision-quality-bench
```

with `--labels-dir`, repeatable `--model`, and `--out` options parallel to
`vision-classifier-bench`.

### 7.5 Run procedure

Once the harness exists:

```bash
MANZIL_LLM_MODE=record uv run --package manzil-worker \
  manzil vision-quality-bench \
  --labels-dir worker/tests/fixtures/vision_quality_labels \
  --model <candidate-model> \
  --out worker/evals/reports/vision-quality-<candidate>.json
```

Run the recorded quality pin first. Run alternative models only against the
same frozen labels, reference version, and prompt.

Repeat the winning run in replay mode.

### 7.6 Required report

Report:

- exact agreement;
- within-one agreement;
- mean absolute error;
- confusion matrix by human rating 1–5;
- unknown/not-visible rate;
- aggregation withheld because target spread exceeded the allowed bound;
- exact Floor Plan versus generalized-gallery results;
- every irrelevant/non-kitchen confident rating;
- cost and latency per Property;
- model, prompt, and reference version.

### 7.7 Completion criteria

The existing design requires every accepted aggregate to be within ±1 of the
human rating. Also require:

- no confident rating on an irrelevant/non-kitchen control;
- no rating when visibility is insufficient;
- all reference hashes and membership validated;
- production aggregation used without benchmark-only exceptions;
- actual results appended to `DESIGN.md` §20;
- `quality_benchmark_status` changed from `deferred_owner_override` only after
  the evidence really passes.

## 8. Conditional future vision benches

### 8.1 Flooring quality

Do not start merely because `flooring_visible` is blank in the current
classifier CSV. Flooring quality remains disabled.

Before activation:

1. Approve the flooring Criterion behavior and scoring role.
2. Build and approve 3–5 reference anchors for each 1–5 level.
3. Assign a quota within the total eight-image VISION cap.
4. Label flooring visibility/assessability on a frozen classifier set.
5. Run a flooring selector bench equivalent to B4.
6. Build a blind holdout outside the anchors.
7. Run a quality bench equivalent to B5.
8. Record the Catalog, quota, references, model, and rollout decision in
   `DESIGN.md` §20.

### 8.2 Bathroom

Bathroom visibility exists in the classifier schema, but there is no active
bathroom quality Criterion. It is not current benchmark debt.

Activation requires a separate Catalog/design decision, reference scale,
selector quota, human label pass, quality bench, and Decision Log entry.

## 9. Work that is evidence debt but not a benchmark

Keep these visible, but do not mix them into model accuracy reports:

- P3-SC5 light-mode and approximately 375 px visual inspection;
- real-page exercise of `full_size_url`;
- a live ingest followed by an unchanged refresh proving zero classifier and
  quality calls once refresh/hash gating exists;

These are visual, integration, or operational acceptance checks.

## 10. Recommended execution order

1. **Resolve current model-pin/configuration drift.**
2. **B4 protocol repair and classifier run.** Labels already exist, so this is
   the fastest high-value closure.
3. **Choose and label the B1 canonical ten.** Use the audit continuously rather
   than waiting until all pages are labeled.
4. **Add B1 diagram grading and run the current-pin scoped baseline.**
5. **Extend the same labels/harness for B2 auxiliary blocks** and rerun
   EXTRACT/VERIFY.
6. **Build and run B5 kitchen-quality holdout.**
7. **Build B3 reconciliation-specific comparison.** It is narrower in runtime
   impact but needs a new dataset and harness.
8. Leave flooring and bathroom benches dormant until their features are
   deliberately activated.

## 11. Final closeout checklist

For each active benchmark:

- [ ] Frozen inputs backed up privately.
- [ ] Human labels completed before model output review.
- [ ] Label validator/audit passes.
- [ ] Current model, prompt, schema, and reference versions recorded.
- [ ] Live record-mode run completed and traced.
- [ ] Replay-mode run reproduces the result without provider spend.
- [ ] Failures, skips, malformed responses, and raw denominators reviewed.
- [ ] Zero-tolerance errors manually inspected.
- [ ] Cost and latency recorded.
- [ ] Report retained with an unambiguous name/date.
- [ ] Result—not merely the fact that a run occurred—recorded in the relevant
      implementation status.
- [ ] Any model/behavior rollout decision appended to `DESIGN.md` §20.
- [ ] Gitignored corpus, labels, recordings, and reports backed up again.
