# Catalog and starter-Rubric review

Status: **resolved supplementary review, 2026-07-21**. This document preserves
the original inventory and proposals; it is not current design authority. The
approved decisions, including renamed keys and deferred items that supersede
parts of the tables below, live in `DESIGN.md` v3.7 (§8.2 and §20). Selected
mechanics and task status live in `IMPLEMENTATION.md`; detailed rationale lives
in `docs/scoped-criteria-and-amenities.md`.

## 1. What is being classified

Three separate concepts should not be collapsed into one:

- **Criterion category** controls how a Criterion is grouped in the Rubric UI.
  The current vocabulary is `unit`, `policy`, `cost`, `availability`,
  `condition`, `location`, and `reputation`.
- **Fact scope** says what the fact describes: a Property, a Floor Plan/unit,
  either depending on the listing, or a composed Hunt-specific value.
- **Starter posture** says whether a new Hunt should enable the Criterion. It
  does not decide whether the Criterion belongs in the catalog.

The proposal adds `property` as a Criterion category for shared amenities and
services. This is cleaner than putting a pool, clubhouse, or management office
under `unit`. It is a material design change to review; it is not yet a change
to `CriterionCategory` or the database constraint.

Recommended starter-posture vocabulary:

- **Core** — enabled after collecting a Hunt-specific target during setup.
- **Conditional** — enabled only when a setup answer makes it relevant.
- **Opt-in** — available in the catalog, disabled initially.
- **Hold** — do not implement until the named modeling or evidence issue is
  resolved.

No starter Criterion should silently become a Gate. Gates should require an
explicit Owner confirmation because an unknown value fails a non-negotiable.
Starter `unknown_delta` should remain `0` unless the Owner changes it.

## 2. Existing catalog inventory

These are the current 19 Catalog Entries, reorganized by fact scope. This table
does not propose changing their keys or value schemas.

| Key | Current category | Fact scope | Starter posture | Notes |
|---|---|---|---|---|
| `beds` | unit | Floor Plan | Core | Seed from the Hunt's desired bedroom count, not the catalog's hard-coded 2-bedroom example. |
| `baths` | unit | Floor Plan | Conditional | Enable after the Owner supplies a preferred/minimum count. |
| `sqft` | unit | Floor Plan | Conditional | Conservative `sqft_min` overlay already exists. |
| `patio_balcony` | unit | Floor Plan/unit | Opt-in | Private outdoor space only, not a shared patio. |
| `private_entry` | unit | Floor Plan/unit | Opt-in | Exterior entrance rather than a shared interior corridor. |
| `in_unit_laundry` | unit | Floor Plan/unit | Conditional | Existing enum already distinguishes in-unit, hookups, shared on-site, and none. |
| `parking` | unit | Mixed | Conditional | Availability may be Property-wide while assignment and type can vary by unit. Parking cost belongs in all-in composition. |
| `cooling` | unit | Floor Plan/unit | Conditional | In a starter Rubric only when the Owner says it matters. |
| `dishwasher` | unit | Floor Plan/unit | Opt-in | Straightforward advertised feature. |
| `kitchen_quality` | condition | Floor Plan/unit | Hold | VISION-dependent and remains disabled until the approved reference set and bench gate. |
| `flooring_quality` | condition | Floor Plan/unit | Hold | Same VISION gate as kitchen quality. |
| `pets_policy` | policy | Property/policy | Conditional | Enable when Hunt settings contain cats or dogs; current value intentionally ignores breed and weight restrictions. |
| `min_lease_months` | policy | Property/Floor Plan policy | Conditional | Relevant when the Owner supplies a desired lease duration. |
| `all_in_monthly` | cost | Hunt + Floor Plan composed | Core | Enable after collecting the Hunt's actual budget. Never extract directly. |
| `security_deposit` | cost | Floor Plan | Opt-in | Refundable deposit only; not the complete upfront cash requirement. |
| `availability_date` | availability | Floor Plan | Core | Enable after collecting the desired move-in deadline. |
| `grocery_proximity` | location | Property location | Opt-in | Maps-derived minutes using the Hunt's proximity mode. |
| `management_reviews` | reputation | Property/manager reputation | Opt-in | Places rating plus synthesis; do not treat the number alone as proof of management quality. |
| `location_safety` | location | Property location | Hold | Override-only placeholder until the deferred safety module exists. |

## 3. Proposed Property amenities and services

These are shared Property facts. They should use the proposed `property`
category unless the review decides to keep the current category vocabulary.
For boolean entries, missing page text means unknown/not-found, never `false`.

| Proposed key | Suggested value schema | Fact scope | Starter posture | Extraction guidance / boundary |
|---|---|---|---|---|
| `pool` | enum: `indoor`, `outdoor`, `indoor_and_outdoor`, `none` | Property | Opt-in | Record `none` only when explicitly stated; seasonal outdoor pools remain `outdoor`. Do not infer quality. |
| `fitness_center` | boolean | Property | Opt-in | True for an advertised resident gym/fitness center. Do not equate nearby third-party gyms with an on-site amenity. |
| `clubhouse` | boolean | Property | Opt-in | Resident clubhouse/community room; do not infer from a leasing-office photo. |
| `playground` | boolean | Property | Opt-in | On-site resident playground. Keep neutral by default so it can be positive or irrelevant per Hunt. |
| `picnic_area` | boolean | Property | Opt-in | Designated on-site picnic/grilling area, not merely landscaped grounds. |
| `emergency_maintenance_24_7` | boolean | Property service | Opt-in | “24-hour emergency maintenance” only. Keep distinct from ordinary on-site maintenance. |
| `maintenance_on_site` | boolean | Property service | Opt-in | Staff physically based at the Property; do not infer from a maintenance phone number. |
| `management_on_site` | boolean | Property service | Opt-in | On-site Property management/leasing staff. Keep separate from maintenance staff and management reviews. |
| `resident_portal` | enum: `payments_and_requests`, `payments_only`, `requests_only`, `none` | Property service | Opt-in | Captures online payments and maintenance requests without creating two nearly duplicate Criteria. |
| `package_handling` | enum: `locker`, `secured_room`, `office`, `unsecured_area`, `none` | Property | Opt-in | Prefer the best explicitly offered normal delivery path; do not infer security. |
| `elevator` | boolean | Property/building | Conditional | Enable when accessibility or upper-floor access matters. It does not prove step-free access from parking/sidewalk to the unit. |
| `step_free_entry` | boolean | Property-to-unit route | Conditional | True only for an explicit step-free/accessible route. A ramp at one entrance alone may be insufficient. This may ultimately require per-building or Floor Plan evidence. |
| `storage` | enum: `in_unit`, `assigned`, `shared`, `available_for_fee`, `none` | Mixed | Opt-in | Prefer in-unit over assigned/shared when multiple types are stated. Optional storage fees do not automatically enter all-in monthly cost. |
| `smoking_policy` | enum: `smoke_free_property`, `designated_areas_only`, `permitted` | Property policy | Conditional | Common Gate candidate. Page silence is unknown, not permission. This is a policy fact, not a claim that smoke exposure is impossible. |
| `property_type` | enum: `apartment`, `townhome`, `duplex`, `single_family`, `other` | Property | Opt-in | Stable Property fact. Decide during review whether mixed communities need `mixed`. |

Possible later Property amenities—EV charging, bike storage, dog park, business
center, sports courts, and gated entry—should stay Custom Criteria until the
real Hunt demonstrates repeated use. A generic “amenities” Criterion remains a
bad fit because its members have different meanings and weights.

## 4. Proposed unit and Floor Plan features

These belong in the existing `unit` category. The central unresolved issue is
scope: catalog Extractions are currently Property-level, while these features
often differ among Floor Plans or are advertised only for “select units.” A
Property-wide boolean would turn “select units have fireplaces” into a false
claim about every scored Unit Group.

Until Floor Plan-scoped Criterion values exist, use an advertised-availability
enum where needed:

`all_units | select_units | none`

Missing text still remains unknown; `none` requires an explicit statement.
This preserves honesty but cannot prove that the pinned Floor Plan has the
feature. Criteria marked **Hold** should not ship as Property-wide booleans.

| Proposed key | Suggested value schema | Fact scope | Starter posture | Extraction guidance / boundary |
|---|---|---|---|---|
| `walk_in_closets` | enum: `all_units`, `select_units`, `none` | Floor Plan/unit | Hold | “Large closets” is not a walk-in closet. Best implemented per Floor Plan. |
| `closet_storage` | enum: `generous`, `standard`, `limited` | Floor Plan/unit | Hold | Too subjective without an anchored definition or plan-specific evidence; likely omit in favor of `walk_in_closets`. |
| `fireplace` | enum: `all_units`, `select_units`, `none` | Floor Plan/unit | Hold | Record only a fireplace inside the unit, not a clubhouse/outdoor firepit. Fuel type could be evidence detail rather than scoring vocabulary. |
| `pantry` | enum: `all_units`, `select_units`, `none` | Floor Plan/unit | Hold | Walk-in versus cabinet pantry can remain evidence detail unless users need the distinction. |
| `countertop_material` | enum: `granite`, `quartz`, `solid_surface`, `laminate`, `other` | Floor Plan/unit | Hold | Material is more objective than “premium countertops.” Mixed/select-unit claims need Floor Plan scope. Avoid double-weighting with `kitchen_quality`. |
| `stainless_steel_appliances` | enum: `all_units`, `select_units`, `none` | Floor Plan/unit | Hold | Finish only; do not treat stainless steel as proof of appliance age or quality. Potential overlap with `kitchen_quality`. |
| `furnishing` | enum: `furnished`, `optional`, `unfurnished` | Floor Plan/unit | Opt-in | Usually explicit and decision-changing for short-term renters. Could ship before general Floor Plan-scoped amenities if listings represent only one offering. |
| `disposal` | boolean | Floor Plan/Unit | Opt-in | True if unit has a garbage disposal in the kitchen |


Before implementing the Hold group, choose one of these designs:

1. Extend Floor Plan extraction/persistence so Criterion values can overlay at
   scoring time, like the existing beds/baths/sqft fields. This is the most
   accurate long-term design.
2. Keep Property-level advertised availability (`all_units`/`select_units`)
   and accept that `select_units` cannot identify the pinned Floor Plan. It
   should never satisfy a non-negotiable.
3. Leave these as Custom Criteria until Floor Plan support exists.

Recommendation: option 1 for frequently used unit features; option 3 for the
long tail. Do not silently choose option 2 during implementation.

## 5. Proposed qualification, cost, and location Criteria

| Proposed key | Proposed category | Suggested value schema | Fact scope | Starter posture | Notes |
|---|---|---|---|---|---|
| `income_requirement_multiple` | policy | number, minimum 0 | Property policy | Opt-in | Example: gross income of 3× rent. Often omitted or qualified; unknown should stay neutral unless the Owner explicitly creates a Gate. |
| `minimum_credit_score` | policy | integer, 300–850 | Property policy | Opt-in | Record only an explicit threshold, not “good credit required.” |
| `estimated_move_in_cost` | cost | number, minimum 0 | Hunt + Floor Plan composed | Hold pending definition | Highest-value cost addition. Proposed meaning: known required cash before occupancy. Review must decide treatment of first-month/prorated rent, refundable deposits, and incomplete mandatory components. |
| `transit_proximity` | location | number, minimum 0 (minutes) | Property location | Opt-in | Needs a precise target: nearest usable transit stop is more defensible than a vague “good transit” rating. Tool behavior and mode must be designed. |
| `internet_connectivity` | property or unit | enum: `fiber`, `cable`, `fixed_wireless`, `dsl`, `unknown_other` | Address/unit serviceability | Hold | Listing claims are weak and provider availability can be address/unit-specific. Requires a reliable external-data seam before catalog promotion. |

Pet fit also needs a later decision. The current `pets_policy` intentionally
ignores breed and weight restrictions. Adding only a `has_restrictions`
boolean would not tell a household whether its actual pet qualifies. A useful
solution would require Hunt-level pet profiles (species, weight, possibly
breed) and a composed `pet_eligibility` result; that is broader than a catalog
row and should not be guessed into this batch.

## 6. Recommended starter Rubric behavior

A catalog should remain the reusable vocabulary of scoreable facts. A starter
Rubric should be a separate template populated from setup answers; the pinned
Catalog Entry contract has no `default_enabled` field.

Suggested setup inputs and resulting enabled Criteria:

| Setup answer | Enable/configure |
|---|---|
| Desired bedrooms | `beds` |
| Minimum/preferred bathrooms | `baths` |
| Maximum monthly budget | `all_in_monthly` |
| Move-in deadline | `availability_date` |
| Desired lease duration | `min_lease_months` |
| Cats/dogs in Hunt settings | `pets_policy` |
| Requires parking | `parking` |
| Laundry preference | `in_unit_laundry` |
| Cooling preference | `cooling` |
| Minimum space | `sqft` |
| Smoke-free requirement | `smoking_policy` |
| Accessibility/upper-floor access need | `step_free_entry`, `elevator` after their scope is resolved |

All other existing and proposed Criteria should initially be opt-in. In
particular, do not default-enable VISION Criteria, the `location_safety`
placeholder, subjective closet storage, or any unit feature whose Floor Plan
scope is unresolved.

## 7. Benchmark and corpus impact

### Historical no-impact boundary

When this was only a review draft, it changed no Catalog Entry, Extraction
schema, prompt, model, Rubric fixture, recording, or label. The subsequently
approved work is now sequenced as P3-SC2–P3-SC8 in `IMPLEMENTATION.md`; those
tasks own their stated fixture and bench effects.

### Impact when approved Catalog Entries are implemented

The effect depends on how each Criterion is produced:

| Kind of addition | EXTRACT/model-bench effect | Label effect |
|---|---|---|
| Page-text Criterion (`requires_tool = null`, not composed) | Automatically becomes a required field in the dynamic EXTRACT schema. This can change model behavior and output size for every listing, even when the Criterion is disabled in a Hunt's Rubric. Refresh the EXTRACT recordings and rerun the full candidate-model bench. | Existing labels remain syntactically valid because absent keys are not graded. Add the new key as a true value or `unknown` to each labeled bench listing if its extraction accuracy is to be measured. |
| Maps/web-search/VISION Criterion | Does not enter the zero-tool EXTRACT schema. Evaluate and record the producing stage separately; VISION additions must follow the versioned-reference-set gate. | Add labels only to a bench designed to grade that producing stage. The current text-extraction bench does not automatically validate it. |
| Composed Criterion | No direct EXTRACT schema change. It needs deterministic composer golden tests and SCORE goldens. Changes to underlying extraction blocks still affect EXTRACT recordings. | Label the source components and expected composition where the harness supports them; do not ask a human to label a number the design says the pipeline must calculate. |
| Floor Plan-scoped Criterion | Requires a schema, state, persistence, reconciliation, and SCORE-overlay decision before benchmarking is meaningful. | Labels must attach the fact to the relevant Floor Plan rather than pretending it is Property-wide. The current `BenchLabel.floor_plans` contract would need an intentional extension. |

The current recording hash covers stage, model, prompt version, and cleaned
content—not the generated structured-output schema. Therefore a catalog schema
change may look up the same recording filename but fail validation because the
old output lacks newly required fields. Re-recording must deliberately refresh
those EXTRACT outputs; merely retaining the old files is not a valid replay.

### Do the existing bench listings need to be relabeled?

Not automatically, and not all 50+ corpus pages:

- The corpus is the larger local eval kit. Only the trimmed, human-labeled
  bench set participates in the current model bench.
- Existing label files grade only keys present in `criteria` or `unknown`, so
  adding a catalog key does not invalidate them.
- If a new Criterion becomes Gate-bearing in the benchmark Rubric, every
  labeled bench listing must classify that key as a value or `unknown`. This
  follows the Phase 0 rule that every Gate-bearing Criterion has ground truth.
- Even for non-Gate Criteria, label the key across the whole labeled bench set
  if the report will claim accuracy for it. Partially labeling a key changes
  the accuracy denominator and makes before/after reports hard to compare.
- Audit coverage before labeling. If none of the frozen pages actually states
  an amenity (for example, no page has an explicit resident portal or
  fireplace), marking all ten as unknown tests hallucination resistance but
  not extraction recall. Add or deliberately select corpus pages with positive,
  negative, “select units,” and missing cases rather than fabricating labels.

### Suggested rollout for the eventual implementation

1. Approve keys, exact schemas, fact scopes, and starter behavior in this
   review.
2. Update `DESIGN.md` §8.2 in place and append the required §20 Decision Log
   entry.
3. Add a small first tranche rather than every idea at once. Recommended
   text-extraction tranche: `smoking_policy`, `property_type`, `pool`,
   `fitness_center`, `emergency_maintenance_24_7`, `management_on_site`, and
   `resident_portal`.
4. Regenerate the catalog seed, add the post-Phase-1 catalog-sync migration,
   and add scoring-engine golden coverage.
5. Extend the human labels for that tranche across the trimmed bench set,
   including explicit unknowns.
6. Refresh recorded EXTRACT responses and rerun the Phase 0 model candidate
   pool. Compare existing Gate accuracy as well as new-field accuracy, tokens,
   latency, schema-validation failures, and invented-value rate.
7. Promote more amenities only if the first tranche does not materially harm
   extraction reliability or cost.

## 8. Decisions for review

1. Add the `property` Criterion category, or keep shared amenities under an
   existing category?   
2. Should the starter Rubric be answer-driven as proposed, or should it be a
   fixed set of enabled Criteria?
3. Should frequently used unit amenities gain true Floor Plan-scoped Criterion
   values, or remain Custom Criteria for now?
4. Which Property amenity tranche is worth the EXTRACT-schema/token cost?
5. What exactly counts toward `estimated_move_in_cost`?
6. Does `property_type` need a `mixed` value?
7. Should `resident_portal` be one capability enum or two boolean Criteria
   (`online_payments`, `online_maintenance_requests`)?

---

I want to add the following rubric criteria:
- walk-in-closets
- pantry
- disposal (garbage disposal)
- stainless-steel appliances
- fireplace
- ceiling fans
- floors (could be multiple: hardwood, tile, vinyl)
- basement
- high-speed internet access (usually listed verbatim, or as Fiber-Ready)
- heating

Here are my answers to §8 of the document
1. I think we should introduce the property criterion category now rather than later. For starters I would like to include the following amenities/criteria:
  - pool
  - fitness center/gym
  - clubhouse
  - emergency or 24 hour maintenance
  - maintenance on site
  - management on site
  - resident portal
  - package handling
  - storage
  - smoking policy
  - property type
  - resident portal/maintenance requests/online payments
2. I think the starter rubric behavior as proposed is fine, but I think we should have a saved, fixed "dev" rubric to smoke test different listings during development
3. I'm not entirely sure I know what this means
4. I think we could categorize the property amenities (and perhaps some catalog items) as "best effort" which for the most part is how we are working anyways, but with a distinction. Similar to how we have some items that will gate (non-negotiables), best-effort criteria will be attempted to be extracted, but in the case they are not able to be extracted, we will not fetch any new pages during the reconcile for these items specifically even if there is disagreement between sources on whether the property or unit group contains these amenities. For example, if we label "pool" as best-effort, and during reconciliation, one website's listing says the property has a pool and another website says it does not, we will go with the optimistic approach and assume that the property does indeed have a pool. Furthermore, if we don't know whether a property has a pool or not, we will not fetch more listings to figure out if it does or not, but if we are already fetching anyways for other reasons, then we might as well look for pools mentioned in that listing as well. Does this make sense?
5. Security deposit + 1st month rent + application fee + one time admin fee + one time pet fee + first month pet rent + utilities + anything else that makes sense
6. Property type should be able to handle a list of types that are available. Unit group should also have the type of unit that it is (even if it is several types somehow)
7. the finer-grained, the better i think.

Thoughts? Assess the ideas and my feedback, and put together a plan to update the current implementation based on the above.
