# Listing Detail Drawer — visual redesign

**Date:** 2026-07-23
**Status:** Design approved (visual direction signed off via Artifact preview); spec under review.
**Scope:** Presentation-only redesign of `ListingDetailDrawer` and its section sub-components. No domain-contract, scoring-engine, data-fetch, or persistence changes. Same information, same behavior (overrides, pins, fees, ratings, comments, save-on-close) — reorganized and restyled for at-a-glance legibility and less badge/whitespace clutter.

Sibling to the recently shipped job-card redesign; the two should read as one considered "Dusk & clay" system.

## Problem

Today `DrawerShell` renders seven equal-weight `Section`s (Score breakdown, Floor plans, All-in cost, Fees checklist, Ratings, Comments, Sources) in one undifferentiated scroll under the property name, address, and image carousel. Every section is the same visual weight, tables stack on tables, and many small badges compete for attention. Nothing leads the eye; it all blurs together.

## Approved direction (from the preview)

A **summary hero** followed by **five topic cards** on one scroll. Nothing is hidden behind tabs — all information stays visible — but a clear visual tier lets the eye land on what matters first.

### Hero (at-a-glance)
- Property name (Literata serif), address with a location pin.
- **Large primary image** (16:10) with prev/next overlay + `n / N` counter, and a **small fixed-size thumbnail filmstrip** (58px, same 16:10 aspect, cover-cropped never stretched, horizontally scrollable).
- **Three headline stat tiles:** Score (leads — colored by band, see below), All-in / mo (with the `~$est` portion), Home (beds/baths, e.g. "Studio · 1 bath").

### Five topic cards (in order)
1. **Why this score** — the criterion breakdown, reframed as an additive tally.
2. **Cost & fees** — the all-in composition and the fees checklist together (money in one place).
3. **Floor plans** — the pin/plan chooser.
4. **Notes & ratings** — ratings (yours + the team's) then comments.
5. **Sources** — deliberately the quietest card, at the bottom.

A card is a bordered, lightly-shadowed surface with a serif title and a quiet right-aligned hint (e.g. "13 criteria · 1 override").

## Scoring presentation (matches the engine — verified)

`shared` scoring engine domain (confirmed in `frontend/src/lib/contracts.ts` + `ScoreCell.tsx`): **base 10, clamp [0, 15]**, `criterion.delta` is additive. `scoreColor` bands are anchored on `total / base`, where "at or above base (10)" = `scoreHighest`. This is authoritative and unchanged.

- Headline score reads **`X / 15`** (never `/100`).
- **Above 10 = needs *and* wants met (exceptional):** rendered in the highest band color (`scoreHighest` → teal) with a `✦` mark. At/below 10, band color + label per the band table below.
- The **score card is an additive tally:** a "Baseline — all your needs met · 10.0" row at top, each criterion showing a signed **delta** (`+1.5` sage / `−2.0` brick / `0` neutral), landing at "Total score X / 15". A one-line legend explains the model.
- **Band → color + label** (decided). Labels are tied to the **same thresholds `scoreColor` already uses** (`total / base`, inclusive lower bound) so color and label never disagree. A pure `scoreLabel(total)` helper is added and unit-tested; `scoreColor` is refactored to share a single `scoreBand()` so the two stay in lockstep (its existing output is unchanged).

  | Total | Band (`scoreColor`) | Color | Label |
  |---|---|---|---|
  | ≥ 10 | scoreHighest | teal | **Exceptional Match** (✦) |
  | 8 to 10 | scoreHigh | sage | Strong Match |
  | 6 to 8 | scoreGood | olive | Acceptable Match |
  | 4 to 6 | scoreMid | ochre | Weak Match |
  | 2 to 4 | scoreLow | burnt clay | Poor Match |
  | < 2 | scorePoor | brick | Unacceptable |

  Because bounds are inclusive-lower (matching `scoreColor`), exactly `10.0` reads **Exceptional Match** (top band, teal) — consistent with "baseline 10 = all needs met" being the excellent floor. Confirmed with Yusuf 2026-07-23.

## Badge/clutter reduction (the core ask)

- Criterion rows: **color + position as meaning** — a signed delta column; **one `ⓘ`** per row holding all evidence + provenance (model, confidence, date, evidence quote, original-on-override) via HoverCard/Popover (reuse existing `EvidenceButton`).
- **Override** shown as a small **plum dot** + plum-tinted value, not a word badge (plum/grape = the "manual/human-entered" semantic). Revert affordance retained.
- Edge cases (`awaiting grade`, `sources disagree`, applicability) become **one quiet text flag**, not a pill pile-up.
- **Cost quality** (actual / estimated / unknown) becomes a small **colored dot at the front of each row** (sage / ochre / hollow), with a one-line legend; amounts stay flush to the right margin. Replaces the per-row `actual/est/unknown` badges.

## Section-by-section plan

Each item notes **reuse vs. restyle vs. new** and what changes. All keep their existing data hooks and mutation/draft behavior.

| Section | Component | Change |
|---|---|---|
| Hero | **new** `DrawerHero` | Composes name/address, the gallery, and the stat strip. Score tile uses `scoreColor` + new label helper. |
| Gallery | `PropertyImageCarousel` → restyle/replace | Large primary + small fixed-aspect thumbnail strip. Keep `images`, `loading` props and empty/loading states. |
| Why this score | `CriterionBreakdown` → restyle | Baseline row + signed-delta rows grouped Property/Floor-plan + total. Keep gate-fired Alert, override dot/revert, `OverrideControl`, `EvidenceButton`, draft overrides. Reduce badges per above. |
| Cost & fees | `AllInBreakdown` + `FeeChecklist` → restyle, combined into one card | Quality dots at row front; amounts flush right; all-in as a contained **result box** (not a splitting divider); "Monthly cost" / "Move-in & recurring fees" sub-labels; **utilities-included promoted** from footnote to its own tinted block. Keep `AllInOverrideControl`, fee assignment/household logic. |
| Floor plans | `FloorPlanPins` → restyle | Pin-icon rows; per-plan **score chip on the plan-name line** (band-colored); rent range + availability on the right; keep `"best"`/plan-id draft-pin radio semantics and `unit_types`. |
| Notes & ratings | `RatingControl` → **extend** + `CommentsSection` reuse | Your rating = 5-star **half-step** (`fractions={2}`); **team ratings list** (each member's avatar/name/stars/value + "Not rated yet" state + average) from the already-fetched `useRatings` (all users) joined with `useMembers`. Comments below a divider. |
| Sources | `SourcesList` → restyle | Compact one-line rows (dot, name, host, tier tag, open-link). Single-source-reason box only when exactly one source. Keep edit permissions + policy control. |
| Shell | `DrawerShell` | Replace `Section` stack with hero + card list. Keep drawer mount/close-intercept, dirty-state save bar (clay-tinted), discard-confirm modal, mobile/desktop title logic, all data hooks. |

## Architecture / boundaries

- New small, focused, independently-testable units: `DrawerHero`, `SectionCard` (shell wrapper), `scoreLabel`/band helper (pure), `StarRating` display (pure, half-step render), `TeamRatings` (list). Each has one clear purpose and reads its data via existing hooks/props.
- `Section` component may stay for other callers; the drawer stops using it. No unrelated refactors.
- CSS: follow the job-card precedent — CSS Modules + Mantine tokens (`--mantine-color-*`, radius, spacing), theme-aware via `:global([data-mantine-color-scheme="dark"])`. No hardcoded hex; colors come from the theme seam.
- Reduced-motion respected; keyboard focus visible on interactive chrome (gallery nav, pins, stars, info popovers).

## Error / edge states (preserved)
- Not scored / unavailable / gate-fired → existing copy and Alert.
- Loading (extractions, images) → existing loaders.
- Missing group (unavailable listing) → existing guarded messaging.
- Empty ratings/comments/sources → graceful empty states.

## Testing (TDD, per project rules)
- **Pure helpers** unit-tested: `scoreLabel`/band mapping (boundaries: 0, <10, =10, >10, 15), half-step star fill math.
- **Component tests** (Vitest + RTL): hero renders score/all-in/beds; `CriterionBreakdown` shows baseline + deltas + total and a single evidence affordance per row; cost dots + flush amounts + result box + utilities block; floor-plan score chip on name line + pin selection; team ratings list incl. "not rated" + average + half-step; compact sources + single-source reason only when one source; save bar appears when dirty.
- **No live LLM/network**; existing fixture/mock patterns. Frontend `pnpm -C frontend test | build | lint` all green.
- Visual verification: Playwright screenshots (light + dark) against a seeded listing, per the established workflow.

## Non-goals
- No changes to scoring, extraction, data contracts, endpoints, RLS, or persistence.
- No new information beyond what the drawer shows today (plus surfacing already-fetched team ratings).
- Not touching other `Section` consumers or the Overview table.

## Resolved decisions (2026-07-23, with Yusuf)
- **Score label bands** — decided; see the band table under "Scoring presentation."
- **Gradients** — kept **flat**, honoring the existing `frontend/AGENTS.md` "flat colors only" rule. The score tile uses a flat band-colored tint (`color-mix` of the band color into the card), not a wash.
- **CSS Modules** — formally permitted (Mantine-first, CSS Modules where warranted). The job-card redesign already established this. Captured in the new `frontend/UI_DESIGN.md`; the `frontend/AGENTS.md` "no bespoke CSS files" bullet is updated to point there.
- **Where this is logged** — a new working document, `frontend/UI_DESIGN.md`, holds the frontend design philosophy **and** a UI decision log. This redesign is its first substantive entry. Not a DESIGN.md §20 entry (intent/contracts unchanged); DESIGN §13 still owns frontend design *intent*.
