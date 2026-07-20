"""Bench labels (P0-11, IMPLEMENTATION §5): hand-labeled ground truth.

One JSON file per bench listing at `tests/fixtures/bench/labels/{slug}.json`;
`tests/fixtures/bench/manifest.md` records which slugs were chosen and why.
Labels are **human-only** — the whole point is truth the model never produced;
tooling here only validates and scaffolds, never fills in values.

A label grades three things:
- `criteria`  — key -> the true value, validated against the catalog's
  `value_schema` (same source the extraction schema is generated from).
- `unknown`   — keys the page genuinely does not state; the model is graded
  correct only if it emitted null/not_found for them.
- `floor_plans` — the true plans (omit the field entirely to skip grading
  plans for a listing).

Keys absent from both `criteria` and `unknown` are simply not graded.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from manzil_worker.fetching.tiers import site_domain
from manzil_worker.stages.schema_gen import extractable_entries, value_adapter
from manzil_worker.state import FloorPlanIn

BENCH_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "bench"
LABELS_DIR = BENCH_DIR / "labels"

MANIFEST_HEADER = """# Bench manifest (P0-11)

One row per bench listing. ~20 rows is the Phase 0 exit gate. Labels live in
`labels/{slug}.json`; `manzil bench-skeleton <slug>` (run after `manzil
save-page`) scaffolds the label and appends this row with slug/site/tier
prefilled. Fill in the rest by hand — a blank page-traits / why / labeled cell
means the listing hasn't been vetted for its slot yet.

Labeling rules (learned the hard way):

1. **Label page truth, never world truth or hunt truth.** If the page states
   it, that's the value — even when it's stale (a past availability date) or
   irrelevant to the rubric. The bench grades extraction fidelity, not rubric
   fit; plan-vs-rubric matching happens later, in SCORE's floor-plan overlay.
2. **Multi-plan page → delete `beds`/`baths`/`sqft` from `criteria`.** There
   is no single property-level truth for unit-scoped fields when plans span
   studio→3BR; their ground truth lives in `floor_plans`. Keep those keys only
   for single-unit listings.
3. **`availability_date` = earliest stated date for that scope** (property
   level: earliest across the target Property's plans; plan level: earliest
   for that plan). If the target Property/Floor Plan has an explicit
   availability date in prose or `[EMBEDDED DATA]`, label that ISO date even
   when the UI also says Available Now / Now / Immediately. Label the
   sentinel `"available_now"` only for phrase-only immediate wording with no
   explicit availability date at that scope — the harness resolves it to the
   UTC date of that listing's corpus `meta.json` `saved_at`, never invent a
   calendar date in the label. Delete the key if the page states no
   availability at all.

Column guide:

- **site** — source domain (rent.com, apartmentguide.com, official property site…).
  The bench should span several templates, not 20 copies of one.
- **tier** — fetch tier the page needed when saved (from `corpus/{slug}/meta.json`).
- **page traits** — what's structurally distinctive: fee-table style (inline /
  tabular / PDF-ish), sparse page, hostile formatting, many floor plans, promo
  banners, missing amenities section…
- **why it earned a slot** — the failure mode or coverage gap this listing
  exercises that no other row already covers.
- **labeled** — date the human label in `labels/{slug}.json` was finished
  (blank = skeleton only, still full of nulls).

| slug | site | tier | page traits | why it earned a slot | labeled |
|---|---|---|---|---|---|
"""


class LabelError(ValueError):
    """A label file that cannot be trusted must never grade a bench run."""


class BenchLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str
    url: str
    labeled_at: date | None = None  # None marks an unfinished skeleton
    notes: str = ""
    criteria: dict[str, Any] = Field(default_factory=dict)
    unknown: list[str] = Field(default_factory=list)
    floor_plans: list[FloorPlanIn] | None = None  # None = don't grade plans

    def graded_keys(self) -> set[str]:
        return set(self.criteria) | set(self.unknown)


def validate_label(label: BenchLabel) -> None:
    """Catalog conformance: unknown keys, out-of-schema values, and
    criteria/unknown overlap all fail loudly — a typo'd label silently
    mis-grading the bench is the failure mode this guards against."""
    entries = {e.key: e for e in extractable_entries()}
    problems: list[str] = []

    for key in sorted(set(label.criteria) - set(entries)):
        problems.append(f"criteria key {key!r} is not an extractable catalog key")
    for key in sorted(set(label.unknown) - set(entries)):
        problems.append(f"unknown key {key!r} is not an extractable catalog key")
    for key in sorted(set(label.criteria) & set(label.unknown)):
        problems.append(f"key {key!r} is in both criteria and unknown — pick one")

    for key, value in label.criteria.items():
        if key not in entries:
            continue
        if value is None:
            problems.append(
                f"criteria.{key} is null — fill in the true value, move the key "
                "to `unknown`, or delete it (absent = not graded)"
            )
            continue
        try:
            value_adapter(entries[key]).validate_python(value)
        except ValidationError as error:
            first = error.errors()[0]["msg"]
            problems.append(f"criteria.{key} = {value!r} violates the catalog schema: {first}")

    if problems:
        raise LabelError(f"label {label.slug!r}: " + "; ".join(problems))


def load_label(path: Path) -> BenchLabel:
    try:
        label = BenchLabel.model_validate(json.loads(path.read_text()))
    except (json.JSONDecodeError, ValidationError) as error:
        raise LabelError(f"label file {path.name}: {error}") from error
    validate_label(label)
    return label


def load_labels(slugs: list[str] = [], labels_dir: Path = LABELS_DIR) -> list[BenchLabel]:
    if not labels_dir.is_dir():
        return []
    return [load_label(path) for path in sorted(labels_dir.glob("*.json")) if (not slugs or path.stem in slugs)]


def skeleton_payload(slug: str, url: str) -> dict[str, Any]:
    """A label file pre-filled with every extractable key set to null, so
    labeling is fill-in-the-blanks. The loader rejects nulls — a skeleton can
    never silently pass as a finished label."""
    return {
        "slug": slug,
        "url": url,
        "labeled_at": None,
        "notes": "",
        "criteria": {entry.key: None for entry in extractable_entries()},
        "unknown": [],
        "floor_plans": [FloorPlanIn().model_dump()],
    }


def add_manifest_row(manifest_path: Path, slug: str, meta: dict[str, Any]) -> bool:
    """Append a manifest row for the slug — slug/site/tier prefilled from the
    corpus meta, the page-traits / why / labeled columns left blank for the
    human. Creates the manifest from the header if absent. Idempotent: an
    existing row for the slug is left untouched, so hand-filled columns survive a
    `--force` re-scaffold. Returns True iff a row was added."""
    body = manifest_path.read_text() if manifest_path.exists() else MANIFEST_HEADER
    if any(line.startswith(f"| {slug} |") for line in body.splitlines()):
        return False
    site, tier = site_domain(meta["url"]), meta.get("tier", "")
    if not body.endswith("\n"):
        body += "\n"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(f"{body}| {slug} | {site} | {tier} | | | |\n")
    return True


def write_skeleton(
    slug: str,
    *,
    corpus_dir: Path,
    labels_dir: Path = LABELS_DIR,
    force: bool = False,
) -> Path:
    """Scaffold labels/{slug}.json from a saved corpus page's meta.json and add a
    manifest.md row (slug/site/tier prefilled) for the slug."""
    meta_path = corpus_dir / slug / "meta.json"
    if not meta_path.exists():
        raise LabelError(
            f"no corpus page at {corpus_dir / slug} — save it first with `manzil save-page`"
        )
    out = labels_dir / f"{slug}.json"
    if out.exists() and not force:
        raise LabelError(f"{out} already exists — pass --force to overwrite it")
    meta = json.loads(meta_path.read_text())
    labels_dir.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(skeleton_payload(slug, meta["url"]), indent=2) + "\n")
    add_manifest_row(labels_dir.parent / "manifest.md", slug, meta)
    return out
