# ONNX image classification: architecture, operation, and promotion

**Status:** ONNX shadow implemented; ONNX-only authority not implemented or approved

**Last updated:** 2026-08-01

This guide is the operational reference for Manzil's local ONNX
`IMAGE_CLASSIFY` candidate. It covers the model and classification logic, the
implemented shadow path, local development, production deployment, and the
work required before the LLM classifier can be removed. The benchmark evidence
and model comparison remain in
[`image-classification-ml-analysis.md`](image-classification-ml-analysis.md).

## 1. What is implemented now

The authoritative `IMAGE_CLASSIFY` result is still the structured VISION-seam
classifier described by DESIGN §10.8. When explicitly enabled, the selected
ONNX model runs beside it as an observation-only shadow:

```text
normalized Property image
          |
          +--> incumbent classifier --> vision_assessment.classification
          |                               |
          |                               +--> image kind and target selection
          |
          +--> ONNX subprocess ------> vision_assessment.classification_shadow
                                          observation only
```

The shadow cannot change image kind, deterministic target selection, quality
`VISION`, Extractions, or SCORE. Its failure is logged and never fails or parks
the Job. No database migration is needed because `property_images` already
persists the complete `vision_assessment` JSON object.

Implementation:

- `worker/src/manzil_worker/vision_onnx.py` owns artifact verification,
  preprocessing, ONNX Runtime inference, subprocess transport, and telemetry.
- `worker/src/manzil_worker/stages/base.py` enables the injected shadow seam
  only when `MANZIL_IMAGE_CLASSIFY_ONNX_SHADOW_DIR` is set.
- `worker/src/manzil_worker/stages/image_classify.py` reads/writes the shadow
  cache, validates exact response identity, persists results, and logs
  disagreements without consulting them for pipeline decisions.
- `worker/src/manzil_worker/evals/clip_onnx.py` reproducibly exports the model.
- `worker/src/manzil_worker/evals/vision_ml_benchmark.py` grades it against the
  public held-out datasets.

## 2. Model artifact and inference logic

The selected artifact is the unsigned-int8, vision-only export of OpenAI CLIP
ViT-B/32:

| Property | Value |
|---|---|
| Backend | `clip-vit-b32-vision-uint8-onnx` |
| Runtime files | `model.onnx`, `manifest.json` |
| Directory size | about 97 MB |
| Directory SHA-256 | `af06481c9b95daa042c9d89f7c2412c845f98aca3706e1cc2d23e7dad853a00b` |
| Kitchen threshold | `0.7033675909042358` |
| Diagram threshold | `0.9717867374420166` |
| Runtime dependencies | Pillow, NumPy, ONNX Runtime |
| Export-only dependencies | PyTorch, Transformers, ONNX |

The artifact contains only CLIP's image tower and precomputed text-prototype
embeddings. It does not contain the text tower or tokenizer.

For each image, the subprocess:

1. decodes the unstored classifier thumbnail and converts it to RGB;
2. resizes the shortest edge to 224 px, center-crops to 224×224, and applies
   CLIP's fixed channel normalization;
3. runs the quantized image tower and L2-normalizes the image embedding;
4. computes cosine-similarity logits against the 67 fixed MIT Indoor scene
   prototypes and applies softmax;
5. reports the highest-probability scene;
6. sums the `kitchen` and `restaurant_kitchen` probabilities into the kitchen
   score and compares it with the calibrated kitchen threshold;
7. computes a separate two-prototype softmax between “Floor Plan diagram” and
   “indoor photograph,” then applies the calibrated diagram threshold.

One image is streamed at a time. ONNX Runtime uses one intra-op thread and one
inter-op thread, with its CPU arena, memory pattern, and weight prepacking
disabled. The parent launches a short-lived subprocess so model memory is
reclaimed before a later browser-tier Job.

The persisted shadow shape is:

```json
{
  "classification_shadow": {
    "cache_key": "<backend>:<artifact digest>:thresholds-v1",
    "backend": "clip-vit-b32-vision-uint8-onnx",
    "artifact_sha256": "af06481...",
    "kitchen_threshold": 0.7033675909042358,
    "diagram_threshold": 0.9717867374420166,
    "assessment": {
      "content_hash": "...",
      "predicted_scene": "kitchen",
      "kitchen_score": 0.98,
      "kitchen_predicted": true,
      "diagram_score": 0.001,
      "diagram_predicted": false
    }
  }
}
```

## 3. Local development: shadow mode available now

Add the absolute local artifact directory to the repository-root `.env`:

```dotenv
MANZIL_WORKER_INPROCESS=true
MANZIL_IMAGE_CLASSIFY_ONNX_SHADOW_DIR=/Users/ysaquib/Workshop/Experiments/manzil/worker/tests/fixtures/vision_benchmark/models/clip-vision-onnx-uint8
```

Then run the API with its optional runtime extra:

```bash
supabase start

uv run --package manzil-api --extra vision-onnx \
  uvicorn manzil_api.main:app --reload --port 8000 --workers 1
```

Run the frontend in another terminal:

```bash
pnpm -C frontend dev
```

Submit a Listing through the UI. The API owns the in-process worker loop, so
the shadow runs automatically when the Job reaches `IMAGE_CLASSIFY`. The
existing `scripts/dev` launcher does not request the optional extra; use the
manual API command above until that launcher is deliberately changed.

Unset or empty `MANZIL_IMAGE_CLASSIFY_ONNX_SHADOW_DIR` to disable the shadow.
This is the entire rollback in the current implementation.

## 4. Production API: shadow mode available now

Manzil currently deploys one Uvicorn process with the durable worker loop in
the API lifespan. The production API therefore needs the optional dependency,
the artifact, and the artifact-directory environment variable. The repository
does not yet contain the real production Dockerfile or Render blueprint;
`api/vision-onnx-smoke.Dockerfile` is a memory-test substrate only.

Package the two files without adding them to Git:

```bash
tar -C worker/tests/fixtures/vision_benchmark/models/clip-vision-onnx-uint8 \
  -czf /tmp/manzil-clip-vision-uint8.tar.gz \
  model.onnx manifest.json
```

Upload the archive to a stable release or object-store location. During the
production build, preserve the existing build steps and add the equivalent of:

```bash
uv sync --frozen --package manzil-api --extra vision-onnx --no-dev

mkdir -p .manzil/models/clip-vision-uint8
curl -fL --retry 5 "$MANZIL_CLIP_ONNX_ARCHIVE_URL" \
  -o /tmp/manzil-clip-vision-uint8.tar.gz
tar -xzf /tmp/manzil-clip-vision-uint8.tar.gz \
  -C .manzil/models/clip-vision-uint8

uv run --no-sync --package manzil-api python -c \
  'from pathlib import Path; from manzil_worker.vision_onnx import artifact_digest; print(artifact_digest(Path(".manzil/models/clip-vision-uint8")))'
```

The final command must print the pinned directory digest from §2. Configure the
runtime service with:

```dotenv
MANZIL_WORKER_INPROCESS=true
MANZIL_IMAGE_CLASSIFY_ONNX_SHADOW_DIR=.manzil/models/clip-vision-uint8
MANZIL_LLM_MODE=live
```

Keep Uvicorn at one process:

```bash
uvicorn manzil_api.main:app \
  --host 0.0.0.0 --port "$PORT" --workers 1
```

The model must be present before Uvicorn starts. Do not download it during an
individual Job. If the worker is later isolated into its own service, install
the extra, artifact, and variable on that worker and disable the API claimant;
the current repository does not yet have the standalone production entry
point.

## 5. Observing a shadow run

An uncached run emits `image_classify_onnx_shadow_complete` with classified and
cached counts, parent-observed wall time, throughput, child peak RSS, and the
hashes where kitchen or diagram decisions disagree with the incumbent.
`image_classify_onnx_shadow_failed` reports optional-backend failures.

Inspect persisted output with:

```sql
select
  id,
  content_hash,
  vision_assessment -> 'classification' as incumbent,
  vision_assessment -> 'classification_shadow' as onnx_shadow
from property_images
where vision_assessment ? 'classification_shadow'
order by created_at desc;
```

The local hard-limit simulation processed 30 images in 2.58 seconds and
reached about 442 MB combined cgroup peak under a 512 MB limit. The real Render
graph remains authoritative. Record service peak memory, API latency, and Job
IDs during representative Listing runs before promotion.

## 6. Why ONNX-only cannot be enabled yet

The current ONNX result is intentionally narrower than the authoritative
`ImageClassification` contract:

| Current authoritative field | ONNX currently supplies it? |
|---|---|
| primary room scene | Partially: 67 indoor scenes need mapping to Manzil's eight scenes |
| diagram | Yes |
| kitchen visibility/assessability | No; kitchen identity is not view usability |
| flooring assessability | No |
| bathroom visibility | No |
| full-room/partial/detail/unusable framing | No |
| irrelevant asset | No; maps, blanks, logos, collages, and contact cards are not covered |
| confidence | No calibrated Manzil confidence/abstention policy |

The deterministic kitchen selector requires high confidence, assessable kitchen
visibility, usable framing, and non-irrelevant/non-diagram status. Treating
every ONNX kitchen prediction as an assessable full-room kitchen would silently
change what reaches the anchored quality call. Filling the missing fields with
`unknown` would be honest but would select no kitchen targets. Neither behavior
is an acceptable production switch.

## 7. Work required for ONNX-only authority

Promotion is an implementation project and a material DESIGN decision, not an
environment-only toggle. It requires all of the following.

### 7.1 Finish the local classification contract

Add fixed, versioned prototype groups or deterministic producers for:

- asset kind: photograph, Floor Plan, map, blank/broken, logo/contact graphic,
  collage, rendering, and other;
- kitchen view usability: assessable, partial, or not visible;
- framing: full room, partial room, detail, or unusable;
- bathroom and flooring assessability where those fields remain in the shared
  classifier contract;
- an explicit abstention/confidence policy based on calibrated score and margin
  thresholds.

Alternatively, narrow the selector contract so it consumes explicit ONNX
scores rather than pretending the missing LLM fields exist. That still needs a
validated kitchen-usability gate. Deterministic decoding, size/uniformity, and
duplicate rules should handle assets they can measure more reliably than CLIP.

Define and test the mapping from MIT labels into Manzil's scene vocabulary. For
example, `kitchen` and `restaurant_kitchen` can map to `kitchen`, but indoor-only
MIT labels cannot establish `exterior`, and amenity versus unit interiors
cannot be inferred from scene identity alone.

### 7.2 Add an explicit backend setting

Introduce a setting such as:

```dotenv
MANZIL_IMAGE_CLASSIFY_BACKEND=llm|onnx_shadow|onnx
MANZIL_IMAGE_CLASSIFY_ONNX_DIR=/path/to/pinned/artifact
```

Neither setting exists today in this neutral form. The implemented
`MANZIL_IMAGE_CLASSIFY_ONNX_SHADOW_DIR` remains shadow-specific; promotion
should introduce the neutral artifact variable above (with a bounded migration
alias if needed) instead of making a variable named `SHADOW_DIR` authoritative.
The backend setting must make one backend authoritative at a time:

- `llm`: current behavior, no ONNX call;
- `onnx_shadow`: incumbent authoritative, ONNX observational;
- `onnx`: ONNX writes the canonical `classification`; no classifier LLM call.

Do not infer authority merely from whether an artifact directory happens to be
set. The artifact location and the product decision are separate settings.

### 7.3 Change persistence and selection deliberately

In ONNX-only mode:

1. validate the artifact during service startup so a missing or corrupt model
   fails deployment before Jobs are claimed;
2. run the ONNX subprocess before selection;
3. persist a versioned canonical `classification` record with backend,
   artifact digest, prototype version, thresholds, and normalized assessment;
4. run image-kind changes and target selection only from that canonical record;
5. remove the `call_vision("image_classify", ...)` path from the selected mode;
6. make runtime inference failure retryable or fail closed with no targets;
   never silently fall back unless fallback is an explicit backend policy;
7. preserve the old incumbent and shadow records long enough to audit and roll
   back without rewriting historical evidence.

Existing image rows need reclassification because their incumbent cache keys
describe another backend. Provide a bounded reclassification command or
image-scoped refresh; do not rely on waiting 30 days for the image TTL.

### 7.4 Clear promotion evidence

The public benchmark establishes room and diagram behavior, not Manzil gallery
behavior. Before ONNX becomes authoritative:

- run representative real Listing galleries through shadow mode;
- review maps, blanks, logos, collages, renderings, amenity kitchens,
  open-plan rooms, and partial/detail kitchen photographs;
- measure kitchen target-set precision/recall or at minimum review every
  incumbent/ONNX target-set disagreement;
- record abstention and no-target rates;
- confirm the real target host's memory, latency, restart, and API-health
  behavior;
- run deterministic invalid-asset, exact-hash, cache, retry, rollback, and
  selector tests;
- record the final model/prototype/threshold pin and the promotion in DESIGN
  §20.

This does not require labeling the duplicate-heavy 294-image set or training a
model. A small, deduplicated disagreement audit is sufficient for the rollout
decision, but some human review is unavoidable if the claim is that routing on
real Listing images is safe.

## 8. Local and production operation after promotion

These commands describe the intended post-implementation operation; setting
the proposed backend variable today has no effect.

Local `.env`:

```dotenv
MANZIL_WORKER_INPROCESS=true
MANZIL_IMAGE_CLASSIFY_BACKEND=onnx
MANZIL_IMAGE_CLASSIFY_ONNX_DIR=/absolute/path/to/clip-vision-onnx-uint8
```

Start the API with `--extra vision-onnx` exactly as in §3. The frontend remains
unchanged. `IMAGE_CLASSIFY` should emit no OpenRouter call or Langfuse LLM trace,
while later text and anchored quality stages still use their existing model
seams.

Production uses the same artifact build and one-process start from §4, plus:

```dotenv
MANZIL_IMAGE_CLASSIFY_BACKEND=onnx
```

Promotion does not remove `OPENROUTER_API_KEY` from the API/worker environment:
other pipeline stages and the separate anchored quality `VISION` stage still
use it. It removes only the generative `IMAGE_CLASSIFY` call.

Rollback sets the backend to `llm`, redeploys, and reclassifies affected hashes
under the incumbent cache key. Stored images, Floor Plan associations, quality
assessments, Extractions, and Scores remain intact; only classifier-derived
image kinds and target sets are recomputed.

## 9. Git and artifact handling

Commit the exporter, runtime, manifest schema, compact benchmark result, tests,
deployment logic, and documentation. Keep the 97 MB generated artifact and
public datasets out of Git. Git LFS is not required. Build or release storage
must retain the exact two-file artifact immutably and make its digest visible;
runtime network access and arbitrary model downloads remain forbidden.
