# Floor-plan unit/category nesting in the cleaner — design

**Date:** 2026-07-20
**Area:** `worker/src/manzil_worker/fetching/cleaner.py` (P0-5, DESIGN §7)
**Status:** approved (design), pending implementation plan

## Problem

On apartments.com listing pages, the cleaned text lists each available unit with
its price, sqft, and availability, but **drops the unit's category** — the
floor-plan name (`Studio, 1 Bath Deluxe`) and the beds/baths (`Studio 1 Bath`).

### Root cause (verified)

Each floor-plan card (`div.pricingGridItem`) contains two **sibling** regions:

1. **Model header** (`div.priceGridModelWrapper`) — the category: floor-plan
   name, rent range, and the `beds / baths / sqft` summary. Built from nested
   `<div>`/`<span>` with low text-and-link density.
2. **Unit grid** (`div.unitGridContainer` → `<ul>`) — one row per available unit
   (`Unit 03-205 price $1,320 square feet 625 availibility Now`).

`trafilatura(favor_recall=True)` keeps the `<ul>` unit rows but prunes the
model-header wrapper as boilerplate. The result: units with price/sqft/
availability but no beds/baths and no plan name.

The category is not literally absent from the document — the existing
`_floor_plan_lines` guard recovers the headers into the bottom `[FLOOR PLANS]`
block, and `[EMBEDDED DATA]` JSON-LD carries per-unit beds/baths. **But both are
structurally decoupled from the unit grid.** The guard deliberately stops at the
header wrapper (`priceGridModelWrapper`, no units), so nothing ties
`Unit 03-205` to `Studio, 1 Bath Deluxe`. An LLM must guess the unit→category
mapping from sqft overlap alone. That severed association is the bug.

This is the general pattern the module docstring already anticipates (lines
13–18): a summary card whose header a generic extractor drops while the unit
list survives. The current guard solves "name missing," not "units orphaned
from their category."

## Goal

Re-associate each unit with its floor-plan category in the cleaned text, using a
**general structural mechanism** — not apartments.com-specific class names, and
not a new "apartments.com cleaner."

## Non-goals

- No change to any pipeline stage other than the cleaner's floor-plan guard.
- No field-level parsing of the header into `name | beds | sqft | rent` columns
  (that would require site-specific sub-element knowledge). The value is the
  **association (grouping)**, carried by order + indentation, not by column
  formatting.
- No use of `[EMBEDDED DATA]` JSON-LD to reconstruct the mapping (structural
  nesting solves it without depending on JSON-LD being present).
- Not suppressing trafilatura's flat unit list (the "replace" option was
  rejected — removing content mid-document risks collateral damage elsewhere).

## Approach

Extend `_floor_plan_lines()` — the existing floor-plan retention guard — so that
when a matched card contains distinct unit rows, it emits the header line with
each unit row indented beneath it, appended under the existing `[FLOOR PLANS]`
marker.

### Output shape

```
[FLOOR PLANS]
Studio, 1 Bath Deluxe $1,290 – $1,320 Studio 1 Bath 625 Sq Ft
  Unit 03-205 price $1,320 square feet 625 availibility Now
  Unit 02-203 price $1,290 square feet 625 availibility Sep 7
One Bedroom Deluxe $1,395 – $1,485 1 Bed 1 Bath 775 Sq Ft
  Unit 04-102 price $1,420 square feet 775 availibility Now
  ...
```

The header line is the existing concatenated summary (`_text_without_actions` of
the header region). Unit rows are indented by two spaces. The main
"Pricing & Floor Plans" flat unit list produced by trafilatura is left
untouched above this section.

### Mechanism

For each name-hint element (unchanged: `_PLAN_NAME_HINT` on `class`/`id`):

1. As today, walk up to `header_ctx` — the first ancestor whose compact text has
   a price/rent-status **and** a floor-plan fact. This is the header summary.
2. **Continue** the walk to find `card` — the **smallest** ancestor of
   `header_ctx` that additionally contains ≥1 **unit row** (defined below).
3. Emit: `header summary` line, then each unit row indented beneath it.
4. If no `card` with unit rows is found, emit **header-only** — exactly today's
   behavior (covers single-unit cards).

**Unit row (general definition, no site-specific classes):** a descendant of
`card`, **outside `header_ctx`**, whose compact text (`_text_without_actions`)
contains a price token or a rent-status (`Call for Rent` / `Not Available`).
Prefer `<li>`/`<tr>` descendants; fall back to elements whose text matches a
`Unit …` pattern. Deduplicate unit rows within a block (apartments.com repeats
its unit list).

### Guardrails against over-capture / mis-association

This is the load-bearing safety section. The danger is climbing past the single
card into a container that wraps **all** floor-plan cards (e.g. the existing
test's `<div class="floorplans">`), which would pin one header's beds/baths onto
another plan's units.

1. **Stop at the smallest ancestor that adds ≥1 unit row.** Never keep climbing
   once unit rows appear.
2. **Abort nesting (fall back to header-only) if the chosen ancestor contains
   more than one name-hint element.** More than one plan name in scope means a
   multi-card container — units cannot be safely attributed to a single plan.
3. **Per-block unit dedup** to collapse repeated unit rows.

### Append gate (unchanged)

Append a block only when the plan `name` is absent from the main extracted text
(current behavior). If the name is already present, the card survived extraction
intact and needs no re-append. Dedup emitted blocks by `(name, header summary)`
to collapse apartments.com's duplicated mobile/desktop card subtrees.

### Backward compatibility / blast radius

- Only cards that match a name-hint class/id **and** contain nested unit rows
  change — they gain indented unit lines.
- Sites with no name-hint structure produce no cards → byte-identical output.
- Single-unit cards and cards where the multi-card guardrail trips render
  header-only, exactly as today.
- **Cost:** unit lines are duplicated (flat list + nested block), roughly
  doubling unit lines in the output for affected pages. Accepted.

## Testing

- **Update** `FLOOR_PLAN_CARD_HTML` tests in `test_cleaner.py`:
  - The multi-unit cards ("The Birch", "The Cedar") now nest their `Unit …`
    span under the header; assert the indented unit line appears after its
    header and that header-only assertions still hold.
  - Single-unit "The Dogwood" stays header-only.
  - Add a multi-card-container case (cards wrapped in one `<div>` with the unit
    rows ambiguous) that asserts the guardrail falls back to header-only rather
    than mis-associating.
- **Add** a real-fixture test on
  `worker/tests/fixtures/corpus/apartments.com--village-of-canton/raw.html`:
  assert a `Studio 1 Bath` header block contains `Unit 03-205`, and a
  `2 Beds 2 Baths` header block contains `Unit 09-205`.
- **Regression sweep:** run `clean_html` over all 35 corpus fixtures — assert no
  exceptions, and that fixtures with no name-hint cards are unchanged.
- **Regenerate** the committed `cleaned.txt` for affected apartments.com
  fixtures and eyeball the diff.
- **Docstring** (cleaner.py lines 13–18) updated to describe unit nesting.

## Files touched

- `worker/src/manzil_worker/fetching/cleaner.py` — `_floor_plan_lines` +
  docstring.
- `worker/tests/test_cleaner.py` — updated + new tests.
- `worker/tests/fixtures/corpus/apartments.com--*/cleaned.txt` — regenerated.
