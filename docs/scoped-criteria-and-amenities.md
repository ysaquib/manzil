# Criterion Scope, Property Amenities, and Floor Plan Details — Finalized Design Plan

Status: **supplementary finalized decision workbook; P3-SC4 engineering landed
2026-07-27 with its human bench acceptance tail pending**. Product and
architecture choices are approved or explicitly deferred. P3-SC1 promoted them
into `DESIGN.md` v3.7 and its §20 Decision Log, recorded selected mechanics and
the Extraction-consumer audit in `IMPLEMENTATION.md` v2.0.68, and sequenced the
P3-SC task series. P3-SC2 and P3-SC3 subsequently landed the scoped substrate
and first Property/set-valued Catalog tranche. P3-SC4 then landed its sparse
claim/presence implementation and bench tooling. `DESIGN.md` v3.15 and
`IMPLEMENTATION.md` v2.0.78 are authoritative; this file keeps the fuller
rationale. Human finalization of the canonical ten and its current-pin baseline
remain the P3-SC4 acceptance gate, not an unresolved design decision.

Written 2026-07-20 against `DESIGN.md` v3.6 and promoted 2026-07-21 into v3.7,
`docs/catalog-and-rubric-review.md`, and the current implementation. This work
intersects Phase 3 P3-6 (multi-source RECONCILE), P3-10 (Custom Criteria),
P3-12 (field-scoped refresh), the Phase 0 model bench, and the scoring and
persistence contracts. It should not be slipped into one of those tasks
without being separately approved and sequenced.

### Approval record — 2026-07-20

Yusuf approved **§§0–3 as written**, including these controlling decisions:

- Property amenities remain Property-scoped.
- Unit features preserve specific/all/select/unspecified applicability
  (`specific_floor_plans`, `all_units`, `select_units`, and
  `unit_scope_unspecified`).
- Exact amenity mapping is Source-local.
- Cross-Source Floor Plan matching is deferred.
- Correctness takes precedence over coverage: prefer missing an exact
  association over creating a wrong one.
- The recommended semantics are approved. Persistence mechanics were initially
  delegated pending an audit of every current Extraction
  read/write/current-value query.

The fourth-pass resetability decision below supersedes the initially open table
choice: direct generalization of `extractions` is now selected. P3-SC1 later
completed the required query audit; its authoritative inventory and selected
mechanics are in `IMPLEMENTATION.md` §7 and §3.

### Approval record — 2026-07-20 (second pass)

Yusuf approved **§§4–7 as written**, with these clarifications and selections:

- The former “best-effort” behavior is approved under the renamed independent
  policies: `available_sources_only` for Criterion escalation and
  `verified_positive_preferred` for conflicts.
- If such a Criterion becomes Gate-bearing, its effective escalation policy is
  `decision_relevant`; normal bounded reconciliation and escalation apply.
- A credible positive/negative disagreement resolved by
  `verified_positive_preferred` uses the quiet **Sources disagree** presentation,
  not the normal Problematic badge. All candidates and provenance remain
  visible.
- Floor Plan deep links are deferred. The modal/full-screen detail experience
  does not add a new route contract in v1.
- The controlled Property/Unit type vocabulary is
  `apartment | condo | townhome | duplex | single_family | loft | other`.
  `apartment` is retained because otherwise the dominant Property type would
  collapse into `other`; triplex, fourplex, and manufactured home are omitted.
- The Pass 7 Floor Plan diagram decisions and Pass 8 additional Floor Plan
  fields from `archive/working through decision workbook.md` are approved and
  incorporated into §7 and the §9 checklist below.

### Approval record — 2026-07-20 (third pass)

Yusuf approved the Pass 10 checklist governance and Pass 11 release
recommendations from `archive/working through decision workbook.md`:

- §9 uses three explicit states: `[x]` approved, `[-]` deferred with a named
  trigger, and `[ ]` blocking before the named phase.
- Product approvals and delegated engineering-design gates are distinguished;
  delegation does not permit implementation before the gate is resolved and
  recorded.
- §9.1 must contain no unanswered blocking item before scoped-fact
  implementation starts.
- Basement support is deferred. Reconsider it only after the first scoped-unit
  and mixed-scope tranches have shipped and real Listing evidence shows that it
  would materially affect the Hunt.
- The Pass 11 zero-wrong-association, Gate-regression, schema-validation,
  partial-fetch, ambiguity, and NFR1 cost thresholds are approved as release
  gates. Because the labeled bench is small, reports must include raw counts
  alongside percentages.

This approval changes planning status only. It does not authorize production
implementation or promote these decisions into `DESIGN.md`.

### Approval record — 2026-07-20 (fourth pass)

Yusuf confirmed that Manzil is not live, has no production data to preserve,
and may use `supabase db reset` and reseed from code-defined state. Under that
resetability assumption, Yusuf approved all recommended §9.1 and §9.2 choices:

- generalize the existing `extractions` schema directly into the single
  append-only Property/Floor Plan fact store; do not add a transitional parallel
  scoped-extractions table solely for migration safety;
- use explicit Source-claim identity and a separate reconciled effective-value
  layer;
- use sparse top-level unit-feature claims, generated response-local Floor Plan
  keys, and expanded per-Floor Plan persisted rows with common provenance;
- use authoritative-success refresh semantics, Source-owned transactional
  `split-property` movement/reconciliation, and the approved global-versus-Hunt
  RLS boundary;
- add general internet readiness as a Property-scoped, listing-advertised fact;
  granular Floor Plan readiness and external serviceability verification remain
  deferred;
- defer storage;
- allow objective flooring materials and subjective `flooring_quality`
  together with an explicit double-weight warning; and
- use the versioned declarative dev Rubric fixture and guarded idempotent seed
  behavior specified in §§8 and 9.2.

At the time of this approval the Extraction-query audit remained mandatory but
was no longer an open schema-selection decision. P3-SC1 completed it on
2026-07-21; `IMPLEMENTATION.md` now owns the result.

### Approval record — 2026-07-21 (final planning pass)

Yusuf approved the remaining §9.3 and §9.5 recommendations and requested that
the plan be finalized before design promotion:

- Floor Plan diagrams use a separate starting cap of three current diagrams per
  Floor Plan and thirty current Floor Plan diagrams per Property, with unmatched
  diagrams counting against the Property cap; fixtures may lower or raise these
  constants only through a recorded implementation decision;
- diagram associations follow authoritative-success refresh semantics and
  retain inactive history/bytes while the Property exists;
- third-party diagrams remain normalized, attributed, private authenticated-use
  assets with an explicit purge path; this is a product retention posture, not
  a legal conclusion;
- the scoped-fact foundation and migration of existing unit Criteria precede
  P3-6 RECONCILE; later UI/catalog tranches follow it or run in parallel only
  where their dependency is already met;
- the temporary honesty guard is omitted under the current clean-reset/no-live-
  ingestion assumption and becomes required only if real Hunt data will use the
  old Property-only pipeline before the scoped substrate lands;
- the current model pins remain the baseline and do not block scoped-schema
  work; schema/token constants are derived from the canonical bench with
  structural limits and NFR1 as hard constraints; and
- this work uses a distinct `P3-SC1`… task series so existing Phase 3 numbers,
  especially P3-6 and P3-7, retain their established meanings.

The remaining bench audit is required work, but not an unresolved product or
architecture decision.

## 0. Outcome and recommendation

The current implementation has a real scope problem: catalog Extractions are
Property-scoped, while several existing Criteria describe a Floor Plan or
unit. During SCORE, only `beds`, `baths`, `sqft`, `security_deposit`, and
`availability_date` receive a Floor Plan overlay. A page-level value for
`patio_balcony`, `private_entry`, `in_unit_laundry`, `parking`, `cooling`, or
`dishwasher` therefore affects every Floor Plan at the Property.

Do **not** make all amenities Property facts. That is appropriate for a pool,
fitness center, clubhouse, management service, and similar shared facilities,
but it would turn claims such as “select units have in-unit laundry” into false
claims about every scored Floor Plan. This can change rankings, make the wrong
Floor Plan appear best within a Unit Group, and incorrectly satisfy a Gate.

Also do **not** require exact Floor Plan mapping for every amenity before the
feature can ship. Many pages cannot support it. The recommended middle path is:

1. Preserve the page's actual specificity: exact Floor Plans, explicitly all
   units, select units, or advertised with unit applicability unstated.
2. Score exact and explicitly-all-unit claims as confirmed.
3. Display select/unspecified claims as “advertised; not confirmed for this
   Floor Plan,” never as truth for a particular Floor Plan and never as
   sufficient for a non-negotiable.
4. Add exact Floor Plan mapping only where the source reliably supplies it.
5. Keep mapping source-local initially; defer cross-Source Floor Plan identity
   matching until the need and evidence justify it.

This captures most of the apartment-hunt value without paying the full cost of
perfect cross-site Floor Plan reconciliation.

## 1. Current implementation assessment

### 1.1 What exists

- `extractions` stores one current catalog fact per
  `(property, hunt_id, criterion)`; catalog facts have `hunt_id = NULL`.
- EXTRACT emits one `{value, confidence, evidence_quote}` wrapper per
  text-extractable Catalog Entry, plus a separate `floor_plans` array.
- `FloorPlanIn` contains rent, beds, baths, sqft, deposit, availability, and one
  evidence quote. It has no generic Criterion-value collection.
- SCORE overlays only beds, baths, sqft, deposit, and availability from a
  Floor Plan onto the Property-level effective values.
- Overrides are Listing + Criterion scoped. They cannot correct one Floor Plan
  without changing every Floor Plan in the Listing.
- The fixed `phase0_rubric.py` is an eval/CLI Rubric, not a saved development
  Hunt Rubric exercised through the real API and frontend.
- Multi-source RECONCILE is planned under P3-6 but has not landed. This is the
  best point to settle per-Criterion escalation, conflict, and scoped-claim
  behavior before its storage and resolution rules become established.

### 1.2 Consequences

The following evidence cannot currently be represented honestly:

- “Balconies available in select units.”
- “The Ash and Birch plans have washer/dryer.”
- An unqualified Property amenity list containing “dishwasher.”
- Shared on-site laundry plus in-unit laundry in only some Floor Plans.
- Storage lockers for the Property plus in-unit storage in a specific plan.
- Conflicting claims in which one Source identifies the relevant Floor Plan
  and another only advertises the amenity generally.

The current boolean schemas make the problem especially sharp. `true` loses
whether the claim meant one Floor Plan, all units, select units, or merely an
unqualified advertisement.

## 2. Is exact amenity-to-Unit-Group mapping worth it?

### 2.1 Short answer

**Yes for decision-relevant unit features, but only when the page supplies a
reliable link. No as a universal extraction requirement.**

The valuable target is Floor Plan mapping, not Unit Group mapping. A Unit Group
is derived from `(beds, baths)` and is not stored. Facts should attach to Floor
Plans; the Unit Group then derives the available facts from its plans and uses
the existing best-or-pinned-plan display behavior.

### 2.2 Expected apartment-hunt value

Exact mapping is most valuable where all three are true:

1. The feature can materially change whether a unit is acceptable or how it
   scores.
2. The feature commonly varies among Floor Plans.
3. Listings often provide plan-specific evidence.

This strongly applies to:

- in-unit laundry or hookups;
- private entry;
- patio/balcony;
- dishwasher;
- fireplace;
- cooling and heating configuration;
- storage type;
- sometimes parking and furnishing.

It is less valuable for minor preference bonuses when most Sources advertise
only a Property-wide amenity list. Walk-in closets, pantry, disposal, ceiling
fans, and appliance finish can initially use the honest
select/unspecified-unit fallback and gain exact mapping when available.

### 2.3 What goes wrong if all amenities are treated as Property-wide

For shared facilities, nothing goes wrong: a pool or clubhouse correctly
applies to every Floor Plan because the resident's access derives from the
Property.

For unit features, Property-wide truth creates four material risks:

- **Ranking error:** a cheaper Floor Plan without laundry can inherit laundry
  from a more expensive plan and become the displayed best plan.
- **Gate error:** “must have in-unit laundry” can pass on a Floor Plan for which
  the listing provides no such evidence.
- **Comparison error:** two Unit Groups at the same Property appear identical
  even when their layouts have different features.
- **False confidence:** evidence and confidence remain visible, but the scope
  transformation itself is hidden, so the UI looks more certain than the
  source warrants.

This could negatively affect the apartment hunt when a feature is important or
Gate-bearing. For a low-weight bonus such as pantry, the practical harm is
smaller, but still biases rankings.

### 2.4 Complexity and the reasonable stopping point

There are three increasing levels of complexity:

1. **Preserve applicability** — detect exact/all/select/unspecified. This has
   high value and moderate complexity and should be required.
2. **Source-local Floor Plan mapping** — link a claim to plans on the same page.
   This has high value when explicit and manageable complexity and should be
   implemented.
3. **Cross-Source Floor Plan identity** — decide whether differently named
   plans on different sites are the same layout. This has substantial
   extraction, reconciliation, persistence, and error-recovery complexity. It
   is not required for the first version.

The recommended stopping point for the apartment hunt is level 2. Level 3
should be triggered by real listings showing that source-local mappings are
insufficient, not assumed into the first implementation.

### 2.5 Explicit recommendation for this apartment hunt

Approve and implement the middle path through level 2:

- classify genuinely shared amenities as Property facts;
- preserve specific/all/select/unspecified applicability for unit features;
- map unit features to Source-local Floor Plans whenever the Source provides a
  reliable association;
- treat select/unspecified features as advertised but unconfirmed, not
  confirmed;
- let the Unit Group derive its presentation from its Floor Plans;
- defer cross-Source Floor Plan identity matching.

This is worth the implementation time because laundry, private entry,
balcony/patio, cooling, dishwasher, fireplace, heating, and storage
can change which actual Floor Plan is acceptable. Treating them all as
Property-wide would be simpler in code but can materially distort the current
apartment hunt: it can rank the wrong Floor Plan first, make comparisons
misleading, and let uncertain evidence satisfy a Gate. Perfect mapping is not
worth delaying the hunt; honest uncertainty plus exact mapping where available
is the recommended cost/benefit boundary. Basement is nevertheless deferred
until post-tranche evidence shows that its Hunt value justifies a dedicated
schema.

### 2.6 Approved Unit Group and Overview-row contract

**Approved 2026-07-20 and recorded in DESIGN v3.6 §3, §9.4, §13.2, and §20.**

The Unit Group remains the derived `(beds, baths)` presentation bucket; it does
not become one row per Floor Plan and does not imply that sibling Floor Plans
share amenities, Unit type, price, or availability. The **Display Floor Plan**
is the Unit Group's valid pinned Floor Plan, otherwise its highest-scoring Floor
Plan.

One Overview row has two explicit layers:

- Unit Group aggregates: `(beds, baths)` identity, Floor Plan count, rent/sqft
  ranges, and the separately labeled earliest-availability summary.
- Display Floor Plan values: score, all-in composition, deposit,
  Criterion-backed values, and scoped amenities/layout facts.

The row identifies `Pinned: <plan>` or `Best score: <plan>`, exposes its `×N`
alternatives, and shows “varies by Floor Plan” when scoped facts differ. It
never constructs an optimistic union of sibling-plan amenities. Unit Group
ratings, comments, Interest Status, and visited state remain Unit-Group-scoped;
simultaneous per-plan applications remain the trigger for a later
Application/entity decision.

## 3. Proposed conceptual model

Do not collapse these independent concepts:

| Concept | Proposed vocabulary | Purpose |
|---|---|---|
| Criterion category | existing values plus `property` | Rubric UI grouping |
| Fact scope | `property`, `floor_plan`, `mixed`, `composed` | What the fact describes |
| Unit applicability | `specific_floor_plans`, `all_units`, `select_units`, `unit_scope_unspecified` | How far unit-feature evidence reaches |
| Effective presence | `confirmed`, `advertised_unconfirmed`, `none`, `unknown` | What SCORE may conclude for one Floor Plan |
| Criterion escalation policy | `decision_relevant`, `available_sources_only` | Whether this Criterion may itself trigger bounded escalation |
| Criterion conflict policy | `standard_ladder`, `verified_positive_preferred` | How credible conflicting values are resolved |
| Starter posture | `core`, `conditional`, `opt_in`, `hold` | Hunt setup behavior; not fact semantics |

### 3.1 Applicability rules

- `specific_floor_plans`: the Source explicitly associates the claim with one
  or more Floor Plans on that Source.
- `all_units`: the Source explicitly states every unit has the feature. A
  generic amenities list is not sufficient.
- `select_units`: the Source says “select units,” “some units,” or provides an
  asterisk/legend with that meaning.
- `unit_scope_unspecified`: the amenity is advertised for the Property's units,
  but the Source does not state which units have it.

Applicability describes where a claim reaches; it does not encode the feature
value. Explicit unavailability is an `effective_presence` value of `none` with
the appropriate applicability. Page silence remains `unknown`/not-found.

Display labels should be explicit:

- Included in this Floor Plan
- All units
- Select units
- Advertised; unit applicability unknown
- Not offered
- Unknown

### 3.2 Effective value for one Floor Plan

Resolve in specificity order:

1. Floor Plan-scoped Override.
2. Reconciled exact Floor Plan claim.
3. Reconciled explicit `all_units` claim.
4. Reconciled `select_units` or `unit_scope_unspecified` claim.
5. Unknown.

An exact negative may override a less-specific `all_units` positive because the
exact evidence is more specific. Conflicts must remain inspectable.

For ordinary Rubric matching, the effective vocabulary for presence-like unit
features should be:

- `confirmed`
- `advertised_unconfirmed`
- `none`
- `unknown`

`select_units` and `unit_scope_unspecified` both become
`advertised_unconfirmed` for a Floor Plan lacking an exact claim. Owners may
assign partial or neutral points, but `advertised_unconfirmed` must never
satisfy a non-negotiable requiring the feature.

### 3.3 Claims shared by several Floor Plans

EXTRACT should be able to emit one sparse claim targeting several Source-local
Floor Plan references. Persistence may expand it to one scoped fact per target
Floor Plan for simple queries and SCORE overlays. This is not harmful
duplication: provenance points back to the same Source/evidence, and the number
of facts is small.

Do not attach global facts to a Unit Group. If target Floor Plans span several
Unit Groups, each Floor Plan receives the claim and the groups derive the
result. If every Floor Plan is named, use exact targets; use `all_units` only
when the Source itself makes that universal claim.

### 3.4 Approved candidate persistence direction

Generalize the existing `extractions` contract and table directly with a target
and applicability rather than inventing a parallel amenity system. This direct
cutover is approved because Manzil is not live, no production rows must be
preserved, and the database can be reset and reseeded from code-defined state.

Conceptually, an Extraction needs:

- existing Property, Hunt, Criterion, value, confidence, evidence, Source,
  model, resolution rule, and timestamp fields;
- nullable `floor_plan_id` for exact Floor Plan facts;
- a target/applicability discriminator;
- enough candidate history for P3-6 to preserve disagreements.

The append-only Source-claim identity is based on Property, nullable Hunt/custom
Criterion scope, Criterion, Source, target scope, and target ID. Applicability
is retained on the claim but does not create an independently current lineage:
if one Source changes the same target claim from `all_units` to `select_units`,
the successful new observation supersedes the prior Source claim. Reconciled
effective values use the same Criterion and target while resolving across
current Source claims. Centralize both lookups behind one repository/query seam
or database view rather than duplicating “latest timestamp” logic.

Audit every existing Extraction read, write, current-value, rescore,
persistence, DEDUPE/split, and API/UI provenance query before implementation so
every path moves atomically to the new contract. The audit is a completeness
gate, not a table-selection gate. Record the exact columns, indexes,
current-value queries/views, reset/reseed mechanics, and P3-6 candidate shape in
the implementation plan and authoritative design documents before scoped
Extraction implementation begins. No legacy-data backfill or dual-read period
is required.

RunState should keep extraction-time plan references source-local. The terminal
projection can resolve them to stable `floor_plans.id` values after the Floor
Plan upsert. Persist-before-advance remains mandatory.

### 3.5 Overrides

The current Listing + Criterion Override is insufficient for unit features.
The UI and persistence need at least:

- override this Floor Plan;
- override all units at this Property for this Listing;
- revert to extracted value.

A human-entered “select units, exact plan unknown” correction is deferred until
real Curator usage demonstrates the need. If later approved, it must be an
applicability correction, not a boolean `true`.

## 4. Criterion escalation and conflict policies

Do not encode acquisition effort and conflict resolution in one overloaded
“best effort” label. They are independent policies, neither is a Criterion
category, and neither is a confidence level.

`criterion_escalation_policy` controls whether a Criterion may itself cause
RECONCILE to acquire more evidence:

- `decision_relevant`: the Criterion may trigger the bounded escalation ladder
  when its unresolved value affects the Hunt's decision.
- `available_sources_only`: extract the Criterion from every Source already
  available to the run, including Sources fetched later for other Criteria, but
  do not fetch another Source solely because this Criterion is unknown or
  disputed.

`criterion_conflict_policy` controls how credible conflicting candidates are
resolved:

- `standard_ladder`: use ordinary equivalence, voting, escalation eligibility,
  and conservative fallback.
- `verified_positive_preferred`: when credible verified positive and explicit
  negative evidence conflict, select the positive while retaining both
  candidates, confidence, evidence, freshness, and the disagreement in
  provenance.

Under either policy, silence, a failed fetch, or low-confidence evidence never
becomes positive. `verified_positive_preferred` means prefer verified positive
evidence when credible Sources disagree; it never means “assume yes.” The
selected value records `verified_positive_preferred` as its resolution rule.

### 4.1 Interaction with Gates

**Approved:** if an `available_sources_only` Criterion becomes Gate-bearing in
the active Rubric, its effective escalation policy becomes
`decision_relevant` and P3-6 uses the normal bounded reconciliation and
escalation ladder. An `advertised_unconfirmed` value still cannot satisfy a
non-negotiable; allowing an uncertain positive to satisfy a Gate would violate
data honesty.

A credible positive/negative disagreement selected under
`verified_positive_preferred` uses a quiet **Sources disagree** indicator rather
than the normal Problematic badge. Candidate values, confidence, evidence,
freshness, and the selected resolution rule remain visible in provenance.

### 4.2 Initial available-sources-only candidates

Approved defaults: use `available_sources_only` with
`verified_positive_preferred` when these are preferences rather than Gates:

- pool;
- fitness center;
- clubhouse;
- management/maintenance conveniences;
- resident portal capabilities;
- package handling;
- general internet readiness;
- walk-in closets, pantry, disposal, ceiling fans, and appliance finish.

Use `decision_relevant` with `standard_ladder` for:

- smoking policy;
- availability;
- costs and fees;
- pet eligibility;
- anything Gate-bearing in the Hunt;
- a unit feature explicitly selected as non-negotiable.

## 5. Catalog proposal

### 5.1 Property Criteria

**Approved first Property tranche:** add `property` to `CriterionCategory` and
add the following scoreable Criteria:

| Key/direction | Scope | Approved schema/boundary |
|---|---|---|
| `pool` | Property | `indoor`, `outdoor`, `indoor_and_outdoor`, `unspecified`, `none`; private pools deferred |
| `fitness_center` | Property | boolean; on-site only |
| `clubhouse` | Property | boolean |
| `emergency_maintenance` | Property service | enum: `emergency_service`, `24_hour_emergency`, `none` |
| `maintenance_on_site` | Property service | boolean |
| `management_on_site` | Property service | boolean |
| `online_payments` | Property service | boolean |
| `online_maintenance_requests` | Property service | boolean |
| `package_handling` | Property | `locker`, `secured_room`, `office`, `unsecured_area`, `none` |
| `smoking_policy` | Property policy | `decision_relevant` + `standard_ladder`; common Gate candidate |
| `property_types` | Property | array/set of controlled type values |
| `internet_readiness` | Property | boolean: the Source advertises general internet/high-speed/fiber readiness; silence is unknown, not false |

Generic `resident_portal` is retained as display evidence, not a third
scoreable Criterion. `online_payments` and `online_maintenance_requests` are the
scoreable capabilities, avoiding triple-weighting one portal.

In the project vocabulary, `internet_readiness` is Property-scoped rather than
Listing-scoped: Listing means the Hunt–Property association, while this is a
global fact extracted from one or more Source listing pages. It records only
that general readiness is advertised across the Property. It does not guarantee
service to a particular Floor Plan, verify provider serviceability, or mean
internet is included in rent. Granular Floor Plan readiness and external
serviceability checks are deferred.

`storage` is deferred rather than placed in this tranche. Reconsider it only if
post-rollout Listing evidence shows material Hunt value; its later design must
separate physical type and scope from required or optional fees.

The approved `pool` vocabulary is
`indoor | outdoor | indoor_and_outdoor | unspecified | none`.

### 5.2 Existing Criteria that need scoped handling

- `patio_balcony`
- `private_entry`
- `in_unit_laundry`
- `parking`
- `cooling`
- `dishwasher`
- `heating_type` extraction block

Laundry and parking are mixed. Shared on-site laundry and Property parking
availability can be Property facts, while in-unit laundry, hookups, assigned
parking, and sometimes parking type can vary by Floor Plan.

### 5.3 New unit/Floor Plan Criteria

Approved first objective tranche:

- `walk_in_closets`
- `pantry`
- `disposal`
- `fireplace`
- `ceiling_fans`
- `stainless_steel_appliances`

Approved later objective tranche:

- `flooring_materials`: array/set, distinct from subjective
  `flooring_quality`. Both may be enabled, but the Rubric editor warns about
  possible double-weighting.

`basement` is deferred beyond these tranches. Reconsider it after the first
scoped-unit and mixed-scope tranches only if real Listing evidence shows that it
materially affects the Hunt; private/shared and finished/unfinished semantics
must then be designed before it can enter the Catalog.

`storage` is likewise deferred. Reconsider it after the first scoped-unit and
Property tranches only if real Listing evidence shows material Hunt value; use
a mixed-scope set of physical types and separate fee representation if it is
later approved.

### 5.4 Property and unit types

Approved shape:

- `property_types`: Property-level set using
  `apartment | condo | townhome | duplex | single_family | loft | other`.
- `unit_types`: Floor Plan-level set. Normally one value, but a set avoids
  forcing a false choice on hybrid offerings; it uses the same initial
  controlled vocabulary.
- A Unit Group displays the union of its Floor Plans' unit types.

Array-valued Catalog Entries require new schema-generation, API/frontend
validation, and scoring semantics. Approved match operators are `contains_any`
(non-empty intersection) and `contains_all` (the extracted set contains every
configured value); the current `in` operator is not sufficient.

## 6. Estimated move-in cost

Approved time window and meaning:

> Required cash from application through occupancy for the selected Floor
> Plan, using one full realistic first month when the Source does not provide a
> more exact payment schedule.

Approved composition:

```text
estimated_move_in_cost
  = first_month_all_in
  + security_deposit
  + application fees
  + admin fees
  + one-time pet deposits/fees
  + other required one-time charges
  + required prepaid or last-month rent
  + non-credited holding deposits
```

`first_month_all_in` already contains base rent, mandatory monthly fees,
first-month pet rent, and utility estimates. Do not add those components again.

Other approved required components when explicitly stated:

- move-in/community fee;
- key, fob, or garage-device deposit;
- required parking deposit;
- utility connection deposits;
- required renters-insurance initiation charge;
- last month's rent when explicitly required;
- holding deposit only to the extent it is not credited toward another counted
  component.

Refundable amounts still affect cash required and must be included but tagged
and subtotaled separately from non-refundable amounts. Optional charges are
excluded. When no exact/prorated payment schedule is stated, use one full
realistic first month. If a major required component is unknown, show a known
subtotal with an incomplete badge, do not present it as the complete move-in
cost, and score `estimated_move_in_cost` as unknown. This remains a separate
later workstream and does not block scoped amenities or Floor Plan diagrams.

## 7. Floor Plan detail and image feature

### 7.1 Product behavior

Every Floor Plan displayed inside a Unit Group should be clickable. Clicking it
opens a Floor Plan detail surface without losing the Listing detail context or
any unsaved draft edits. Approved UX:

- desktop: a nested modal above the Listing Drawer;
- mobile: a full-screen modal with a clear return to the Unit Group;
- keyboard: Floor Plan rows/cards are real buttons or links, focus is trapped
  while open, Escape closes, and focus returns to the clicked Floor Plan;
- v1 deliberately has no Floor Plan deep link or new top-level route contract;
  deep links are deferred.

The detail surface should show:

- plan name and source;
- beds, baths, Unit type(s), sqft range, rent range, deposit, earliest
  availability, and available-unit count;
- whether this is the pinned or currently displayed plan for its Unit Group;
- its score and Criterion breakdown, not only the Unit Group's displayed score;
- confirmed amenities, advertised-but-unconfirmed amenities, explicit
  absences, and unknowns, grouped and labeled by applicability;
- evidence and provenance for each amenity, including the Source and last
  extraction/refresh time;
- the Floor Plan diagram carousel when associated diagrams exist;
- an explicit “No Floor Plan diagram found” empty state rather than substituting
  a generic Property photo;
- the Source's Floor Plan detail URL or anchor when one was captured;
- Floor Plan-scoped Override controls when that part of the scoped-fact feature
  lands.

The parent Overview row follows the approved §2.6 contract: clicking the Unit
Group opens its alternatives, while clicking a particular Floor Plan opens this
detail surface. Plan-specific values in Overview and Compare always follow the
Display Floor Plan; group-level ranges/counts remain aggregates.

The existing Listing photo gallery remains Property-level. Floor Plan diagrams
must not be mixed into it without a clear `Floor plan` label, and Property
photos must not appear as if they depict a selected layout.

### 7.2 Image discovery and association

Extend FETCH/image discovery to retain context for each image candidate rather
than only its URL. Useful context includes:

- `alt`, `title`, caption, and nearby text;
- enclosing Floor Plan card/table row;
- link target and Source-native plan identifier;
- JSON-LD or embedded-data object path;
- nearby plan name, beds, baths, and sqft;
- whether the candidate came from a thumbnail, full-size link, `srcset`, CSS
  background, or embedded JSON.

IMAGE_FETCH continues to download through the SSRF-guarded fetcher, normalize,
hash, deduplicate, and store in the private `property-images` bucket. Floor Plan
diagrams need a separate normalization profile from ordinary photos: diagrams
often contain small labels and dimensions, so the current approximately
1024-pixel photo target may make them illegible. The approved starting
candidate preserves aspect ratio up to 2048 pixels and uses lossless or
high-quality WebP, while still enforcing byte and decompression-bomb limits;
the legibility fixture determines the exact final normalization profile.

Association must be source-local in v1. Accept an automatic Floor Plan link
only when structured data, a containing Floor Plan card, a Source-native ID, or
an unambiguous nearby plan label supports it. Filename resemblance or visual
similarity alone is insufficient. Record:

- association method;
- confidence;
- contextual evidence used for the link;
- Source and extraction time.

If an image is clearly a Floor Plan diagram but cannot be linked reliably, keep
it as an unmatched Floor Plan diagram at the Property and show it in a separate
“Unmatched Floor Plan diagrams” gallery. Do not attach it to every Floor Plan.
The database design must support a later manual association/disassociation with
append-only attribution, but the Curator UI is deferred until automatic
coverage demonstrates that it is needed.

Floor Plan diagrams are not inputs to `kitchen_quality` or `flooring_quality`
VISION. They must be excluded from that target slice so diagrams do not dilute
photo-based ratings. Any later OCR, diagram interpretation, or vision-based
plan matching is a separate approved feature with its own evals.

### 7.3 Storage and database direction

Reuse `property_images` as the content-addressed asset table and add a dedicated
association table rather than putting only `floor_plan_id` on the image row.
One diagram may be explicitly shared by several Floor Plans, and one Floor Plan
may have several diagrams.

Conceptual shape:

```text
property_images
  existing columns
  kind = listing_photo | floor_plan_diagram | other
  normalization_profile

floor_plan_images
  floor_plan_id
  property_image_id
  source_id
  association_method
  confidence
  evidence_context
  first_seen_at
  last_seen_at
  is_current
  primary key (floor_plan_id, property_image_id)
```

Exact column names remain an engineering choice. The approved constraints are:

- bytes remain stored once by content hash;
- associations may be many-to-many;
- an association carries provenance rather than being an unexplained foreign
  key;
- the image and target Floor Plan must belong to the same Property;
- automatic v1 associations must be from the same Source;
- service-role-only writes and authenticated reads follow the current global
  image/Floor Plan RLS posture;
- `split-property`, DEDUPE merge, refresh, and retention handle associations
  transactionally;
- a partial image fetch cannot delete prior known-good assets or associations;
- removed/replaced diagrams retain history while `is_current` controls ordinary
  display.

Use a separate stored-image budget for Floor Plan diagrams so ordinary photo
ordering and `MAX_STORED_IMAGES` do not evict useful diagrams found later in a
page. Likewise, adding diagrams must not increase the P3-7b quality-rating image
budget. Start diagram normalization at 2048 pixels with high-quality or
lossless WebP, subject to the required legibility fixture. Retain the normalized
asset plus Source URL, not a second full-size original, unless that fixture
proves the normalized representation inadequate.

### 7.4 Approved additional per-Floor Plan data

In addition to scoped amenities and diagrams, include these first-class fields
now because they support identity, refresh, or the detail UI:

- Source-native Floor Plan identifier and stable Floor Plan detail URL/anchor;
- Unit type(s), separate from the Property's types;
- pricing observation timestamp alongside the existing rent/sqft range;
- `first_seen_at` and `last_seen_at`;
- an explicit current/inactive marker derived from refresh evidence rather than
  destructive deletion;
- plan-specific evidence/provenance for every value;
- associated diagram order.

Keep these optional and populate them only when explicitly Floor Plan-specific:

- offered lease-term range;
- accessibility features;
- plan-specific mandatory fees and concession evidence.

Source-native Floor Plan ID and detail URL are nullable first-class columns,
not values hidden only in `raw`. User-selectable primary-diagram controls are
deferred; deterministic Source/display order is sufficient in v1.

Defer individual unit numbers, inferred room dimensions, floor level,
view/orientation, diagram OCR or interpretation, and individual-unit inventory.
A Floor Plan is not an individual physical unit, and inferred measurements from
a diagram would overstate precision.

Plan-specific concessions deserve care: storing the evidence and validity
window is useful, but composing them into rent or all-in cost is a separate
pricing decision because conditional promotions can make an apartment look
artificially cheap.

### 7.5 Image-specific validation

Required fixtures and checks:

- a Floor Plan card with one unambiguous diagram links correctly;
- one diagram explicitly shared across multiple Floor Plans creates multiple
  associations without duplicate bytes;
- several diagrams may link to one Floor Plan;
- an ambiguous diagram remains unmatched;
- a generic Property photo never becomes a Floor Plan diagram;
- `srcset` selects the best permitted source rather than a tiny thumbnail;
- normalized diagram text remains legible at supported viewport sizes;
- same bytes at a changed URL deduplicate;
- changed bytes at the same URL create a new asset/version and refresh the
  current association;
- a partial fetch cannot remove the prior diagram;
- an unchanged refresh performs no upload and creates no duplicate association;
- Floor Plan diagrams never enter kitchen/flooring VISION inputs;
- signed URL expiry or a missing object produces an image-level error state,
  not a broken Floor Plan detail surface;
- RLS prevents unauthenticated reads and client writes;
- DEDUPE merge and `split-property` preserve correct assets and associations.

## 8. Saved development Rubric

Add the version-controlled declarative fixture
`worker/fixtures/dev_rubric.v1.json` plus the idempotent
`manzil seed-dev-rubric` command for a dedicated development Hunt. The command
creates missing state, no-ops when the same template version is installed, and
refuses to overwrite locally modified Rubric state unless explicitly invoked
with `--force`. This is separate from the Phase 0 eval Rubric and separate from
the answer-driven starter Rubric used by real Hunts.

The dev Rubric should:

- exercise every supported catalog schema and frontend widget;
- enable the active extraction tranche;
- avoid Gates by default unless a named fixture tests Gate behavior;
- use stable options and expected score goldens;
- include examples of confirmed, advertised unconfirmed, none, and unknown;
- never become a production Hunt default;
- carry a template version so updates are deliberate and reviewable.

## 9. Decisions required before implementation

The approved Pass 10 checklist vocabulary is:

- `[x]` **Approved** — the decision and rationale are settled in this plan;
- `[-]` **Deferred** — not required for the approved tranche and accompanied by
  a named reconsideration trigger;
- `[ ]` **Blocking** — must be answered before the named phase begins.

Every unchecked item in §9.1 is a delegated engineering-design gate blocking
the scoped-fact substrate. Delegation identifies who decides it; it does not
waive the gate. Items in §9.2 may block only their named tranche. No production
implementation is authorized by the approvals recorded here, and §9.1 must
have no unchecked item before scoped-fact implementation starts.

### 9.1 Scoped-fact substrate decisions

- [x] **Scope vocabulary:** `property | floor_plan | mixed | composed`.
- [x] **Applicability vocabulary:**
  `specific_floor_plans | all_units | select_units | unit_scope_unspecified`.
- [x] **Generic amenity-list rule:** an unqualified unit amenity is
  `unit_scope_unspecified`, never `all_units`.
- [x] **Scoring uncertain availability:** select/unspecified maps
  to `advertised_unconfirmed` and cannot satisfy a confirmed-feature
  non-negotiable.
- [x] **Persistence implementation:** directly generalize the existing
  `extractions` table as the single append-only Property/Floor Plan fact store.
  Reset and reseed; do not add a transitional parallel scoped-extractions table
  or legacy-data backfill. Audit every current query before implementation so
  all code paths cut over atomically.
- [x] **Current-value identity:** Source claims use Property, nullable
  Hunt/custom Criterion scope, Criterion, Source, target scope, and target ID.
  Applicability is claim data, not a separate current lineage. A successful new
  observation supersedes the prior Source claim for that identity; reconciled
  effective values resolve across current Sources for the Criterion and target.
- [x] **Extraction response shape:** use sparse top-level unit-feature claims
  with Source-local Floor Plan references rather than embedding every optional
  Criterion inside every Floor Plan.
- [x] **Floor Plan reference:** use a generated response-local key validated
  against the same response and resolve it to a stable `floor_plans.id` only
  after Floor Plan upsert. Retain Source-native IDs separately when available.
- [x] **Shared claim persistence:** EXTRACT may emit one claim targeting several
  Floor Plans; persistence expands it to one row per Floor Plan for read/SCORE
  simplicity while retaining a common claim/evidence provenance identifier.
- [-] **Cross-Source plan matching:** deferred. Reconsider only if post-rollout
  Listing evidence shows Source-local mapping is materially insufficient.
- [x] **Override baseline:** exact Floor Plan and all-units Overrides plus
  revert-to-extracted behavior are required.
- [-] **Select/unspecified applicability correction:** deferred until real
  Curator usage demonstrates the need for this manual correction.
- [x] **Specificity conflicts:** exact Floor Plan evidence wins over a
  less-specific all-unit claim, with conflict provenance retained.
- [x] **Escalation/Gate interaction:** a Gate makes the effective policy
  `decision_relevant`; normal bounded reconciliation and escalation apply.
- [x] **Disagreement presentation:** a `verified_positive_preferred` result over
  credible negative evidence uses the quiet **Sources disagree** indicator, not
  the normal Problematic badge; all evidence remains visible.
- [x] **Refresh behavior:** unchanged content retains current claims; a
  successful complete Extraction appends the new Source claim set and retires
  superseded claims for refreshed fields; partial/failed work retains known-good
  claims. Silence retires to unknown rather than becoming `none`; only explicit
  negative evidence produces `none`. A Floor Plan becomes inactive only after a
  successful authoritative Source refresh proves its absence. History remains
  append-only.
- [x] **Source deletion/split:** `split-property` transactionally moves selected
  Sources, their Floor Plans, Source-local scoped facts, and image associations.
  Recompute reconciled Property facts, Unit Groups, availability, and scores on
  both resulting Properties; never copy a previously reconciled Property value
  onto both sides as truth.
- [x] **RLS/read exposure:** Catalog Floor Plan-scoped facts are global facts
  readable by authenticated users; Hunt custom-Criterion facts and Overrides
  remain Hunt-private. Automated writes remain service-role-only, human
  Override writes remain role-controlled, and diagrams retain private Storage
  access.

### 9.2 Catalog and product decisions

- [x] Approve the new `property` category.
- [x] First Property Criterion tranche: `pool`, `fitness_center`, `clubhouse`,
  `emergency_maintenance`, `maintenance_on_site`, `management_on_site`,
  `online_payments`, `online_maintenance_requests`, `package_handling`,
  `smoking_policy`, `property_types`, and Property-scoped
  `internet_readiness`.
- [x] Emergency-maintenance schema:
  `emergency_service | 24_hour_emergency | none`.
- [x] Generic `resident_portal` is display evidence; `online_payments` and
  `online_maintenance_requests` are the scoreable capability Criteria.
- [x] Pool schema:
  `indoor | outdoor | indoor_and_outdoor | unspecified | none`; private pools
  remain deferred and do not change Property-level pool semantics.
- [x] `property_types` and `unit_types` are arrays using the initial controlled
  vocabulary `apartment | condo | townhome | duplex | single_family | loft |
  other`.
- [x] Array match operators: `contains_any` means non-empty intersection;
  `contains_all` means the extracted set contains every configured value.
- [x] `property_types` uses explicit Property claims plus derived Floor Plan
  types, retaining disagreement rather than silently replacing either source.
- [-] `basement` is deferred. Reconsider after the first scoped-unit and
  mixed-scope tranches only if real Listing evidence shows material Hunt value;
  define private/shared and finished/unfinished semantics at that time.
- [x] `internet_readiness` is a Property-scoped boolean recording that a Source
  listing page advertises general internet, high-speed, or fiber readiness.
  Silence is unknown, not false. It does not assert Floor Plan-level service,
  provider serviceability, speed, connection type, or inclusion in rent;
  granular readiness and external serviceability checks are deferred.
- [-] `storage` is deferred. Reconsider after the first scoped-unit and Property
  tranches only if real Listing evidence shows material Hunt value; a future
  design must separate mixed physical type/scope from required or optional fees.
- [x] `flooring_materials` and subjective `flooring_quality` may both be
  enabled. Keep their semantics and scores independent, and show an explicit
  Rubric-editor warning about possible double-weighting.
- [x] Initial preference amenities in §4.2 default to
  `available_sources_only` + `verified_positive_preferred`; smoking policy,
  availability, costs/fees, pet eligibility, and Gate-bearing Criteria use
  `decision_relevant` + `standard_ladder`.
- [x] Escalation and conflict policies are Catalog defaults, not Owner-editable
  in v1; Gate decision relevance changes the effective escalation policy.
- [x] **Saved dev Rubric:** use a version-controlled declarative fixture at
  `worker/fixtures/dev_rubric.v1.json`, installed into a dedicated development
  Hunt by the idempotent `manzil seed-dev-rubric` command. It has no default
  Gates, includes stable fixture score goldens, records a template version, and
  refuses to overwrite local drift unless explicitly run with `--force`.

### 9.3 Floor Plan detail and image decisions

- [x] Clickable Floor Plan detail uses a nested modal on desktop and full-screen
  modal on mobile while the Listing draft remains mounted.
- [-] Floor Plan deep links are deferred until the modal experience has shipped
  and a concrete navigation or sharing need is demonstrated.
- [x] Approve `property_images` plus a many-to-many `floor_plan_images`
  association table rather than a single `floor_plan_id` column.
- [x] Automatic associations require explicit structured/card/native-ID/label
  evidence; the numerical confidence threshold remains a bench-derived
  engineering gate, with ambiguous candidates left unmatched.
- [x] Persistence supports manual association/disassociation with append-only
  attribution.
- [-] The Curator association UI is deferred until automatic coverage proves a
  material need for manual correction.
- [x] Unmatched diagrams appear in a separate **Unmatched Floor Plan diagrams**
  gallery and never attach to every Floor Plan.
- [x] **Floor Plan diagram storage caps:** start with at most three current
  diagrams per Floor Plan and thirty current Floor Plan diagrams per Property.
  Unmatched diagrams count against the Property cap. Prefer explicit
  associations, full-size candidates, and deterministic Source order. These
  caps remain separate from ordinary photo and VISION caps and may change only
  after the legibility/coverage fixtures justify a recorded implementation
  adjustment.
- [x] Start at 2048-pixel high-quality/lossless WebP, subject to the legibility
  fixture before the exact normalization profile is locked.
- [x] Retain the normalized asset plus Source URL, not a second full-size
  original, unless legibility testing proves inadequate.
- [x] Preserve deterministic Source/display diagram order.
- [-] User-selectable primary-diagram controls are deferred until real usage
  shows deterministic Source/display order is inadequate.
- [x] **Diagram refresh lifecycle:** unchanged or partial/failed discovery never
  retires an association. A successful complete Source refresh updates
  `last_seen_at` and marks a missing prior association non-current while
  retaining history. Reappearing identical content reactivates the existing
  content-hash asset/association; changed bytes create a new asset and retire
  the former association. Retain inactive bytes while the Property exists;
  explicit Property/image purge may remove objects no longer referenced.
- [x] Diagrams are categorically excluded from kitchen/flooring VISION.
- [x] Source-native Floor Plan ID and detail URL are nullable first-class
  `floor_plans` columns, not values hidden only in `raw`.
- [x] Include now: Unit type, pricing observation timestamp, `first_seen_at`,
  `last_seen_at`, current/inactive state, plan-specific provenance, and diagram
  order. Lease terms, accessibility, and plan-specific fees/concessions are
  optional only when explicitly tied to the Floor Plan.
- [-] OCR, inferred room dimensions, diagram interpretation, vision-based
  association, floor level, view/orientation, individual unit numbers, and
  individual-unit inventory are deferred until a separately approved feature
  demonstrates need and supplies its own accuracy contract.
- [x] **Third-party diagram posture:** retain only the normalized asset plus
  Source URL, attribution/provenance, and timestamps unless legibility fixtures
  require the original. Storage remains private and authenticated-Hunt-use only;
  do not expose permanent public URLs or republish diagrams. Preserve inactive
  evidence while its Property remains stored and provide an explicit purge path
  for unreferenced objects. Revisit before any public or multi-tenant posture;
  this is a product retention decision, not a legal conclusion.

### 9.4 Move-in-cost decisions

- [x] Time window: required cash from application through occupancy.
- [x] Reuse `first_month_all_in` to avoid double counting monthly components.
- [x] Use one full realistic first month when no exact/prorated payment schedule
  is stated.
- [x] Include explicitly required last-month/prepaid rent.
- [x] Include only the non-credited portion of a holding deposit; credited
  amounts attach to the component they satisfy rather than being counted twice.
- [x] Utility connection deposits and required insurance-initiation charges may
  enter the standard required-cost vocabulary when explicitly stated.
- [x] A materially incomplete known subtotal displays separately with an
  incomplete badge and scores unknown, never as a conservative lower bound.
- [x] Show refundable and non-refundable subtotals separately while both count
  toward cash required.

Estimated move-in cost remains a separate later workstream and does not block
scoped amenities or Floor Plan diagrams.

### 9.5 Operational decisions

- [x] **P3-6 boundary:** promote the design, land the unified scoped Extraction
  foundation, add the first Property tranche/dev Rubric, and migrate existing
  unit Criteria before P3-6 RECONCILE. P3-6 then reconciles the final scoped
  identity rather than a temporary Property-only contract.
- [-] **Temporary honesty guard:** omit it while the database remains resettable
  and no real Hunt data uses the old Property-only pipeline. Trigger and ship it
  immediately if real ingestion must resume before the scoped substrate lands.
- [ ] **Execution gate before the first scoped bench:** select and document the
  canonical ten frozen listings/cases containing exact, all-unit, select-unit,
  unqualified, negative, missing, shared-plan, and ambiguous/unambiguous diagram
  evidence.
- [x] Pass 11 release thresholds in §10.6 define acceptable scope-association,
  Gate-regression, schema-validation, ambiguity, partial-fetch, and cost
  behavior; report raw counts alongside percentages.
- [x] **Schema/token-budget rule:** measure the canonical bench, set structural
  caps above its observed high end with documented headroom, bound evidence
  length and output tokens, preserve core/Gate claims first on explicit
  truncation, and keep total live ingestion under NFR1. The measured constants
  are implementation outputs, not new product decisions.
- [x] **Model-pin dependency:** use the current pins as the scoped-schema
  baseline; do not block on P0-14. Rerun the affected bench if a later model-pin
  decision changes EXTRACT or VERIFY.
- [x] **Task placement/naming:** keep the work in Phase 3 as the distinct
  `P3-SC1`… scoped-criteria series. Explicit dependencies, rather than numeric
  adjacency, place `P3-SC1`–`P3-SC4` before P3-6 and the remaining tranches
  after P3-6. Do not renumber or overload existing P3-6/P3-7 identifiers.

### 9.6 Bench review scope and effort

The local eval kit currently contains twenty-one label JSON files, while the
formal Phase 0 target is the trimmed canonical ten and the tracked manifest is
not fully curated. Existing labels cover the old Catalog and basic Floor Plan
fields; they do not yet express scoped applicability, shared-plan claims, or
diagram associations. Do not relabel all twenty-one by default.

Expected work:

1. **Coverage audit and canonical-ten selection — 1–2 focused hours.** Inventory
   the existing frozen pages against exact/all/select/unspecified/negative/
   missing claims plus shared and ambiguous diagram cases; fill the manifest's
   page-trait and slot-rationale columns. Add a page only for a demonstrated
   coverage gap.
2. **Label-contract and harness extension — roughly 1–2 engineering days, after
   the scoped response contract exists.** Extend labels and grading for
   applicability, Source-local Floor Plan references, shared claims, abstention,
   and diagram association; keep CI synthetic and the real kit local.
3. **Human labeling/review — roughly 6–10 hours for ten pages.** Expect
   30–60 minutes per listing because plan-specific claims require checking page
   structure, asterisk legends, and image context rather than copying one value.
   One to three additional hours may be needed if the canonical ten lacks enough
   diagram examples.
4. **Recorded run and result review — roughly 2–4 active hours** after the code
   and labels are ready, plus unattended provider runtime. Run current pins,
   inspect every zero-tolerance error count, schema failure, truncation, token/
   cost figure, and Gate regression; rerun only affected stages after fixes.

Practical planning allowance: one short audit session now, followed later by
about **2–3 engineering days plus one human labeling day**. The audit may reduce
that estimate by showing that several existing pages cover multiple required
cases. Bench execution is an implementation/evaluation activity; it does not
block promotion of the finalized design into `DESIGN.md` and
`IMPLEMENTATION.md`.

## 10. Concerns and risks

### 10.1 Extraction reliability

- Models may infer plan applicability from visual proximity in cleaned text
  even when page structure was lost.
- Asterisks may be detached from their legend by the cleaner.
- Floor Plan names may collide, be omitted, or change on refresh.
- Requiring a full Criterion object for every Floor Plan would inflate output
  and schema-validation failures; sparse claims mitigate this.
- More fields can degrade accuracy on existing Gate Criteria. Bench the whole
  output, not only new amenities.
- Image/page structure can associate the wrong diagram with a nearby Floor Plan
  when cards are flattened or lazy-loaded; ambiguous candidates must fail to
  unmatched rather than guess.

### 10.2 Persistence and identity

- `floor_plans` are Source-specific. Treating similarly named plans from
  different Sources as identical without an explicit design would create a new
  DEDUPE problem inside the Property.
- Refresh must not strand facts on superseded Floor Plans or mint new IDs for a
  stable plan.
- Append-only history complicates “current” selection when a Source removes a
  plan or retracts an amenity. A tombstone/absence policy is required.
- Generalizing the existing Extraction table changes many latest-value queries,
  rescore, queue projection, split-property, API response, and frontend detail
  assumptions.
- Image assets are content-addressed while associations are time-varying. An
  authoritative refresh must retire stale associations without destroying
  evidence or allowing a partial fetch to erase valid history.

### 10.3 Scoring and UX

- A three-state effective value changes existing boolean Rubric options and
  requires migration of saved Hunt options.
- Existing scores must not silently reinterpret old `true` values as confirmed
  all-unit evidence. Historical values may need to become
  `unit_scope_unspecified` and trigger rescore.
- “Advertised; not confirmed for this Floor Plan” must remain understandable in
  Overview, Compare, breakdowns, and evidence UI.
- The best-plan behavior can magnify a false positive, so exact scope deserves
  dedicated golden tests.
- Overlapping Criteria such as portal/capabilities, flooring material/quality,
  and Property storage/unit storage can double-weight one underlying benefit.
- A nested detail interaction must preserve Listing draft state, pin state, and
  keyboard/mobile usability; replacing the Listing Drawer route state would be
  fragile.

### 10.4 Reconciliation

- `verified_positive_preferred` is deliberately biased and must be named in
  provenance; otherwise users may interpret it as consensus.
- A Source saying “no pool” may be stale while another positive is current, but
  the reverse is also possible. Freshness should be visible even when no
  escalation occurs.
- `available_sources_only` cannot be allowed to weaken Gate correctness.
- P3-6's bounded worst-case Source/extraction budget must remain intact.

### 10.5 Cost and schedule

- Catalog page-text additions enter every EXTRACT call because the full catalog
  is extracted regardless of the Hunt's enabled Rubric.
- Adding all proposed fields at once makes it difficult to attribute accuracy,
  latency, or schema failures.
- The apartment hunt benefits more from honest uncertainty on a small tranche
  than from a large catalog filled with falsely universal amenities.
- Floor Plan diagrams are cheap to store but need a separate discovery/storage
  cap; feeding them into the existing VISION slice would increase cost and harm
  rating relevance.

### 10.6 Approved release thresholds

The risks above are acceptable only with the following Pass 11 release gates:

- zero explicit `select_units` fixtures promoted to `all_units`;
- zero wrong automatic Floor Plan image associations in the labeled set;
- zero wrong exact amenity-to-Floor Plan associations in the labeled set;
- every ambiguous amenity or image association abstains and remains
  unspecified or unmatched rather than guessing;
- no regression in existing Gate correctness on the trimmed bench;
- no schema-validation regression unless a specific model or prompt change is
  explicitly approved and the resulting trade-off is recorded;
- total live new-Listing ingestion remains below NFR1's **$0.15 LLM+API cost
  ceiling**;
- a partial image fetch never removes a known-good diagram or association.

Abstention and reduced exact-association coverage are acceptable when needed to
meet the zero-wrong-association gates. Every bench report must show raw
numerators and denominators alongside percentages because the labeled corpus is
small. A tranche does not release merely because its aggregate percentage looks
acceptable if any zero-tolerance count is nonzero.

## 11. Phased implementation

### Phase 3 task identity and P3-6 boundary

Use a distinct scoped-criteria series rather than renumbering established Phase
3 tasks or calling unrelated work P3-5/P3-6 suffixes. `P3-SC` makes the
workstream visible while the dependency column supplies its actual order.

| Task | Scope | Dependency/order |
|---|---|---|
| `P3-SC1` ✅ | Promoted this plan into DESIGN + §20; audited all Extraction queries; recorded exact schema/current-value/reset contracts in IMPLEMENTATION (completed 2026-07-21) | Complete; prerequisite cleared |
| **`P3-SC2` ✅** | Unified append-only scoped Extraction foundation: schema/domain models, sparse claims, Floor Plan identity resolution, effective values, Overrides, refresh/split/RLS | Landed 2026-07-21; prerequisite cleared |
| **`P3-SC3` ✅** | Landed 2026-07-22: `property` category, array/set plumbing, Property/Unit types, first Property tranche including general internet readiness, and guarded saved dev Rubric | Complete; prerequisite cleared |
| **`P3-SC4` ◐** | Engineering landed 2026-07-27: existing unit Criteria use exact/all/select/unspecified semantics and the canonical bench contract/tooling is extended. Human label finalization and current-pin baseline remain | Acceptance tail is the hard prerequisite for P3-6 |
| **`P3-5` ✅** | Existing DISCOVER branch: native search, official/candidate Source links, tier/family slate, Source Policy enforcement | Landed 2026-07-21; its half of the P3-6 join is cleared |
| **`P3-6`** | Existing multi-Source fan-out and RECONCILE ladder, now operating on Property and scoped Floor Plan candidates | After `P3-SC4`; `P3-5` is complete; retain the established task ID |
| `P3-SC5` | Floor Plan detail UI and diagram discovery/association/storage/lifecycle | After `P3-SC2` and P3-7a; not a P3-6 prerequisite, so schedule after P3-6 on the critical path or in parallel once dependencies are met |
| `P3-SC6` | First new objective unit-feature tranche | After P3-6 so new Criteria enter the reconciled path rather than a temporary single-Source path |
| `P3-SC7` | Flooring materials and overlap warning; storage, basement, and granular internet remain deferred | After `P3-SC6` and the array plumbing established in `P3-SC3` |
| `P3-SC8` | Estimated move-in-cost composition | Separate later workstream after the selected Floor Plan/scoped-cost inputs are stable |

Run the relevant synthetic fixtures and local canonical bench after each
output-affecting tranche; do not postpone all evaluation until `P3-SC8`.
The next work is P3-SC4's human canonical-ten labeling/baseline tail. P3-6
remains blocked until it records zero wrong exact associations.

### P3-SC1 — finish and promote the design

**Completed 2026-07-21.** The authoritative result is DESIGN v3.7,
IMPLEMENTATION v2.0.68, and the P3-SC1 audit recorded in IMPLEMENTATION §7.

1. Update DESIGN §§3, 8.2, 9.2–9.6, 10.5–10.6, 13, 14, and 19 in place.
2. Append the material decision to DESIGN §20.
3. Audit every Extraction read/write/current-value path named in §3.4 and
   record the exact implementation contract in IMPLEMENTATION.
4. Convert `docs/catalog-and-rubric-review.md` from an unresolved review into
   an approved record or link it to the authoritative DESIGN decisions.
5. Add `P3-SC1`–`P3-SC8` to IMPLEMENTATION §7 with the dependencies and
   acceptance criteria in this section.

This prerequisite is now cleared. Production schema/code begins with P3-SC2;
P3-SC1 itself intentionally changed documentation and contracts only.

### Conditional temporary honesty guard

Omit this under the current clean-reset/no-live-ingestion assumption. If the
old Property-only pipeline must ingest real Hunt data before P3-SC2 lands,
immediately add the lossy guard and its select/unqualified fixtures, ensure such
claims cannot satisfy Gates, and rerun the Phase 0 bench.

### P3-SC2 — scoped Extraction substrate

**Completed 2026-07-21.** The authoritative result is DESIGN v3.9,
IMPLEMENTATION v2.0.71, and migration
`supabase/migrations/20260801000000_scoped_extraction_foundation.sql`.
P3-SC2 deliberately does not migrate the existing unit Criteria's claim
schemas or prompts; existing unit-like page facts are preserved as
`unit_scope_unspecified` until P3-SC4 performs that output-affecting tranche.

Reshape the existing table and update all audited consumers as one contract
change, reset the development database, and reseed it; do not build a
transitional dual-read or legacy-data backfill path.

1. Land target/applicability domain models and persistence.
2. Extend RunState with sparse unit-feature claims and Source-local Floor Plan
   references.
3. Validate every target reference before VERIFY/persistence.
4. Persist Floor Plans, resolve their IDs, then persist scoped facts in the
   same terminal projection transaction.
5. Extend VERIFY evidence, conformance, plausibility, and consistency checks.
6. Extend effective-value resolution and the pure SCORE input; keep the engine
   deterministic and LLM-free.
7. Add Floor Plan-scoped Overrides, API shapes, RLS, and UI controls.
8. Update rescore, refresh, split-property, and unavailable-plan handling.

### P3-SC3 — Property category, first tranche, and dev Rubric

**Completed 2026-07-22.** The authoritative result is DESIGN v3.10,
IMPLEMENTATION v2.0.72, migration
`supabase/migrations/20260802000000_catalog_sync_p3_sc3.sql`, and the current
Catalog/dev-Rubric mechanics recorded in IMPLEMENTATION §3. The saved Rubric
is `worker/fixtures/dev_rubric.v1.json`; `manzil seed-dev-rubric` installs it
into its deterministic development Hunt and requires `--force` to replace
Rubric drift.

1. Add `property` and array/set support to shared vocabulary, database
   constraints/catalog sync, API validation, scoring, and frontend grouping.
2. Add Property/Unit types plus the approved first Property tranche, including
   Property-scoped general `internet_readiness`.
3. Regenerate the catalog seed and add a catalog-sync migration.
4. Add the saved/versioned dev Rubric and idempotent seed command.
5. Add scoring, API, and frontend tests.
6. Keep production Extraction strict while adapting only the legacy synthetic
   seed/API replay helpers with explicit `not_found` Property values.
7. Leave the human-labeled scoped schema, canonical recording refresh, Gate
   regression report, and current-pin quality verdict in P3-SC4, where the
   existing unit Criteria acquire their final output semantics.

### P3-SC4 — migrate existing unit Criteria

**Engineering implementation landed 2026-07-27; human acceptance remains.**
The authoritative mechanics and status are in DESIGN v3.15 and IMPLEMENTATION
v2.0.78. The local audit currently finds ten gradeable legacy labels and eleven
unfinished skeletons, but none of the required scoped or diagram coverage
cases. Use `manzil bench-audit-scoped` while reviewing them; do not infer human
truth from old model output.

Move `patio_balcony`, `private_entry`, laundry, parking, cooling, dishwasher,
and heating through the scoped path before adding the long tail.

Required goldens:

- exact claim applies only to its target Floor Plan;
- one claim may target several Floor Plans and Unit Groups;
- explicit all-units applies to every current Floor Plan;
- select/unspecified becomes `advertised_unconfirmed`, not confirmed;
- page silence remains unknown;
- explicit none remains none;
- exact evidence beats less-specific evidence with provenance;
- a Floor Plan Override does not change siblings;
- best-versus-pinned Unit Group display uses the correct scoped values;
- reset/reseed fixtures and replay responses never reinterpret old
  Property-only booleans as confirmed all-unit claims.

Complete the §9.6 canonical-ten audit and scoped label/harness extension in this
task before declaring the current-pin baseline acceptable.

### P3-6 — scoped multi-Source integration

1. Add independent Criterion escalation and conflict policies to RECONCILE.
2. Reconcile Property claims separately from exact Floor Plan claims.
3. Do not reopen settled fields with escalation-round Sources.
4. Do not trigger escalation for `available_sources_only` unknowns/disputes.
5. Let Gate decision relevance follow the approved §4.1 rule.
6. Persist named resolution rules and all candidates.
7. Verify the P3-6 worst-case run remains within its Source/extraction budget.

### P3-SC5 — Floor Plan detail and image substrate

1. Extend image candidate discovery with structural/label context and the
   full-size candidate URL.
2. Add the approved diagram normalization profile and separate 3-per-plan /
   30-per-Property storage caps.
3. Classify explicit Floor Plan diagrams deterministically where possible;
   ambiguous diagrams remain unmatched.
4. Add `floor_plan_images`, its provenance/current-state fields, constraints,
   indexes, RLS, and private Storage integration.
5. Resolve Source-local plan references only after stable Floor Plan upsert and
   write associations in the terminal transaction.
6. Exclude Floor Plan diagrams from kitchen/flooring VISION inputs.
7. Add the clickable Floor Plan detail surface with plan facts, scoped
   amenities, evidence, score breakdown, diagram carousel/lightbox, pin state,
   Source link, loading/error/empty states, keyboard support, and responsive
   behavior.
8. Extend refresh, retention, DEDUPE merge, `split-property`, purge, and
   API/cache invalidation behavior.
9. Run the §7.5 fixtures, diagram-legibility comparison, and one real-listing
   smoke test containing an explicitly labeled Floor Plan diagram.

P3-SC5 is not a prerequisite for P3-6. It may begin in parallel after P3-SC2
and P3-7a, but remains after P3-6 in the default critical-path order.

### P3-SC6 — objective unit tranche

Add walk-in closets, pantry, disposal, fireplace, ceiling fans, and stainless
steel appliances. Each must have positive, negative, select-unit,
unqualified, and missing bench examples before an accuracy claim is made.

### P3-SC7 — flooring-material tranche

1. Add flooring materials using the array/set and `contains_any`/`contains_all`
   support established in P3-SC3.
2. Add the approved objective/subjective overlap
   warning. Storage and basement remain deferred under their §9.2 triggers;
   granular internet readiness remains deferred.

### P3-SC8 — estimated move-in cost

1. Implement a deterministic composer reusing the selected Floor Plan's
   `all_in_monthly`, deposit, fee checklist, one-time fee evidence, and Hunt
   household counts.
2. Persist component detail and completeness separately from the score
   breakdown, following the existing all-in pattern.
3. Add component-exact composer and SCORE goldens.
4. Display refundable/non-refundable totals and missing components.

### Measured rollout after every P3-SC tranche

For each tranche:

1. Audit frozen-page coverage before labeling.
2. Label all trimmed bench listings for every field whose accuracy will be
   reported.
3. Include explicit positive, negative, all-unit, select-unit, unspecified,
   exact-plan, and missing cases.
4. Refresh recordings intentionally; do not accept old-schema replay failures
   as validation.
5. Compare Gate accuracy, new-field accuracy, scope accuracy, invented-scope
   rate, tokens, latency, and schema-validation failures.
6. Run a real-Hunt smoke pass with the saved dev Rubric.
7. Promote the next tranche only after the prior tranche meets its thresholds.

## 12. Acceptance criteria for the overall change

- A Property amenity such as a shared pool appears for every Unit Group without
  pretending it is inside a unit.
- “Select units have balconies” never renders or scores as confirmed for every
  Floor Plan.
- A claim explicitly linked to two Floor Plans affects exactly those plans,
  even when they span Unit Groups.
- An unqualified amenities list displays “applicability unknown.”
- Floor Plan pinning changes displayed amenities and score consistently.
- A scoped Override corrects one Floor Plan without changing siblings.
- Every Floor Plan inside a Unit Group opens an accessible detail surface with
  that plan's own facts, amenities, evidence, score, and pin state.
- An explicitly associated Floor Plan diagram is stored privately as a
  content-addressed asset and appears only on its associated Floor Plan(s).
- An ambiguous diagram remains available as unmatched and is never shown as if
  it represents every Floor Plan.
- One diagram may serve several explicitly associated Floor Plans without
  duplicate stored bytes, and one plan may show several diagrams.
- Floor Plan diagram labels remain legible after normalization and diagrams do
  not consume kitchen/flooring VISION input budget.
- Refresh, DEDUPE merge, `split-property`, partial fetches, and retention do not
  orphan or silently misassociate Floor Plan diagrams.
- An `available_sources_only` disagreement consumes no additional fetch by
  itself; `verified_positive_preferred` selects only verified positive evidence
  and retains contrary evidence.
- Gate-bearing Criteria follow the explicitly approved safe reconciliation
  rule.
- Refresh/rescore/split-property preserve scoped provenance and stable Floor
  Plan identity.
- The scoring engine remains pure, deterministic, and covered by exact
  breakdown goldens.
- Every new LLM call remains behind the client seam and traced; EXTRACT and
  VERIFY extraction calls retain zero tools.
- The full-catalog schema stays inside the approved token/cost budget and does
  not materially regress existing Gate accuracy.

## 13. Explicit non-goals for the first version

- Private pools; pools remain Property amenities.
- Inferring exact Floor Plan applicability from photos alone.
- Cross-Source Floor Plan identity/merging.
- OCR, room-dimension inference, or vision-based Floor Plan diagram association.
- Individual physical unit inventory beneath a Floor Plan.
- Treating a Unit Group as a stored global fact owner.
- External ISP serviceability checks unless separately approved.
- Floor Plan-level or connection-type internet readiness; v1 records only the
  Property-scoped advertised readiness fact.
- Storage extraction or scoring until its post-tranche evidence trigger is met
  and its mixed-scope type/fee semantics are separately approved.
- Basement extraction or scoring until its post-tranche evidence trigger is
  met and its scope/type semantics are separately approved.
- Implementing unrelated DESIGN §18 backlog items.
- Making scoped amenities part of agents mode before workflow mode and its eval
  evidence are complete.

## 14. Finalized decisions summary

The approved/deferred package is:

1. Add the `property` category and independent `fact_scope` metadata.
2. Preserve specific/all/select/unspecified applicability.
3. Treat generic unit amenity lists as unspecified, not universal.
4. Implement source-local Floor Plan mapping; defer cross-Source plan matching.
5. Represent select/unspecified as `advertised_unconfirmed` and
   Gate-insufficient.
6. Store independent Catalog defaults for Criterion escalation
   (`decision_relevant` or `available_sources_only`) and conflict resolution
   (`standard_ladder` or `verified_positive_preferred`); a Gate makes the
   effective escalation policy `decision_relevant`.
7. Omit the temporary honesty guard under the clean-reset/no-live-ingestion
   assumption; ship it immediately if real Hunt ingestion must use the old
   Property-only path before P3-SC2 lands.
8. Add Property Criteria separately from scoped unit Criteria.
9. Migrate existing unit Criteria before adding the new unit-feature tranche.
10. Use arrays for Property/Unit types with
    `apartment | condo | townhome | duplex | single_family | loft | other` and
    the approved `contains_any`/`contains_all` match semantics; flooring remains
    in the later mixed-scope tranche.
11. Compose move-in cost from first-month all-in plus deposits and required
    one-time/prepaid charges, never double-counting monthly components.
12. Stop at source-local exact mapping for the current apartment hunt unless
    real evidence demonstrates that cross-Source Floor Plan matching is worth
    its additional complexity.
13. Make every Floor Plan clickable and show its plan-specific facts,
    amenities, provenance, score, pin state, and diagrams without unmounting the
    parent Listing detail draft; Floor Plan deep links are deferred.
14. Reuse content-addressed `property_images` assets and add a provenance-rich
    many-to-many `floor_plan_images` association table; do not use only a
    nullable `floor_plan_id` on the asset.
15. Discover and store explicit Floor Plan diagrams with a legibility-oriented
    normalization profile and separate cap; leave ambiguous diagrams unmatched
    and keep all diagrams out of kitchen/flooring VISION.
16. Keep one Overview row per Unit Group and enforce its two-layer contract:
    aggregates summarize the group, while plan-specific facts come only from
    the explicitly labeled Display Floor Plan (valid pin, otherwise best score).
17. Add first-class Source-native Floor Plan identity/link, Unit type, pricing
    observation time, lifecycle timestamps/state, provenance, and diagram order;
    defer individual-unit data, diagram interpretation/OCR, floor/view, inferred
    dimensions, and user-selectable primary diagrams.
18. Defer basement extraction and scoring until post-tranche Listing evidence
    demonstrates material Hunt value and its scope/type semantics are approved.
19. Under the clean-reset assumption, directly generalize `extractions` into
    the single append-only scoped fact store; use sparse claims, response-local
    Floor Plan keys, expanded per-plan rows, authoritative-success refresh, and
    one centralized current/reconciled lookup contract.
20. Add only Property-scoped, listing-advertised general internet readiness in
    v1; defer Floor Plan granularity and external serviceability checks. Defer
    storage until post-tranche evidence justifies its mixed-scope type/fee
    design.
21. Start Floor Plan diagrams at three current images per Floor Plan and thirty
    per Property, use authoritative-success lifecycle semantics, retain private
    attributed normalized assets while the Property exists, and support an
    explicit purge path.
22. Preserve existing P3-6/P3-7 meanings and use the `P3-SC1`…`P3-SC8` task
    series around P3-6, with `P3-SC1`–`P3-SC4` before reconciliation and later
    tranches after it or parallel only when dependencies permit.
