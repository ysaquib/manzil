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

from manzil_shared.catalog import MULTI_CLAIM_IDENTITY_KEYS, P3_SC6_KEYS, SCOPED_UNIT_CLAIM_KEYS
from manzil_shared.models import UnitApplicability
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from manzil_worker.fetching.tiers import site_domain
from manzil_worker.stages.schema_gen import extractable_entries, value_adapter
from manzil_worker.state import FloorPlanIn

BENCH_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "bench"
LABELS_DIR = BENCH_DIR / "labels"
SCOPED_BENCH_CLAIM_KEYS = SCOPED_UNIT_CLAIM_KEYS | {"heating_type"}

MANIFEST_HEADER = """# Bench manifest (P0-11)

One row per bench listing. Exactly 10 reviewed rows is the current canonical set. Labels live in
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
4. **Scoped unit features live in `scoped_claims`, not `criteria`.** Use exact
   response-local Floor Plan refs only when the page itself makes the
   association; generic lists are `unit_scope_unspecified`, explicit
   “select/some units” language is `select_units`, and `all_units` requires an
   explicit universal statement. Empty lists mean the page is silent.
5. The canonical ten together must cover exact/all/select/unspecified,
   explicit negative, missing, one shared multi-plan claim, and both ambiguous
   and unambiguous diagram cases. Run `manzil bench-audit-scoped` before a
   baseline; zero wrong exact associations is the acceptance gate.

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


class IncompleteLabelError(LabelError):
    """An unfinished skeleton — null/empty values, not a trust failure. bench-run
    warns and skips these; every other LabelError still fails the run loudly."""


class ScopedClaimLabel(BaseModel):
    """Human truth for one sparse unit claim before persistence expansion."""

    model_config = ConfigDict(extra="forbid")

    value: Any
    applicability: UnitApplicability
    floor_plan_refs: list[str] = Field(default_factory=list)


class DiagramAssociationLabel(BaseModel):
    """P3-SC5-ready human truth for a discovered diagram candidate.

    P3-SC4 records the label contract only; diagram discovery/association is
    still deferred to P3-SC5.
    """

    model_config = ConfigDict(extra="forbid")

    candidate_ref: str
    floor_plan_refs: list[str] = Field(default_factory=list)
    ambiguous: bool = False


class BenchLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str
    url: str
    labeled_at: date | None = None  # None marks an unfinished skeleton
    notes: str = ""
    criteria: dict[str, Any] = Field(default_factory=dict)
    unknown: list[str] = Field(default_factory=list)
    floor_plans: list[FloorPlanIn] | None = None  # None = don't grade plans
    scoped_claims: dict[str, list[ScopedClaimLabel]] = Field(default_factory=dict)
    diagram_associations: list[DiagramAssociationLabel] | None = None

    def graded_keys(self) -> set[str]:
        return set(self.criteria) | set(self.unknown) | set(self.scoped_claims)


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
    for key in sorted(set(label.scoped_claims) - SCOPED_BENCH_CLAIM_KEYS):
        problems.append(f"scoped_claims key {key!r} is not in the P3-SC4 scoped tranche")
    for key in sorted(set(label.scoped_claims) & (set(label.criteria) | set(label.unknown))):
        problems.append(f"key {key!r} is graded in both scoped_claims and criteria/unknown")

    for key, value in label.criteria.items():
        if key not in entries:
            continue
        if value is None:
            continue  # null = unfinished skeleton — caught by incomplete_reasons, not a trust bug
        try:
            value_adapter(entries[key]).validate_python(value)
        except ValidationError as error:
            first = error.errors()[0]["msg"]
            problems.append(f"criteria.{key} = {value!r} violates the catalog schema: {first}")

    plan_refs = {
        plan.response_key for plan in (label.floor_plans or []) if plan.response_key is not None
    }
    entries = {e.key: e for e in extractable_entries()}
    for key, claims in label.scoped_claims.items():
        entry = entries.get(key)
        if entry is None and key != "heating_type":
            continue
        # Parity with schema_gen._validate_scoped_refs: multi-claim keys allow
        # distinct values at the same target; boolean keys allow one per target.
        multi_claim = key in MULTI_CLAIM_IDENTITY_KEYS
        seen_targets: set[str | None] = set()
        seen_identities: set[tuple[str | None, str]] = set()
        values_by_target: dict[str | None, set[str]] = {}
        for index, claim in enumerate(claims):
            if key == "heating_type":
                if claim.value not in {"gas", "electric"}:
                    problems.append(
                        f"scoped_claims.{key}[{index}].value = {claim.value!r} "
                        "must be gas or electric"
                    )
            else:
                try:
                    value_adapter(entry).validate_python(claim.value)
                except ValidationError as error:
                    first = error.errors()[0]["msg"]
                    problems.append(
                        f"scoped_claims.{key}[{index}].value = {claim.value!r} "
                        f"violates the claim schema: {first}"
                    )
            exact = claim.applicability is UnitApplicability.SPECIFIC_FLOOR_PLANS
            if exact and not claim.floor_plan_refs:
                problems.append(f"scoped_claims.{key}[{index}] exact claim needs floor_plan_refs")
            if not exact and claim.floor_plan_refs:
                problems.append(
                    f"scoped_claims.{key}[{index}] non-exact claim cannot name Floor Plans"
                )
            unknown_refs = set(claim.floor_plan_refs) - plan_refs
            if unknown_refs:
                problems.append(
                    f"scoped_claims.{key}[{index}] references unknown label Floor Plans "
                    f"{sorted(unknown_refs)}"
                )
            targets: list[str | None] = claim.floor_plan_refs or [None]
            value_key = json.dumps(claim.value, sort_keys=True, separators=(",", ":"))
            if multi_claim:
                identities = {(target, value_key) for target in targets}
                duplicates = seen_identities.intersection(identities)
                if duplicates:
                    rendered = ", ".join(
                        "generalized scope" if ref is None else ref for ref, _ in duplicates
                    )
                    problems.append(
                        f"scoped_claims.{key}[{index}] duplicates the same value for "
                        f"concrete target(s): {rendered}"
                    )
                for target in targets:
                    existing_values = values_by_target.setdefault(target, set())
                    none_key = json.dumps("none")
                    if claim.value == "none" and any(
                        value != none_key for value in existing_values
                    ):
                        problems.append(
                            f"scoped_claims.{key}[{index}] none cannot coexist with a "
                            "positive value at the same concrete target"
                        )
                    if claim.value != "none" and none_key in existing_values:
                        problems.append(
                            f"scoped_claims.{key}[{index}] positive value cannot coexist "
                            "with none at the same concrete target"
                        )
                    existing_values.add(value_key)
                seen_identities.update(identities)
            else:
                duplicates = seen_targets.intersection(targets)
                if duplicates:
                    problems.append(
                        f"scoped_claims.{key}[{index}] duplicates a concrete claim target"
                    )
                seen_targets.update(targets)

    for association in label.diagram_associations or []:
        if association.ambiguous and association.floor_plan_refs:
            problems.append(
                f"diagram {association.candidate_ref!r} is ambiguous but has Floor Plan targets"
            )
        unknown_refs = set(association.floor_plan_refs) - plan_refs
        if unknown_refs:
            problems.append(
                f"diagram {association.candidate_ref!r} references unknown label Floor Plans "
                f"{sorted(unknown_refs)}"
            )

    if problems:
        raise LabelError(f"label {label.slug!r}: " + "; ".join(problems))


def incomplete_reasons(label: BenchLabel) -> list[str]:
    """Null/empty markers of an unfinished skeleton (vs gradeable ground truth):
    a null `labeled_at` (the schema's own skeleton marker) or any null `criteria`
    value. A finished label has neither; bench-run warns and skips the rest."""
    reasons: list[str] = []
    if label.labeled_at is None:
        reasons.append("labeled_at is null (unfinished skeleton)")
    reasons += [
        f"criteria.{key} is null" for key in sorted(label.criteria) if label.criteria[key] is None
    ]
    return reasons


def parse_label_file(path: Path) -> BenchLabel:
    try:
        return BenchLabel.model_validate(json.loads(path.read_text()))
    except (json.JSONDecodeError, ValidationError) as error:
        raise LabelError(f"label file {path.name}: {error}") from error


def validate_labels(labels: list[BenchLabel]) -> None:
    """Trust-check every label before a bench run spends tokens."""
    for label in labels:
        validate_label(label)


def load_label(path: Path) -> BenchLabel:
    label = parse_label_file(path)
    validate_label(label)  # trust checks — a typo'd label fails loudly
    reasons = incomplete_reasons(label)
    if reasons:
        raise IncompleteLabelError(f"label {label.slug!r}: " + "; ".join(reasons))
    return label


def load_labels(slugs: list[str] | None = None, labels_dir: Path = LABELS_DIR) -> list[BenchLabel]:
    if not labels_dir.is_dir():
        return []
    return [
        load_label(path)
        for path in sorted(labels_dir.glob("*.json"))
        if not slugs or path.stem in slugs
    ]


class SkippedLabel(BaseModel):
    """A bench label bench-run left out because it is an unfinished skeleton."""

    slug: str
    reason: str


SCOPED_COVERAGE_CASES = (
    "exact",
    "all_units",
    "select_units",
    "unit_scope_unspecified",
    "negative",
    "missing",
    "shared_plan",
    "diagram_ambiguous",
    "diagram_unambiguous",
)


def scoped_coverage_audit(labels: list[BenchLabel]) -> dict[str, list[str]]:
    """Return canonical-bench coverage with the contributing label slugs.

    This audits human labels only; it never infers truth from model output.
    """
    coverage = {case: [] for case in SCOPED_COVERAGE_CASES}
    for label in labels:
        claims = [claim for rows in label.scoped_claims.values() for claim in rows]
        applicability = {claim.applicability for claim in claims}
        if UnitApplicability.SPECIFIC_FLOOR_PLANS in applicability:
            coverage["exact"].append(label.slug)
        if UnitApplicability.ALL_UNITS in applicability:
            coverage["all_units"].append(label.slug)
        if UnitApplicability.SELECT_UNITS in applicability:
            coverage["select_units"].append(label.slug)
        if UnitApplicability.UNIT_SCOPE_UNSPECIFIED in applicability:
            coverage["unit_scope_unspecified"].append(label.slug)
        if any(claim.value is False or claim.value == "none" for claim in claims):
            coverage["negative"].append(label.slug)
        if any(not rows for rows in label.scoped_claims.values()):
            coverage["missing"].append(label.slug)
        if any(len(claim.floor_plan_refs) > 1 for claim in claims):
            coverage["shared_plan"].append(label.slug)
        diagrams = label.diagram_associations or []
        if any(diagram.ambiguous for diagram in diagrams):
            coverage["diagram_ambiguous"].append(label.slug)
        if any(not diagram.ambiguous and diagram.floor_plan_refs for diagram in diagrams):
            coverage["diagram_unambiguous"].append(label.slug)
    return coverage


TRANCHE_COVERAGE_CASES = (
    "positive",
    "negative",
    "exact",
    "all_units",
    "select_units",
    "unit_scope_unspecified",
    "missing",
)
SC6_REQUIRED_COVERAGE = (
    "positive",
    "negative",
    "select_units",
    "unit_scope_unspecified",
    "missing",
)
SC7_REQUIRED_COVERAGE = (
    "positive",
    "exact",
    "all_units",
    "select_units",
    "unit_scope_unspecified",
    "missing",
)


def scoped_tranche_coverage_audit(
    labels: list[BenchLabel],
) -> dict[str, dict[str, list[str]]]:
    """Per-Criterion human coverage for P3-SC6/SC7 accuracy claims."""
    keys = sorted(P3_SC6_KEYS | {"flooring_materials"})
    coverage = {key: {case: [] for case in TRANCHE_COVERAGE_CASES} for key in keys}
    for label in labels:
        for key in keys:
            if key not in label.scoped_claims:
                continue
            claims = label.scoped_claims[key]
            if not claims:
                coverage[key]["missing"].append(label.slug)
                continue
            if any(claim.value is True or isinstance(claim.value, list) for claim in claims):
                coverage[key]["positive"].append(label.slug)
            if any(claim.value is False or claim.value == "none" for claim in claims):
                coverage[key]["negative"].append(label.slug)
            for applicability, case in (
                (UnitApplicability.SPECIFIC_FLOOR_PLANS, "exact"),
                (UnitApplicability.ALL_UNITS, "all_units"),
                (UnitApplicability.SELECT_UNITS, "select_units"),
                (UnitApplicability.UNIT_SCOPE_UNSPECIFIED, "unit_scope_unspecified"),
            ):
                if any(claim.applicability is applicability for claim in claims):
                    coverage[key][case].append(label.slug)
    return coverage


def load_labels_split(
    slugs: list[str] | None = None, labels_dir: Path = LABELS_DIR
) -> tuple[list[BenchLabel], list[SkippedLabel]]:
    """Load labels for a bench run, partitioning unfinished skeletons (null/empty
    values) out as `skipped` instead of aborting. Genuinely broken labels — bad
    JSON, non-catalog keys, schema violations, criteria/unknown overlap — still
    raise LabelError so a typo can never silently mis-grade the bench.

    Every matching label file is trust-validated before any gradeable label is
    returned, so one broken file late in the directory cannot leave earlier
    labels half-loaded while the run is already underway."""
    loaded: list[BenchLabel] = []
    skipped: list[SkippedLabel] = []
    if not labels_dir.is_dir():
        return loaded, skipped
    paths = [path for path in sorted(labels_dir.glob("*.json")) if not slugs or path.stem in slugs]
    parsed: list[tuple[Path, BenchLabel]] = []
    problems: list[str] = []
    for path in paths:
        try:
            label = parse_label_file(path)
        except LabelError as error:
            problems.append(str(error))
            continue
        try:
            validate_label(label)
        except LabelError as error:
            problems.append(str(error))
            continue
        parsed.append((path, label))
    if problems:
        raise LabelError("; ".join(problems))

    for path, label in parsed:
        reasons = incomplete_reasons(label)
        if reasons:
            skipped.append(
                SkippedLabel(
                    slug=path.stem,
                    reason=f"label {label.slug!r}: " + "; ".join(reasons),
                )
            )
        else:
            loaded.append(label)
    return loaded, skipped


def skeleton_payload(slug: str, url: str) -> dict[str, Any]:
    """A label file pre-filled with every extractable key set to null, so
    labeling is fill-in-the-blanks. The loader rejects nulls — a skeleton can
    never silently pass as a finished label."""
    return {
        "slug": slug,
        "url": url,
        "labeled_at": None,
        "notes": "",
        "criteria": {
            entry.key: None
            for entry in extractable_entries()
            if entry.key not in SCOPED_UNIT_CLAIM_KEYS
        },
        "unknown": [],
        "floor_plans": [FloorPlanIn().model_dump()],
        "scoped_claims": {key: [] for key in sorted(SCOPED_BENCH_CLAIM_KEYS)},
        "diagram_associations": None,
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
