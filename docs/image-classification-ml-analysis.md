# Image classification without an LLM

**Status:** Public-data benchmark implemented; shadow evaluation still required

**Date:** 2026-08-01

**Updated finding:** The 294-image local kit is duplicate-heavy and contains
many maps, blanks, and other non-room assets. It is not recommended for
training or primary model selection.

**Scope:** Manzil's `IMAGE_CLASSIFY` gallery-routing stage, with a boundary
analysis of the downstream anchored `VISION` quality-rating stage

## Executive conclusion

Manzil does **not** need a generative LLM for `IMAGE_CLASSIFY`.

The current classifier is a constrained perception-and-routing problem:
identify kitchen photos, reject diagrams and irrelevant images, estimate
whether enough of the kitchen is visible, and let deterministic code choose at
most three diverse targets. A local pretrained scene or vision-language model
can do that job without task-specific training. The generative model's
29-of-30 response-completeness failure is evidence that free-form token
generation is a poor interface for a fixed batch-classification task, not
evidence that visual reasoning is indispensable.

The best fit for Manzil is:

1. Keep the existing deterministic image discovery, diagram signals, dHash
   clustering, Source-local Floor Plan associations, quotas, and selector.
2. Use a pretrained **SigLIP2 Base** model as an accuracy-first, hierarchical
   zero-shot classifier. Classify content kind first, then room scenes, then
   view usability/assessability. It can express maps, blanks, diagrams,
   renderings, open-plan rooms, and “assessable kitchen” without a custom
   trained head.
3. Benchmark it against pretrained **Places365-ResNet18**, the strict scene
   baseline, and **OpenAI CLIP ViT-B/32**, the smaller open-weight zero-shot
   comparison. MobileCLIP2 is not a production candidate because Apple's model
   terms restrict it to research and exclude product development.
4. Use MIT Indoor 67 and CubiCasa5K for the initial public-data benchmark. Keep
   SUN397, LSUN, ZInD, and ADE20K optional rather than requiring 36–108 GB
   downloads before the first decision. Do not train on the current 294-image
   kit or treat it as the primary acceptance set; after collapsing duplicates
   and unusable assets, it is only a weak regression smoke set.
5. Preserve an abstain/unknown path and promote a pretrained classifier only
   after external-dataset evaluation plus a live shadow run.
6. Keep the separate, subjective 1–5 `kitchen_quality` rating on anchored
   `VISION` for now. It may eventually be replaced by an ordinal or
   similarity-based model, but the current evidence is not enough to claim
   that replacement is safe.
7. When the deployment must remain on Render Starter, use the exported
   **vision-only CLIP uint8 ONNX** artifact as the practical shadow candidate.
   It preserves PyTorch CLIP's held-out kitchen and diagram results in 97 MB and
   completes a 30-image combined API/worker smoke run under the hard 512 MB
   limit. SigLIP2 remains the accuracy ceiling, not the $7 deployment choice.

This is pretrained discriminative vision rather than a classic hand-engineered
classifier, but it satisfies the practical goal: fully local, non-generative,
no task-specific labeling project, no per-image API cost, exactly one result
per input image, and no Property photos sent to a third party.

## Important repository conflict

DESIGN.md §10.8 and its 2026-07-28 Decision Log entry pin
`IMAGE_CLASSIFY` to `google/gemini-3-flash-preview`. IMPLEMENTATION.md records
the same pin. The current working copy of
`worker/src/manzil_worker/llm/config.py`, however, maps `image_classify` to
`TASTE_MODEL`, currently `anthropic/claude-sonnet-4.6`.

That is an authority conflict under the repository rules. The Owner directed
the 2026-08-01 **offline local-model benchmark** to proceed in isolation while
leaving the production pins untouched. Consequently the benchmark below does
not compare against, modify, or validate the incumbent production classifier.

Replacing the classifier is also a material design change: it requires an
in-place update to DESIGN.md §10.2/§10.8/§11/§15 and a §20 Decision Log entry
after the evaluation rules, model artifact, and rollback policy are accepted.

## What the current process actually does

The word “classification” hides two distinct model jobs:

```text
IMAGE_FETCH
  deterministic discovery, safety checks, normalization, hashes, context
       |
       v
deterministic diagram signals and Source-local associations
       |
       v
IMAGE_CLASSIFY                         <-- replacement candidate
  up to 30 separate <=384 px thumbnails
  scene / visibility / framing / confidence / irrelevant / diagram
       |
       v
deterministic dHash clustering and target selection
  at most 3 high-confidence, assessable, diverse kitchen images
       |
       v
VISION                                 <-- separate decision
  5 anchored rating sheets + selected full-size targets
  subjective kitchen-quality rating from 1 to 5
       |
       v
deterministic weighted median, provenance, Extraction, SCORE
```

`IMAGE_CLASSIFY` currently returns these fields for every thumbnail:

- `primary_scene`: kitchen, bathroom, living, bedroom, exterior, amenity,
  diagram, or other;
- kitchen, flooring, and bathroom visibility/assessability;
- framing: full room, partial room, detail, or unusable;
- confidence;
- irrelevant and diagram flags.

Production selection currently consumes much less:

- the image is not deterministically or visually a diagram;
- the image is not irrelevant or unusable;
- `kitchen_visibility == assessable`;
- confidence is high;
- the image is not a dHash near-duplicate;
- deterministic ordering then prefers exact Floor Plan evidence, distinct-plan
  coverage, full-room framing, and stable Source/page order.

Flooring and bathroom target quotas are disabled. Their classifier fields are
future-facing shadow output, not a present justification for an LLM. Likewise,
`primary_scene` is broader than the kitchen selector presently requires.

### Why the current LLM approach is mismatched

- The task has a small, fixed taxonomy and no need to generate prose.
- The model must reproduce 30 hashes exactly, turning a perception task into a
  brittle token-copying task. Every tested generative candidate violated the
  strict response contract; the selected model returned 29/30.
- Confidence words (`low`, `medium`, `high`) are model self-reports, not
  calibrated probabilities.
- Batching is economical for an API model but creates cross-image response
  coupling: one omitted or repeated record can degrade unrelated images.
- The model output requires anomaly reconciliation that a tensor classifier
  does not need. A local model naturally returns one fixed-size row for every
  input tensor.
- The current prompt asks for unused future fields, spending output tokens and
  increasing ways for the response to be internally inconsistent.

These are interface costs, not evidence that the model sees kitchens better
than a dedicated classifier.

## Does each decision require an LLM?

| Decision | LLM required? | Better non-LLM formulation |
|---|---:|---|
| Kitchen present | No | Pretrained scene classifier or zero-shot image encoder |
| Kitchen assessable for finish comparison | No in principle | Hierarchical zero-shot usability prompts with conservative abstention; optionally add appliance/cabinet evidence |
| Floor Plan diagram | No | Existing DOM/text rules plus image classifier; line/text-density features may assist |
| Irrelevant/logo/map/people-only | No | Zero-shot asset-kind prompts; deterministic metadata remains first |
| Primary room scene | No | Places365 or vision-language embedding similarity |
| Full/partial/detail/unusable framing | No in principle | Zero-shot usability prompts; abstain when views/templates disagree |
| Operational confidence | No | Similarity margin and cross-template/view agreement; do not call it calibrated |
| Near-duplicate removal | No | Existing dHash logic is already the right tool |
| Source-local Floor Plan association | No | Existing page-native evidence rules; visual similarity must remain forbidden |
| Subjective kitchen quality, 1–5 | Not necessarily, but not yet proven replaceable | Ordinal model or anchor-similarity/ranking model needs independent human-rated evaluation |
| Short visual rationale | Yes if prose is required | Do not require prose for routing; emit numeric evidence/features instead |

## Public pre-labelled datasets

Several credible datasets cover parts of Manzil's taxonomy. The right strategy
is to use their published pretrained models and validation splits, not create a
new hand-labelled room corpus.

| Dataset | Scale and labels | Best use for Manzil | Important mismatch |
|---|---|---|---|
| [Places365](https://github.com/CSAILVision/places365) | Millions of images across 365 scene classes; official pretrained CNNs | Primary pretrained baseline for kitchen, bathroom, bedroom, living room, exterior, and amenity scenes | Closed scene taxonomy; no assessability, maps/blanks, or listing-specific usability |
| [MIT Indoor 67](https://dspace.mit.edu/server/api/core/bitstreams/7f2c98d5-312e-4840-955e-4d320475b1a6/content) | 15,620 images across 67 indoor classes, including kitchen, bathroom, bedroom, and living room | Manageable independent room-classification evaluation set | General web imagery, not specifically rental listing galleries |
| [SUN397](https://docs.pytorch.org/vision/stable/generated/torchvision.datasets.SUN397.html) | 108,754 images across 397 scenes; SUN contains substantial kitchen, bathroom, bedroom, and living-room subsets | Broad scene evaluation and difficult negative classes | Broad domain and long-tail taxonomy |
| [LSUN](https://www.tensorflow.org/datasets/catalog/lsun) | Millions of labelled examples for kitchen, bedroom, living room, and dining room | High-volume room-scene evaluation or optional fine-tuning; kitchen alone is roughly 35 GB | Very large, no bathroom class, and labels do not express framing or assessability |
| [Zillow Indoor Dataset](https://github.com/zillow/zind) | 67,448 panoramas from 1,575 residential homes with room/layout annotations and Floor Plans | Closest residential-domain check and useful whole-room views | Controlled, mostly unfurnished 360-degree panoramas rather than listing-gallery crops; custom terms and approval; roughly 40 GB |
| [CubiCasa5K](https://arxiv.org/abs/1904.01920) | 5,000 densely annotated residential Floor Plan images | Positive corpus for Floor Plan diagram recognition | Contains diagrams but not the ordinary-photo negative distribution |
| [ADE20K](https://arxiv.org/abs/1608.05442) | About 22,000 scene-parsing images with indoor objects and regions | Optional appliance, cabinet, counter, and room-object evidence | Segmentation taxonomy rather than a ready-made gallery classifier |

## Implemented public-data benchmark

The repository now provides `manzil vision-ml-bench` and an optional
`vision-bench` dependency extra. Models and datasets remain in the gitignored
`worker/tests/fixtures/vision_benchmark/` directory. The harness is offline,
loads only local files, freezes every model, bounds inputs to the production
classifier's 384 px maximum, and emits JSON plus Markdown reports. A dedicated
Linux-compatible Dockerfile is `worker/vision-benchmark.Dockerfile`.

The full 2026-08-01 run used:

- 20 public MIT training images per class to calibrate one deterministic
  kitchen threshold by maximum F1;
- the complete official 1,340-image MIT `TestImages.txt` split for final
  kitchen-vs-rest and 67-way scene grading;
- 748 CubiCasa training diagrams plus 748 MIT photographs for diagram-threshold
  calibration;
- all 748 CubiCasa validation diagrams plus 748 held-out MIT photographs for
  final diagram grading;
- CPU-only inference on Darwin arm64 with batch size 16. These timings establish
  relative local cost, not yet the Linux hosting measurement.

No task-specific model weights were trained. Public training labels calibrated
thresholds only; all reported accuracy metrics use held-out splits.

| Model | Kitchen precision | Kitchen recall | Kitchen F1 | 67-way top-1 | Diagram precision | Diagram recall | Diagram F1 | Images/s | Artifact |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| SigLIP2 Base | 89.8% | **100.0%** | **94.6%** | **86.2%** | 100.0% | 99.7% | 99.9% | 25.7 | 1,539 MB |
| CLIP ViT-B/32 | **95.2%** | 90.9% | 93.0% | 74.9% | 100.0% | **99.9%** | **99.9%** | **67.6** | 609 MB |
| Places365 ResNet-18 | 80.4% | 84.1% | 82.2% | 22.1% | n/a | n/a | n/a | 50.1 | **46 MB** |

The kitchen test contained 44 positives. SigLIP2 found all 44 with five false
positives. CLIP missed four and produced two false positives. Places365 missed
seven and produced nine false positives. The stage's costlier error is a false
negative that omits useful evidence before quality scoring, so **SigLIP2 is the
accuracy-first shadow candidate when hosting permits it**. The later ONNX
deployment benchmark makes CLIP the selected $7 Render candidate. Places365 does
not clear the room-routing result and cannot visually reject Floor Plans with
its closed taxonomy.

The tracked compact evidence is
`worker/evals/vision-ml-benchmark-2026-08-01.json`; detailed per-run reports are
local artifacts under `worker/evals/reports/`.

### Vision-only CLIP ONNX comparison

`manzil vision-ml-export-clip-onnx` now reproducibly exports the downloaded
OpenAI CLIP checkpoint into three image-tower-only variants. The command
precomputes the fixed text embeddings, verifies FP32 output parity, quantizes
both signed and unsigned int8 alternatives, and writes a self-describing
manifest beside each model. Runtime classification needs Pillow, NumPy, and
ONNX Runtime, not PyTorch, Transformers, a tokenizer, or the 253 MB text tower.

```bash
uv run --package manzil-worker --extra vision-bench \
  manzil vision-ml-export-clip-onnx
```

All variants were graded on the same complete held-out splits as the original
models:

| CLIP runtime | Artifact | Kitchen precision | Kitchen recall | Kitchen F1 | 67-way top-1 | Diagram F1 | Render Starter result |
|---|---:|---:|---:|---:|---:|---:|---|
| PyTorch, full model | 609 MB | 95.2% | 90.9% | 93.0% | 74.9% | 99.9% | Does not leave safe API/worker headroom |
| ONNX FP32, vision only | 352 MB | 95.2% | 90.9% | 93.0% | 74.9% | 99.9% | Failed the hard-limit combined diagnostic |
| ONNX signed int8, vision only | 97 MB | 95.1% | 88.6% | 91.8% | 74.6% | 99.7% | Fits, but loses one additional kitchen true positive |
| **ONNX unsigned int8, vision only** | **97 MB** | **95.2%** | **90.9%** | **93.0%** | 74.6% | **99.9%** | **Fits in streaming mode; selected deployment candidate** |

The unsigned variant exactly preserved PyTorch CLIP's kitchen confusion counts
(40 true positives, two false positives, four false negatives) and diagram
result. Its 67-way result changed from 74.93% to 74.55%, a five-image difference
over 1,340 test images. Signed int8 was rejected because the smaller result was
not worth an additional kitchen false negative.

The closest local Render Starter simulation used `linux/arm64`, a hard 512 MB
memory limit with swap disabled, 0.5 CPU, the actual FastAPI application and
worker imports, ONNX prepacking/memory arenas disabled, and one image at a
time. The final unsigned-model run processed 30 images in 2.58 seconds (11.6
images/s), with 248 MB process peak RSS and 442 MB cgroup peak. It recorded zero
memory-pressure and zero OOM events, leaving approximately 70 MB cgroup
headroom.
`api/vision-onnx-smoke.Dockerfile` reproduces the API/worker dependency
substrate; it is intentionally not a deployment image because it excludes both
the generated model artifact and Playwright's Chromium binary.

This establishes **technical fit for a serialized shadow stage**, not unlimited
co-residency. Chromium must not overlap inference on Starter, Uvicorn must stay
at one process, and loading the model in a short-lived subprocess is safer than
keeping it resident across later Tier-2 Jobs. The real Render service still
needs an observed live-job memory check before promotion.

### Implemented shadow rollout path

The consolidated model, runtime, local-development, production-deployment,
observability, and ONNX-only promotion guide is
[`onnx-image-classification.md`](onnx-image-classification.md). This section
retains the benchmark conclusion and deployment-fit evidence.

The selected unsigned-int8 model is now available to `IMAGE_CLASSIFY` as an
explicitly enabled, observation-only backend. Set
`MANZIL_IMAGE_CLASSIFY_ONNX_SHADOW_DIR` to the directory containing its pinned
`model.onnx` and `manifest.json`; leaving the variable unset preserves existing
behavior exactly. The API deployment must install its `vision-onnx` extra. For
a local real Listing Job from the repository root:

```bash
export MANZIL_IMAGE_CLASSIFY_ONNX_SHADOW_DIR="$PWD/worker/tests/fixtures/vision_benchmark/models/clip-vision-onnx-uint8"
uv run --package manzil-api --extra vision-onnx \
  uvicorn manzil_api.main:app --host 127.0.0.1 --port 8000 --workers 1
```

The parent starts a short-lived Python subprocess, verifies the complete
artifact digest and unsigned-int8 manifest, streams one thumbnail at a time,
and releases ONNX memory when the subprocess exits. Failures are warning logs
only and never halt or park the Job. Results cache by normalized image content
hash plus backend/artifact/threshold version and persist separately at
`property_images.vision_assessment.classification_shadow`. They do **not**
change the incumbent `classification`, image kind, deterministic target
selection, quality `VISION`, or SCORE.

Each uncached Job emits `image_classify_onnx_shadow_complete` with classified
and cached counts, subprocess wall time, throughput, child peak RSS, and the
content hashes where kitchen or diagram decisions disagree with the incumbent.
Render's service graph remains the authority for combined instance memory;
record its peak alongside this log because child RSS alone excludes the API
parent. Before promotion, collect representative real Listing Jobs containing
ordinary rooms, open-plan kitchens, diagrams, maps, blanks, logos, collages,
and rendered interiors, then review disagreement images rather than treating
incumbent agreement as ground truth.

The generated 97 MB artifact remains gitignored, so ordinary Git and no Git
LFS are still sufficient. A deployment must supply those two files from a
pinned private release/object-store asset during image construction (or copy
them from a secure build context) and set the environment variable to that
immutable directory. Do not fetch model files when a Job runs. The current
smoke Dockerfile intentionally does not invent an artifact host; production
deployment cannot be completed until that stable artifact location exists.

### Linux/Docker portability validation

The benchmark also passed in a locally built `linux/arm64` container on
2026-08-01. The image is 817 MB and uses the official PyTorch CPU wheels on
Linux; it contains neither CUDA libraries nor the downloaded datasets/model
artifacts. A Places365 quick-profile smoke run completed without a network
download at runtime, reporting 76.2% kitchen F1, 68.1 images/s, and 606 MB peak
RSS. The quick profile is a harness/portability check, not a replacement for
the full results above. A native `linux/amd64` hosting measurement remains to
be collected on the eventual target infrastructure.

Build and run the same portable check from the repository root:

```bash
docker build \
  -f worker/vision-benchmark.Dockerfile \
  -t manzil-vision-benchmark:local \
  .

docker run --rm \
  -v "$PWD/worker/tests/fixtures/vision_benchmark:/benchmark:ro" \
  -v "$PWD/worker/evals/reports:/reports" \
  manzil-vision-benchmark:local \
  --benchmark-root /benchmark \
  --profile quick \
  --model places365 \
  --device cpu \
  --batch-size 16 \
  --out /reports/vision-ml-benchmark-docker-quick.json
```

The repository records the harness, dependency lock, Dockerfile, tests, and
compact result JSON in ordinary Git. `.gitignore` and `.dockerignore` exclude
the roughly 9 GB public dataset/model directory, so Git LFS is not required.
For a future production image, package only the selected inference artifact
and its license/manifest; do not package these benchmark datasets.

### What this benchmark does not prove

MIT and CubiCasa validate room identity and Floor Plan rejection. They do not
label whether cabinets, counters, appliances, or flooring are sufficiently
visible to judge kitchen quality; nor do they cover listing maps, blanks,
logos, renderings, collages, amenity kitchens, or open-plan crops in the same
distribution as Manzil. Therefore this result selects a **shadow candidate**,
not a production backend. Promotion still requires deterministic invalid-asset
tests, a live Listing-gallery shadow run, an assessability/abstention policy,
an observed target-host shadow measurement, and the material DESIGN decision.

### What no public dataset fully supplies

The public datasets label room identity well. They generally do not label the
operational distinctions Manzil currently asks for:

- enough cabinetry, counters, and appliances visible to judge finish quality;
- full-room versus partial/detail/unusable framing;
- open-plan photos containing more than one valid room;
- Property listing maps, blank/broken assets, logos, contact cards, collages,
  and marketing graphics;
- rendered versus photographed interiors;
- whether an amenity kitchen represents a Floor Plan;
- duplicate crops across listing Sources.

Those gaps do **not** imply that Manzil must create a supervised dataset. A
pretrained open-vocabulary model can classify them from fixed text prototypes,
while deterministic checks should handle cheaply measurable cases such as
blank/near-uniform images, broken dimensions, known diagrams, and duplicates.
The important limitation is epistemic: without a matching labelled benchmark,
“assessable” scores are routing heuristics with abstention, not calibrated
probabilities.

## Status of Manzil's 294-image kit

The local kit contains 294 rows from only 10 Properties, with many duplicate
crops and many deliberately irrelevant assets such as maps and blank images.
Its nominal row count therefore overstates both visual diversity and useful
room coverage. It should not train the classifier, select the primary model, or
support a broad accuracy claim.

Retain it only for:

- a regression smoke test after collapsing content hashes and dHash duplicate
  groups;
- verifying that known local maps/blanks/diagrams do not enter quality targets;
- comparing target-set changes during shadow rollout;
- preserving examples of the exact failure modes that motivated the stage.

Its labels may be used to describe regressions, but the pretrained-only
recommendation does not depend on them. The 25 approved kitchen-quality
anchors remain a separate reference profile for the downstream 1–5 `VISION`
call; they are not classifier training data or an independent quality test.

## Options

### 1. Deterministic rules only

Use DOM context, alt/title/caption text, native plan IDs, filename patterns,
dimensions/aspect ratio, line density, OCR/text density, and the existing dHash
logic.

**Pros**

- Zero model dependency, cost, warm-up, or drift.
- Completely explainable and easy to fixture-test.
- Already strong for explicitly labeled Floor Plan diagrams and Source-local
  associations.

**Cons**

- Cannot reliably recognize an unlabeled kitchen from pixels.
- Real listing galleries frequently have weak or absent accessible text.
- Heuristics for “assessable” framing will be brittle across photography
  styles.

**Verdict:** keep as the first layer, not the whole classifier.

### 2. Generic ImageNet classifier

Run an off-the-shelf ResNet, MobileNet, or EfficientNet with its original
ImageNet head and map output labels to Manzil concepts.

**Pros**

- Small, fast, widely exportable, and easy to run on CPU.
- Mature runtimes and permissive implementations are available.

**Cons**

- ImageNet is mainly an object taxonomy, not an apartment-room routing
  taxonomy.
- “Kitchen assessable,” diagram, amenity photography, and framing do not map
  cleanly to its classes.
- A high-confidence appliance label is not the same as a full kitchen view.

**Verdict:** not recommended as a standalone model.

### 3. Places365 pretrained scene CNN

Places365 is explicitly trained for scene recognition and publishes pretrained
CNNs under CC BY. Its taxonomy includes the indoor scene concepts Manzil cares
about, making it the strongest strict “pretrained room classifier” baseline.
The [official Places365 repository](https://github.com/CSAILVision/places365)
provides models and licensing information.

**Pros**

- Directly aligned with kitchen/bathroom/bedroom/living-room recognition.
- Small ResNet variants are practical on a CPU worker.
- Fixed output tensor; no schema, hash-copying, or response-completeness
  failure.
- Easy to use as probabilities or as frozen features for a classical head.

**Cons**

- Scene identity is not the same as kitchen assessability.
- It is an older, closed taxonomy and cannot express Manzil-specific concepts
  without a head.
- It may treat open-plan kitchen/living photos as living rooms despite a usable
  kitchen being visible.
- Diagram and irrelevant handling need other signals.

**Verdict:** mandatory baseline; likely insufficient alone.

### 4. Pretrained object detector

Use a COCO-trained detector to look for ovens, refrigerators, sinks, and
microwaves, optionally combining object count/coverage with scene scores.
Ultralytics documents that its general YOLO checkpoints use the
[80-class COCO taxonomy](https://docs.ultralytics.com/models/yolov8/).

**Pros**

- Appliance evidence can rescue open-plan kitchens that a scene model calls
  “living.”
- Bounding-box area and object count can help distinguish a full view from a
  detail shot.
- Outputs are deterministic tensors.

**Cons**

- COCO lacks key concepts such as cabinets and countertops.
- A close-up refrigerator or sink can generate a false “assessable kitchen.”
- Adds a second large runtime/model and licensing review. Ultralytics' current
  software licensing includes AGPL/enterprise considerations.
- Detection is more compute than whole-image classification.

**Verdict:** a possible ensemble feature only; do not start here.

### 5. Zero-shot CLIP/SigLIP-family classifier

Encode an image and compare it with fixed text prototypes such as “a full,
well-lit apartment kitchen suitable for judging cabinets, counters, and
appliances,” “a partial kitchen detail,” “a floor plan diagram,” and negative
classes. This is a vision-language foundation model, but it is not a
generative LLM and does not produce tokens at runtime.

OpenAI's [CLIP repository](https://github.com/openai/CLIP) demonstrates
zero-shot classification via image/text embedding similarity. Google's
[SigLIP2 Base model](https://huggingface.co/google/siglip2-base-patch16-224)
is Apache-2.0 and directly supports zero-shot image classification. The
[SigLIP2 paper](https://arxiv.org/abs/2502.14786) reports improvements over
SigLIP in zero-shot classification and transfer.

**Pros**

- No task-specific labels are required to get a first result.
- Custom semantic concepts fit better than a fixed Places365 taxonomy.
- One encoder can support kitchen, diagram, irrelevant, framing, and future
  shadow categories.
- Text prototypes are versionable and cheap to experiment with.

**Cons**

- Prompt wording and competing class sets materially change scores.
- Raw similarities are not trustworthy probabilities. OpenAI's own
  [CLIP model card](https://github.com/openai/CLIP/blob/main/model-card.md)
  recommends task-specific, fixed-taxonomy testing before deployment.
- Full SigLIP2 Base artifacts are about 1.5 GB, undesirable for Manzil's small
  worker unless the image tower is exported separately.
- “Zero-shot” removes training labels, not the need for evaluation and
  threshold calibration.

**Verdict:** recommended model family. Start with SigLIP2 Base for the
accuracy-first evaluation and keep an explicit abstention path.

### 6. MobileCLIP2 encoder

Apple's [official MobileCLIP repository](https://github.com/apple/ml-mobileclip)
publishes compact contrastive image-text encoders. MobileCLIP2-S0 has an
11.4M-parameter image tower and is intended for efficient zero-shot inference.
Text embeddings for Manzil's fixed taxonomy can be computed once; production
then needs only the image tower and stored prototype vectors.

**Pros**

- Much smaller image tower than base CLIP/SigLIP alternatives.
- Custom text concepts without a generative model.
- A single image embedding can feed zero-shot prototypes, k-nearest-neighbor
  retrieval, and logistic-regression heads.
- Well suited to batches of 30 thumbnails and CPU/ONNX deployment.

**Cons**

- Apple releases model weights under its ML Research Model Terms rather than a
  standard permissive open-source model license; review and record acceptance.
- The current official integration adds PyTorch/OpenCLIP dependencies unless
  Manzil exports and pins an ONNX artifact.
- Its published general benchmarks do not establish apartment-gallery
  performance.

**Verdict:** rejected as a production candidate. The weights are licensed only
for non-commercial scientific research and academic development; the terms
explicitly exclude product development and use in a product or service. OpenAI
CLIP ViT-B/32 replaced it in the implemented comparison.

### 7. Frozen DINOv2 embeddings plus k-NN or logistic regression

Meta's [DINOv2](https://github.com/facebookresearch/dinov2) provides
self-supervised visual features designed for simple k-NN, logistic-regression,
or linear heads. The smallest published backbone is 21M parameters, and code
and general weights are Apache-2.0.

**Pros**

- Clean separation between a frozen pretrained vision model and a classical
  decision layer.
- Strong general visual features and simple training.
- Does not need text prompts or a text tower.
- Existing labels can train the heads.

**Cons**

- Without labels it has no natural mapping from embeddings to “assessable
  kitchen.”
- Ten Properties may not span enough visual diversity for a robust head.
- Larger and less semantically direct than MobileCLIP2-S0 for this task.

**Verdict:** unnecessary for the pretrained-only first pass because it needs a
task-specific mapping layer.

### 8. Frozen encoder plus classical supervised head

Extract features once with Places365, MobileCLIP2, SigLIP2, or DINOv2. Train
regularized logistic regression (or, secondarily, a linear SVM) on the existing
labels. Calibrate the probabilities with grouped folds. Scikit-learn supports
[sigmoid, isotonic, and temperature-style calibration workflows](https://scikit-learn.org/stable/api/sklearn.calibration.html).

**Pros**

- Uses the labels already paid for without fine-tuning millions of weights.
- Fast to train, deterministic, inspectable, and easy to version.
- Usually more domain-aligned than pure zero-shot prompts.
- Produces one result per image with meaningful, evaluated thresholds.
- Training can run locally on CPU after embeddings are cached.

**Cons**

- A small head can still overfit ten Properties.
- Isotonic calibration is too data-hungry here; regularized sigmoid/Platt-style
  calibration is safer.
- Every model, preprocessing, head, and threshold change requires a grouped
  bench rerun.

**Verdict:** technically viable but no longer recommended for the first pass.
The current local kit has too little independent visual diversity. Revisit only
if pretrained zero-shot and Places365 models fail in a specific, well-defined
way and an appropriate external labelled subset can train the missing concept.

### 9. Cloud computer-vision label APIs

AWS Rekognition, Google Cloud Vision, and Azure AI Vision offer pretrained,
non-LLM image labels. AWS can also return sharpness/brightness/contrast
properties in
[`DetectLabels`](https://docs.aws.amazon.com/rekognition/latest/dg/labels-detect-labels-image.html);
Google provides
[label detection](https://cloud.google.com/vision/docs/detect-labels-image-command-line);
Azure returns broad
[content tags](https://learn.microsoft.com/en-us/azure/ai-services/computer-vision/concept-tagging-images).

**Pros**

- No local model runtime or weight management.
- Mature APIs, scaling, and generic image-quality metadata.
- Fixed responses are less brittle than a generative LLM.

**Cons**

- Generic provider taxonomies still do not define “assessable kitchen.”
- Per-image network cost and latency replace the current batched call.
- Property photos leave Manzil's infrastructure.
- Provider model versions and labels can drift.
- Adds a new vendor credential and integration, contrary to NFR5 unless it
  clearly wins.

**Verdict:** inferior to local inference for this small, private workload.

### 10. Pseudo-labeling or distillation from the current LLM

Run the incumbent over many unlabeled images, train a smaller model on its
outputs, and retain human labels only for evaluation.

**Pros**

- Can cheaply expand training volume.
- May reproduce subtle incumbent judgments.

**Cons**

- Copies the incumbent's errors and uncalibrated confidence.
- The current model already has incomplete/malformed batch behavior.
- It cannot substitute for independent ground truth.
- It would still need an independently representative acceptance set.

**Verdict:** unnecessary and contrary to the pretrained-only preference.

### 11. Keep the LLM

**Pros**

- Flexible taxonomy and good semantic reasoning without training.
- The same seam already exists and is traced.
- It can produce human-readable rationales.

**Cons**

- Current candidates failed the exact batch contract.
- Per-run spend, network latency, provider dependence, and privacy exposure.
- Self-reported confidence is not calibrated.
- Output fields can contradict each other.
- Rationales add no value to deterministic routing.

**Verdict:** retain temporarily as a shadow comparator and fallback, not as the
preferred steady-state classifier.

## Recommended architecture

### Model

Start with `google/siglip2-base-patch16-224` as the accuracy-first candidate.
It is pretrained, Apache-2.0, non-generative, and can compare every image with
fixed natural-language class prototypes. The implemented benchmark uses OpenAI
CLIP ViT-B/32 as the smaller deployment candidate and Places365-ResNet18 as the
closed-taxonomy scene baseline. No candidate receives a task-specific trained
head in the first pass.

Classify hierarchically rather than asking one flat eight-way question:

1. **Asset kind**
   - interior photograph;
   - exterior photograph;
   - rendered interior;
   - Floor Plan diagram;
   - map or location screenshot;
   - logo, contact card, or marketing graphic;
   - blank, broken, or unusable image;
   - other.
2. **Visible scenes**, multi-label
   - kitchen;
   - bathroom;
   - living room;
   - bedroom;
   - dining room;
   - hallway/entry;
   - laundry;
   - amenity/common area;
   - exterior;
   - other.
3. **View usability for each enabled VISION profile**
   - assessable full view;
   - assessable partial view;
   - detail only;
   - not visible/unusable.

The hierarchy prevents a map or blank image from being forced into the nearest
room class. Multi-label scene output preserves open-plan kitchen/living images.
Profile-specific usability avoids claiming that a visible refrigerator alone
is sufficient to judge kitchen finish quality.

Use multiple fixed prompt templates per class and average their embeddings so
one phrase does not become the taxonomy. Negative prototypes are equally
important: “a close-up of one appliance,” “a living room with only a distant
glimpse of a kitchen,” and “a building-location map” should compete directly
with positive kitchen prototypes.

The pretrained model's score is a similarity score, not a calibrated
probability. Production confidence should be conservative and based on:

- winner-versus-runner-up margin;
- agreement across prompt templates;
- agreement across two deterministic image views, such as contain-fit and
  center-crop;
- optional agreement with Places365 for ordinary room scenes;
- an explicit minimum score and abstention when these signals disagree.

Do not describe this confidence as statistically calibrated without a
representative labelled set. Low-margin output becomes unknown and cannot feed
a quality target.

### Inference path

```text
normalized stored image
  -> deterministic blank/broken/known-diagram checks
  -> existing <=384 px classifier thumbnail(s)
  -> batched pretrained image encoder
  -> hierarchical fixed-prototype similarities
  -> multi-label scene + profile usability
  -> margin/agreement rules and abstention
  -> existing vision_assessment.classification envelope
  -> existing eligible_quality_images / select_kitchen_targets
```

The model should load once per worker process. Thirty images should be encoded
as one tensor batch; benchmark batch sizes against the actual Render worker's
RAM and CPU rather than assuming laptop results transfer.

An ONNX export is preferable after correctness is established. ONNX Runtime
supports static and dynamic quantization; its
[documentation](https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html)
generally recommends static quantization for CNNs and dynamic quantization for
transformer-based models. Quantization is a second step: compare predictions
and selector metrics before adopting the smaller artifact.

### Artifact and cache contract

The cache key must include at least:

- encoder name and exact weight SHA-256;
- preprocessing version, resolution, crop/contain behavior, and normalization;
- prompt/prototype text, template set, and embedding digest;
- hierarchy, class order, score aggregation, margins, and thresholds;
- optional Places365 model and agreement-policy versions;
- output-contract version.

Do not key only on a human-readable model slug. Pin the model artifact in an
immutable deployment asset or download it during image build with an expected
hash; never download mutable “latest” weights at worker startup.

Persist raw similarity/margin/agreement values and the final discrete
assessment. Raw scores make threshold changes auditable and can support a
zero-inference reselection, while the discrete result preserves the existing
consumer contract.

## Pretrained-only evaluation plan

### Candidate matrix

Run, at minimum:

1. incumbent classifier, after resolving its model-pin conflict;
2. Places365-ResNet18 direct scene scores plus deterministic rules;
3. SigLIP2 Base hierarchical zero-shot prototypes;
4. OpenAI CLIP ViT-B/32 with the exact same hierarchy and prototypes;
5. optional SigLIP2 plus Places365 agreement policy.

No model is fitted on Manzil images.

### Composite external benchmark

Use official dataset splits rather than mixing everything into one artificial
accuracy number:

- **room scenes:** MIT Indoor 67 and SUN397; optionally use LSUN's validation
  sets for kitchen/bedroom/living/dining volume;
- **residential transfer:** ZInD room panoramas, acknowledging the panorama and
  unfurnished-home domain shift;
- **Floor Plan diagrams:** CubiCasa5K positives against MIT/SUN/ZInD photograph
  negatives;
- **object/scene sanity:** optional ADE20K indoor subsets;
- **invalid assets:** deterministically generated blank, transparent,
  near-uniform, corrupt-dimension, and tiny-image fixtures;
- **listing-specific smoke:** the unique dHash clusters from Manzil's local
  kit, reported separately and never allowed to dominate the result.

Report room-class precision/recall, multi-label open-plan behavior, diagram
false-positive/false-negative rates, invalid-asset rejection, and abstention.
Do not claim a validated assessability probability: none of these external
datasets provides that label. Instead report view-usability outputs in shadow
and require the selector to abstain on low-margin cases.

### Acceptance posture

The existing guide's selector goals remain desirable:

- at least 95% precision among selected kitchen targets;
- at least 90% Property-level kitchen recall at three targets;
- zero high-confidence selections on no-kitchen galleries;
- zero selected Floor Plan diagrams;
- no duplicate target selections;
- below $0.005 classification cost per Property.

The current 294-image kit cannot establish those claims robustly. External
room and diagram datasets can establish most component behavior, while a live
shadow run establishes operational behavior. Until a representative
listing-gallery benchmark exists, the rollout must say “pretrained model with
conservative abstention,” not “bench-proven assessability.”

For a local model, there is no metered inference fee, but CPU time is not free.
Also report:

- cold model-load time and peak RSS;
- warm latency per image and per 30-image Property;
- encoder artifact size;
- abstention rate;
- room-scene precision/recall by external dataset;
- diagram precision/recall and false-positive rate;
- content-kind confusion matrix;
- results by dataset/domain rather than only pooled metrics;
- score-margin and prompt-template agreement distributions;
- selector output differences from the incumbent;
- malformed/missing output count, expected to be exactly zero.

### Shadow rollout

1. Run the local classifier and incumbent together for a bounded set of live
   Properties.
2. Persist both results under separate version keys; only the incumbent feeds
   selection initially.
3. Report disagreement rates, target-set overlap, latency, memory, and cost.
4. Inspect automatically checkable failures: selected deterministic diagrams,
   response count, duplicates, and consistency violations.
5. If the offline gates pass and shadow operations are healthy, switch the
   local model to primary and keep the LLM fallback behind a feature flag for
   one release.

Disagreement alone is not ground truth. If a new live failure mode appears,
the honest choices are conservative abstention, a deterministic exclusion, or
fallback—not declaring whichever model agrees with expectations the winner.

## What should remain an LLM for now

The anchored 1–5 `kitchen_quality` call is a different task. It judges finish
modernness relative to Owner-approved references, aggregates across selected
views, and emits an Explanation. It is subjective and directly affects points
and potentially Gates.

A non-LLM replacement is possible:

- embed targets and the 25 anchors, then use nearest-anchor or ordinal
  regression;
- train an ordinal head on the five anchor levels;
- learn pairwise ranking from “A is better than B” judgments;
- use handcrafted material/object features.

None is ready to recommend today:

- 25 anchors are a tiny, intentionally curated reference profile, not an
  independent test set;
- nearest visual similarity may follow composition, lighting, and color rather
  than finish quality;
- there is no accepted external kitchen-quality benchmark;
- the model would need an abstain rule for mixed renovations and poor views;
- a silent one-level bias changes Rubric points.

Therefore replace `IMAGE_CLASSIFY` first and leave anchored quality `VISION`
unchanged. Revisit quality only after the owed external human-rated bench
exists; then compare an ordinal frozen-embedding model against the current
anchored call on exactly that held-out set.

## Additional considerations

### Confidence and abstention

Without a representative matching benchmark, “high confidence” cannot mean a
calibrated probability. It should require a strong winner margin, prompt
ensemble agreement, deterministic-view agreement, and no conflicting
deterministic evidence. It must not mean top-1 softmax or cosine score alone.
Ambiguous open-plan rooms, renderings, collages, extreme crops, and
out-of-distribution marketing images should abstain and be excluded from
quality targets.

### Multi-label versus single-label

Open-plan apartments invalidate a mutually exclusive scene taxonomy. Kitchen
presence, assessability, diagram, irrelevant, and framing are independent
operational attributes. Hierarchical, multi-label prototype comparisons match
the selection logic better than one eight-way room classifier.

### Domain leakage and duplicates

The same staged photo commonly appears across Sources, resolutions, and crops.
Content hash catches exact bytes; dHash catches near-duplicates for selection.
The local smoke set must collapse these groups before reporting any rate.
Otherwise repeated crops make the set look larger and let one underlying image
dominate the result.

### Preprocessing parity

Training/eval and production must use the exact same EXIF orientation,
colorspace, resize, aspect handling, and normalization. The current
`classification_thumbnail` function is the natural single seam. A model
requiring cover-crops risks removing cabinets or appliances at the edge; use
the model's required transform, but compare contain/letterbox behavior in the
bench.

### Rendered interiors and collages

Listing galleries contain renderings, virtual staging, amenity kitchens,
watermarked collages, maps, and contact cards. Decide explicitly whether a
rendered kitchen may feed quality. The current schema has no
photo-versus-render distinction. That is a missing design choice, not a
threshold-tuning detail.

### Property gallery versus exact Floor Plan evidence

The model must not infer Floor Plan identity from visual similarity. Preserve
the current Source-local native/card/label association rules. A classifier
answers “is this an assessable kitchen?”; it does not answer “which Floor Plan
does this kitchen belong to?”

### Licensing

Record both code and weight licenses in the model manifest:

- Places365 pretrained models: CC BY, attribution required.
- SigLIP/SigLIP2: Apache-2.0 model release.
- DINOv2 general code/weights: Apache-2.0.
- MobileCLIP2 code: MIT; weights: Apple ML Research Model Terms.
- Ultralytics: review AGPL/enterprise terms before embedding its runtime.

For a personal tool the practical risk is low, but the deployment artifact
should still have a deliberate license decision rather than inheriting a model
hub default.

### Privacy and security

Local inference keeps Property images inside Manzil and removes one third-party
image transfer. Model files are executable supply-chain inputs in practice:
prefer `safetensors` or ONNX over arbitrary pickle checkpoints, pin hashes, and
build them into the worker image. The classifier must not gain network tools.

### Dependency and deployment cost

The repository currently uses Pillow but not PyTorch, Transformers, OpenCLIP,
ONNX Runtime, or scikit-learn in its production dependency set. Adding a full
PyTorch stack is material for image size and cold start. A sensible path is:

1. prototype/evaluate in an optional eval dependency group;
2. export the winning frozen encoder and fixed prototype vectors to ONNX;
3. add only ONNX Runtime to the production worker if the measured image/RAM
   cost is acceptable.

NFR5 requires a new moving part to replace two elsewhere or justify itself.
This change can justify itself by removing the external classifier model call,
its response-reconciliation complexity, and its provider-specific cache/cost
path.

### Observability

Langfuse's “every LLM call” rule no longer applies to a genuinely local
non-LLM inference, but observability still does. Record model/cache versions,
batch size, latency, abstentions, similarity/margin summaries, selected hashes,
and peak memory in Job events or structured logs. The deterministic selector
and quality `VISION` provenance remain unchanged.

### Rollback

Keep the classifier implementation behind an explicit backend selection during
shadowing. A rollback must invalidate only classifier cache entries, recompute
targets, and leave stored images, Floor Plan associations, quality
assessments, and Extractions intact. Never overload the existing model slug
with new weights.

## Final recommendation

Approve an evaluation task, not an immediate production flip:

> Replace generative `IMAGE_CLASSIFY` with a local frozen
> pretrained classifier using fixed, versioned prototypes for asset kind,
> multi-label room scenes, and profile-specific usability. SigLIP2 remains the
> public-data accuracy winner, but the 512 MB Render constraint selects the
> 97 MB vision-only CLIP uint8 ONNX export for the first deployable shadow
> stage. Do not train on the current 294-image kit;
> retain only its unique image clusters as a local regression smoke set. Keep
> the incumbent as a shadow/fallback during one rollout window, and keep
> anchored 1–5 kitchen-quality `VISION` unchanged.

This is the lowest-risk path to the user's actual goals: no hand-labeling
project, no recurring classification API cost, no brittle 30-record generated
schema, better privacy, and a result that remains testable and deterministic.
If no pretrained candidate clears the external component benchmarks and live
shadow checks, keep the LLM temporarily or abstain more aggressively. Do not
turn the duplicate-heavy local kit into a supervised training dependency merely
to force a replacement.
