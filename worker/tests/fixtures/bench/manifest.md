# Bench manifest (P0-11)

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
3. **`availability_date` = the earliest date the page states** (property level:
   earliest across plans; plan level: earliest for that plan). Never today's
   date. Delete the key if the page states no dates.

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
