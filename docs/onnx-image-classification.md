# ONNX image classification: architecture and operation

**Status:** ONNX is the exclusive authoritative `IMAGE_CLASSIFY` backend (DESIGN v3.52)

**Last updated:** 2026-08-03

This guide is the operational reference for Manzil's local ONNX
`IMAGE_CLASSIFY` backend. It covers the model and classification logic, the
canonical runtime path, local development, production deployment, and the
accepted limitations of the narrowed selector contract. The benchmark evidence
and model comparison remain in
[`image-classification-ml-analysis.md`](image-classification-ml-analysis.md).

## 1. What is implemented now

The selected ONNX model is the only workflow classifier. The former structured
VISION-seam classifier remains in code as a disabled legacy function; no
production path invokes or falls back to it:

```text
normalized Property image
          |
          +--> ONNX subprocess --> vision_assessment.classification
                                      |
                                      +--> diagram kind promotion
                                      +--> top-three kitchen_score selector
                                      +--> anchored quality VISION
```

ONNX may promote a visually detected diagram but never demotes deterministic
diagram evidence. Its `kitchen_score` orders quality targets; it does not rate
kitchen quality. Failure is fatal to the Stage and follows ordinary Job retry
policy—there is no LLM fallback. No database migration is needed because
`property_images` already persists the complete `vision_assessment` JSON object.

Implementation:

- `worker/src/manzil_worker/vision_onnx.py` owns artifact verification,
  preprocessing, ONNX Runtime inference, subprocess transport, and telemetry.
- `worker/src/manzil_worker/stages/base.py` enables the canonical injected seam
  from `MANZIL_IMAGE_CLASSIFY_ONNX_DIR` (with the former shadow variable accepted
  temporarily as a compatibility alias).
- `worker/src/manzil_worker/stages/image_classify.py` reads/writes the canonical
  cache, validates exact response identity, persists results, promotes old
  shadow rows, and ranks kitchen targets.
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

The canonical persisted shape is:

```json
{
  "classification": {
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

## 3. Local development

Add the absolute local artifact directory to the repository-root `.env`:

```dotenv
MANZIL_WORKER_INPROCESS=true
MANZIL_IMAGE_CLASSIFY_ONNX_DIR=/Users/ysaquib/Workshop/Experiments/manzil/worker/tests/fixtures/vision_benchmark/models/clip-vision-onnx-uint8
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
ONNX runs automatically when the Job reaches `IMAGE_CLASSIFY`. The
existing `scripts/dev` launcher does not request the optional extra; use the
manual API command above until that launcher is deliberately changed.

`MANZIL_IMAGE_CLASSIFY_ONNX_SHADOW_DIR` remains a bounded compatibility alias
for existing installations. If neither variable is set, a Job with images fails
at `IMAGE_CLASSIFY`; it never activates the LLM classifier.

## 4. Production API

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
MANZIL_IMAGE_CLASSIFY_ONNX_DIR=.manzil/models/clip-vision-uint8
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

## 5. Observing a run

An uncached run emits `image_classify_onnx_complete` with classified and cached
counts, parent-observed wall time, throughput, and child peak RSS. A cached run
emits `image_classify_onnx_cached`. Failures propagate into ordinary Stage retry
and terminal Job error handling.

Inspect persisted output with:

```sql
select
  id,
  content_hash,
  vision_assessment -> 'classification' as onnx_classification,
  vision_assessment -> 'classification_llm_legacy' as prior_llm_classification
from property_images
where vision_assessment -> 'classification' ? 'backend'
order by created_at desc;
```

The local hard-limit simulation processed 30 images in 2.58 seconds and
reached about 442 MB combined cgroup peak under a 512 MB limit. The real Render
graph remains authoritative. Record service peak memory, API latency, and Job
IDs during representative Listing runs as ongoing operational evidence.

## 6. Deliberately narrowed contract

The canonical ONNX result is intentionally narrower than the former LLM
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

No missing field is synthesized. Deterministic `other` and Floor Plan kinds plus
ONNX diagram predictions are excluded; every remaining photo is ranked by
descending `kitchen_score`, and the top three go to anchored quality VISION.
That call still returns `visible | not_visible`, rating, and confidence, so a
high-probability but unrateable image is rejected at the stage that can actually
make that judgment.

## 7. Accepted debt and follow-up evidence

DESIGN v3.52 explicitly accepts promotion before the previously listed target-set
evidence is complete. The following remain debt, not runtime gates.

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

The shipped selector consumes explicit ONNX scores rather than pretending the
missing LLM fields exist. Deterministic decoding, size/uniformity, and duplicate
rules remain possible follow-up improvements where they outperform CLIP.

Define and test the mapping from MIT labels into Manzil's scene vocabulary. For
example, `kitchen` and `restaurant_kitchen` can map to `kitchen`, but indoor-only
MIT labels cannot establish `exterior`, and amenity versus unit interiors
cannot be inferred from scene identity alone.

### 7.2 Runtime configuration

`MANZIL_IMAGE_CLASSIFY_ONNX_DIR` names the required artifact. There is no backend
mode switch: DESIGN v3.52 makes ONNX authoritative in code, so artifact presence
cannot select LLM behavior. `MANZIL_IMAGE_CLASSIFY_ONNX_SHADOW_DIR` is accepted
only as a bounded path alias for installations created before promotion.

### 7.3 Persistence, migration, and rollback

The implemented path:

1. requires a configured artifact before classifying a non-empty gallery;
2. verifies the pinned digest in the ONNX subprocess before selection;
3. persist a versioned canonical `classification` record with backend,
   artifact digest, prototype version, thresholds, and normalized assessment;
4. run image-kind changes and target selection only from that canonical record;
5. never invokes `call_vision("image_classify", ...)` on the workflow path;
6. make runtime inference failure retryable or fail closed with no targets;
   never silently fall back unless fallback is an explicit backend policy;
7. promotes old shadow records without re-inference and retains replaced LLM
   records under `classification_llm_legacy`.

Existing image rows migrate through an image-scoped refresh; they do not wait for
the 30-day TTL. Rollback is a code decision, not an environment flip: restore the
retained legacy function as the workflow entry point, issue a new DESIGN ruling,
and refresh affected images. Stored legacy evidence remains available for audit.

### 7.4 Owed evidence

The public benchmark establishes room and diagram behavior, not Manzil gallery
behavior. The following evidence remains owed after the Owner-directed promotion:

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
- keep the pinned model/prototype/threshold record and operational telemetry
  current.

This does not require labeling the duplicate-heavy 294-image set or training a
model. A small, deduplicated disagreement audit is sufficient for the rollout
decision, but some human review is unavoidable if the claim is that routing on
real Listing images is safe.

## 8. Local and production operation

Local `.env`:

```dotenv
MANZIL_WORKER_INPROCESS=true
MANZIL_IMAGE_CLASSIFY_ONNX_DIR=/absolute/path/to/clip-vision-onnx-uint8
```

Start the API with `--extra vision-onnx` exactly as in §3. The frontend remains
unchanged. `IMAGE_CLASSIFY` should emit no OpenRouter call or Langfuse LLM trace,
while later text and anchored quality stages still use their existing model
seams.

Promotion does not remove `OPENROUTER_API_KEY` from the API/worker environment:
other pipeline stages and the separate anchored quality `VISION` stage still
use it. It removes only the generative `IMAGE_CLASSIFY` call.

Rollback requires the code-and-DESIGN procedure in §7.3; it is intentionally not
an unreviewed environment toggle.

## 9. Git and artifact handling

Commit the exporter, runtime, manifest schema, compact benchmark result, tests,
deployment logic, and documentation. Keep the 97 MB generated artifact and
public datasets out of Git. Git LFS is not required. Build or release storage
must retain the exact two-file artifact immutably and make its digest visible;
runtime network access and arbitrary model downloads remain forbidden.
