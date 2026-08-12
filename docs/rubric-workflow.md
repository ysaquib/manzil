# Rubric creation workflow (deferred feature)

**Status: not started.** Written up here per Yusuf's request while designing the
[hunt creation flow](#relationship-to-hunt-creation) so the idea has a home
before work begins. Nothing in this document authorizes implementation — it
still needs a DESIGN.md §20 Decision Log entry and in-place §9.2 updates
before any of it is built, per AGENTS.md's rule on material design changes.

## Problem

Building a Rubric today means the single-page `RubricEditor` (P1-12): every
Catalog Criterion listed, each toggled on/off, each with its own ordered
Option list and deltas typed in by hand. That is the correct **advanced**
surface for someone who already knows exactly what they want scored and how —
but it is a cold start for someone who has never assigned point values to
"in-unit laundry" versus "covered parking" before, and it is the first thing
`CreateRubricPrompt` drops every new hunt owner into.

## Proposal

Split Rubric creation into two entry modes, chosen up front:

1. **Assisted mode** — a short series of questions ("how much do you care
   about X?") converted algorithmically into a tailored Rubric: which
   Catalog Criteria to enable, sensible Option deltas, and candidate Gates
   (non-negotiables/dealbreakers) for anything answered as a hard requirement.
2. **Advanced mode** — exactly today's `RubricEditor`, unchanged. Full manual
   control over every Criterion, Option, delta, and Gate.

Both modes write to the same `rubric_criteria` rows through the same save
path (§9.2) — assisted mode is a generator that produces the same shape
advanced mode edits directly, not a parallel data model. A Rubric built
one way is always readable and editable the other way.

Critically, the choice is never one-way:

- **Retake the quiz** — re-answer assisted mode's questions at any time. This
  needs a decision (below) on whether it replaces the current Rubric outright
  or merges with manual edits made since the last time it ran.
- **Manual edit at any time** — a Rubric produced by the quiz is a normal
  Rubric the moment it's saved; nothing marks its rows as quiz-owned or
  locks them against `RubricEditor`.

## Assisted mode — sketch

Not designed in detail yet; the shape below is a starting point for the
eventual DESIGN.md write-up, not a spec.

- One screen per Catalog category (unit, fittings, tenancy, cost, location,
  management, property), each asking how much the hunt cares about the
  Criteria in it — likely a simple intensity scale ("don't care" → "must
  have") rather than raw delta entry.
- "Must have" answers become candidate Gates: a non-negotiable when the
  Criterion has an obvious acceptable/unacceptable split (pets policy,
  parking), surfaced for confirmation rather than applied silently, since a
  Gate can zero out a listing's score.
- Answers translate to Option deltas using each Criterion's existing
  `default_options` (§8.2 Catalog) as the starting curve, scaled by the
  stated intensity — reusing data that already exists rather than inventing
  a second scoring vocabulary.
- Skippable per-category and resumable, same as the hunt creation stepper —
  a quiz that can't be abandoned partway through will train people to avoid
  starting it.
- Custom Criteria (§9.2) are out of scope for the quiz itself: they have no
  catalog default curve to scale from, so they stay a `RubricEditor`-only
  concern even for a hunt built entirely in assisted mode.

## Open questions (to resolve before a §20 entry)

- **Retake semantics.** Does retaking the quiz overwrite every quiz-derived
  answer, or attempt to preserve manual edits made in between? Overwriting
  everything is far simpler and matches "the quiz is a generator," but a
  hunt owner who tweaked three deltas by hand after the first quiz run may
  not expect a retake to discard them silently.
- **Where Gates come from.** Should the quiz ever set a non-negotiable or
  dealbreaker without an explicit separate confirmation step, given a firing
  Gate collapses a listing's score to the gate's `set_score` (§9.3)?
- **Granularity of the intensity scale.** A 3-point scale ("skip it",
  "nice to have", "must have") is simplest to build and explain; a 5-point
  scale gives the generator more room to differentiate deltas but asks more
  of the user per Criterion.
- **Re-scoring cost.** Any Rubric save already takes the free bump-and-rescore
  path (§9.2). A multi-category quiz that saves once at the end versus
  progressively per category is a UX choice, not a cost one — worth deciding
  based on whether partial quiz progress should be visible as a live Rubric.
- **Where "Advanced mode" lives relative to "Assisted mode."** A single
  entry screen with two large choices, or advanced mode framed as an escape
  hatch reachable from inside the quiz ("skip the rest, edit manually")?

## Relationship to hunt creation

The [hunt creation flow](#status-not-started) proposal deliberately excludes
all Rubric decisions — no questions about criteria, weights, or Gates appear
in that stepper. `CreateRubricPrompt` already exists as the decoupled nudge
that offers Rubric setup once a hunt has zero enabled Criteria, independent
of how the hunt itself was created; this workflow is what that prompt should
eventually lead into (mode-choice screen, instead of landing directly in
`RubricEditor` as it does today).

## Non-goals (for this document)

- Per-member weighted rubrics — already rejected in DESIGN §18/§20.
- Anything touching Custom Criteria's acquisition/routing logic (§9.2) —
  the quiz consumes existing Catalog Criteria only.
- Any change to the scoring engine (`shared/`) itself. This is entirely a
  Rubric-authoring UX layer on top of the existing pinned rubric-option
  shape (§8.2) and scoring contract (§9.3); neither is touched.
