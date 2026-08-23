# ONNX image classification: architecture and operation

**Status:** retained unused implementation. Live `IMAGE_CLASSIFY` is an LLM
(`openai/gpt-5.6-luna`, DESIGN v3.102). Do not load this
artifact on Render's starter instance.

**Last updated:** 2026-08-21

This guide is the operational reference for Manzil's **retained** local ONNX
`IMAGE_CLASSIFY` backend. It is not the workflow path. Use it only when
reverting onto a host with enough RAM. The live classifier and quality VISION
pins live in `worker/src/manzil_worker/llm/config.py`. The benchmark evidence
and model comparison remain in
[`image-classification-ml-analysis.md`](image-classification-ml-analysis.md).

## 1. What is implemented now

DESIGN v3.102 restored the structured LLM classifier as the workflow path and
left this ONNX stack unwired — not deleted:

```text
normalized Property image
          |
          +--> call_vision(image_classify) --> vision_assessment.classification
          |                                      |
          |                                      +--> diagram kind promotion
          |                                      +--> LLM kitchen selector
          |                                      +--> anchored quality VISION
          |
          +--> ONNX subprocess   (retained; not called)
```

`image_classify_stage` never invokes `ctx.image_classify_onnx`, never writes
`classification_shadow`, and does not fall back to ONNX on LLM failure. The
ONNX stage function is `_image_classify_onnx_stage`. `StageCtx` defaults the
seam to `None`; `_configured_image_classify_onnx` still builds it from
`MANZIL_IMAGE_CLASSIFY_ONNX_DIR` for a revert.

Implementation (retained):

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

`MANZIL_IMAGE_CLASSIFY_ONNX_DIR` is unused on the workflow path (DESIGN v3.102).
Leave it unset on Render's $7 starter instance. Setting it does nothing unless
you restore `_configured_image_classify_onnx` as the `StageCtx` default and
point `image_classify_stage` at `_image_classify_onnx_stage`.
`MANZIL_IMAGE_CLASSIFY_ONNX_SHADOW_DIR` remains a path alias inside that unused
factory only.

### 7.3 Persistence, migration, and rollback

The live path (DESIGN v3.102):

1. classifies through `call_vision("image_classify", …)`;
2. never constructs or calls the ONNX subprocess;
3. persists a versioned LLM `classification` record (`model:prompt-<version>`);
4. treats an ONNX-shaped incumbent as stale, reclassifies, and keeps it as
   `classification_onnx_legacy`;
5. selects kitchen targets from the structured LLM fields;
6. fails closed on a malformed LLM batch past `IMAGE_CLASSIFY_ANOMALY_TOLERANCE`.

To restore ONNX as authority: restore `image_classify_stage` to
`_image_classify_onnx_stage`, wire `StageCtx.image_classify_onnx` with
`_configured_image_classify_onnx`, require the artifact on a host with enough
RAM (not Render starter), issue a new DESIGN ruling, and refresh affected
images. Dual-running ONNX as shadow or fallback is not a rollback option on
the current host — it reintroduces the OOM.

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
