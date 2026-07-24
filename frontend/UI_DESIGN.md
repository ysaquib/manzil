# Manzil — UI Design & Development

Working document for how the Manzil frontend **looks, feels, and is built**. It is the home for the
design philosophy and the **UI Decision Log** (bottom). It is deliberately practical: read it before
building or reshaping any surface.

**Where this sits in the hierarchy**
- `DESIGN.md §13` owns frontend **design intent** (what the surfaces are for). Authoritative on intent.
- Repo-root `AGENTS.md` + `frontend/AGENTS.md` own the **hard rules** (contracts, data layer, phase discipline).
- **This doc** owns the **craft**: visual language, component approach, consistency patterns, and a log of UI changes and why. When this doc and a `frontend/AGENTS.md` design bullet drift, this doc is the current word and the AGENTS bullet should be updated to point here.

---

## 1. Design philosophy

**"Dusk & clay."** *manzil* means home — a stage of a journey, arriving somewhere at dusk. The UI
should feel **warm, calm, and characterful**, not generic SaaS. (DESIGN §20, 2026-07-09.)

Guiding principles (Refactoring UI, adapted):
- **Hierarchy through weight, size, and warm-gray shade — not decoration.** Labels are lighter than
  data. De-emphasize secondary content instead of emphasizing everything.
- **Whitespace and grouping first.** Group with spacing and bounded **cards**; reach for divider
  lines sparingly.
- **Constrained, semantic palette.** Every color has a role and comes from the theme. Warm neutrals
  everywhere; one warm accent (clay); earthy status hues (moss/olive/ochre/brick). No electric colors.
- **Flat, not glossy.** Flat colors only — no gradients (backgrounds, buttons, badges, charts, score
  tiles). Depth comes from a restrained shadow scale and borders, not washes.
- **Serif for identity, sans for work.** Literata (serif) for headings/wordmark; Source Sans 3 (sans)
  for body; JetBrains Mono for figures/code. Tabular numerals wherever digits align in columns.
- **Plain-spoken, warm microcopy.** Empty/loading/error states speak plainly; controls say exactly
  what they do.

## 2. The theme is the single styling seam

- **`src/theme.ts` + `src/colors.ts` are the source of truth** for color, spacing, radius, shadow,
  and component default props. Components read **tokens** (`var(--mantine-color-*)`, `gray.6`,
  semantic role names) and **never hardcode hex**.
- Palette is defined once in `colors.ts` (named scales: `warm_stone`, `dark_dusky`, `dusky`,
  `sage`, `olive`, `muted_ochre`, `burnt_clay`, `dusty_brick`, etc.) and mapped to Mantine slots +
  score roles in `theme.ts`. Swap a role there, not per-usage.
- **Dynamic color** follows the `scoreColor`/`scoreBand` pattern: a pure function returns a Mantine
  **color name**, never a hex. Any new "color by value" logic does the same and is unit-tested.

## 3. Components: Mantine-first, CSS Modules where warranted

**Default to Mantine.** Compose from `@mantine/core` primitives (`Card`, `Stack`, `Group`, `Table`,
`Badge`, `Rating`, `Drawer`, `Popover`, `HoverCard`, …) and set look via **props + theme default
props**. Most surfaces need no custom CSS at all.

**Primitives over raw `<div>`s.** A bare `<div>` (or `<span>`/`<p>`) in a `.tsx` is a smell — reach
for the primitive that names the intent instead: `Box` (styled div), `Stack`/`Group` (flex column/
row), `SimpleGrid` (equal-column grid), `Paper`/`Card` (bordered surface), `AspectRatio` (ratio box),
`Text`/`Title` (typography). Fewer, semantic nodes read better, and typographic roles ride props
(`c="dimmed"`, `fw={600}`, `tt="uppercase"`, `ff="heading"`) that resolve through the theme rather
than restating colors/weights in CSS. Drop to a co-located `*.module.css` only for what props can't
express (see below), not for ordinary layout or text. (RefactoringUI: hierarchy and grouping come
from semantic structure + spacing, not from nesting anonymous boxes.)

**Don't hand-roll what Mantine ships.** Use the packaged component and restyle it to spec rather than
rebuilding it: `@mantine/carousel` for image/content carousels (never a bespoke scroll-snap strip),
`@mantine/dates` for date inputs, `@mantine/notifications` for toasts, `@mantine/modals` if a confirm
helper is wanted (raw `<Modal>` is already fine). One genuinely-custom exception in the drawer:
`ImageLightbox` stays hand-built because it is a full-screen **zoom viewer**, not a carousel.

**Reach for a co-located `*.module.css` file when** the design genuinely needs something the props
API doesn't express cleanly:
- bespoke layout (CSS grid tracks, `min-width:0` overflow control, sticky/pinned footers),
- state-driven visuals (pulse/shimmer/`data-*`-keyed styles, meters, sub-pips),
- fine control the theme can't reach (precise track/dot geometry).

Rules for module CSS (so it stays consistent and themable):
- **Colors are always tokens**, never raw hex: `var(--mantine-color-sage-6)`,
  `var(--mantine-font-family-monospace)`; `color-mix(in srgb, var(--mantine-color-...) N%, …)`
  is fine for tints.
- **Anchor spacing and font-size to the scale.** `margin`/`padding`/`gap` and `font-size` values
  that fall within the Mantine scale use the token var (`var(--mantine-spacing-*)`,
  `var(--mantine-font-size-*)`) so they track `theme.ts` — snap to the nearest step. Use an explicit
  value **only** when the size is *intentionally* outside the scale (below `xs` or above `xl`) or is
  a calculated/optical one-off (a hanging indent that must equal dot+gap, a display numeral) — and
  then prefer **rem** over px. Scale, for reference: spacing `xs`=10 · `sm`=12 · `md`=16 · `lg`=20 ·
  `xl`=32; font `xs`=12 · `sm`=14 · `md`=16 · `lg`=18 · `xl`=20 (px). Never override a themed `Card`'s
  radius with a bespoke value.
- **Optical geometry stays explicit.** Dot/track/pip/avatar pixel sizes, `border-width`,
  `letter-spacing`, `line-height`, and fixed grid-column widths are not spacing/font tokens — leave
  them as tuned px/rem (see `PipelineTrack.module.css`/`HistoryCard.module.css`). The hard rules are
  colors (always tokens) and in-range spacing/font (always tokens); optical geometry is the
  deliberate exception.
- **Theme-aware** via `:global([data-mantine-color-scheme="dark"]) .foo { … }` (no
  `postcss-preset-mantine`, so no `light-dark()` mixin). Audit both schemes.
- Keep modules **co-located** with their component and scoped to it. No global stylesheets, no app-wide
  CSS layer, no inline hex in `.tsx`.
- Respect `prefers-reduced-motion`; give interactive chrome a visible focus state.

Reference implementations: `features/jobs/PipelineTrack.module.css`,
`features/jobs/HistoryCard.module.css`.

## 4. Consistency patterns (reuse these)

- **Section card.** A bordered, lightly-shadowed surface: serif title (order 5-ish) on the left, a
  quiet dimmed hint on the right, content below. Group related content into a few cards rather than
  many equal-weight sections.
- **Summary hero + detail.** For dense detail surfaces, lead with an at-a-glance hero (identity +
  the few headline stats, the leading stat visually strongest) then calmer detail cards. One scroll;
  nothing hidden behind tabs.
- **Score display.** `X / 15`, colored by `scoreColor`, labeled by `scoreLabel` (same bands). `✦`
  marks the exceptional (≥10) band. Additive breakdowns show a baseline row → signed deltas → total.
- **Quiet status markers over badges.** Prefer a small **colored dot** + a one-line legend, or a
  single `ⓘ` affordance holding detail on hover, over stacking word-badges. Color and position carry
  meaning. Plum/grape = manual/human-entered (overrides); sage/ochre/hollow = actual/estimated/unknown.
- **Affordance hierarchy.** Frequent/important actions are always visible (primary `Button`,
  persistent controls). Rare/destructive actions are tucked but reachable (`Menu`, `Tooltip`/
  `HoverCard` for provenance, confirm `Modal` for destructive). Nothing important lives only behind a
  hover; nothing rare occupies prime real estate.

## 5. Responsive, dark mode, accessibility

- **Phone-first (~375px) always.** Detail is a right `Drawer` on mobile and desktop; tables hide
  secondary columns or stack; forms/steppers stack. Mantine breakpoints + `useMediaQuery` — no bespoke
  media queries in TSX. **No horizontal page scroll, ever** — wide content scrolls inside its own
  container.
- **Dark mode via Mantine.** `defaultColorScheme="auto"`; header toggle persists `light`/`dark`
  (`manzil-color-scheme`); pre-mount script prevents flash. Contrast fixes go through `theme.ts`
  (`autoContrast`, `primaryShade`), not per-component hex. Audit every new surface in both schemes.
- **Accessibility.** Visible keyboard focus; `aria-label` on icon-only controls; interactive things
  look interactive; honor reduced motion.

## 6. Data & testing (pointers)

- Server state via TanStack Query only; render persisted `scores.breakdown` directly (never recompute
  client-side). Mutations invalidate keys. See `frontend/AGENTS.md` for the two-client split and
  `frontend/API_ASSUMPTIONS.md` for endpoint assumptions.
- **TDD.** Vitest + Testing Library, co-located `*.test.tsx`; pure view-model/helper logic
  (`scoreColor`, `scoreLabel`, phase mappers, star-fill math) is unit-tested at boundaries. No snapshot
  tests. Visual changes are screenshot-verified in both themes.

---

## UI Decision Log

Newest first. Each entry: what changed, and why.

| Date | Change | Why |
|---|---|---|
| 2026-07-24 | **Drawer polish + Mantine-hardening pass** (`dev-phase3`). (1) Star ratings now take the member's color, yellow fallback (`starColorCss`). (2) `DrawerHero` recomposed from raw `<div>`s onto `Box`/`Text`/`Group`/`Title` primitives (typographic roles → props), output unchanged. (3) Token-anchoring tightened and swept across the drawer's module CSS — in-range spacing/font now use `var(--mantine-spacing-*)`/`var(--mantine-font-size-*)`; §3 rules updated. (4) The hand-rolled carousels (`DrawerImageGallery`, `PropertyImageCarousel`) rebuilt on **`@mantine/carousel`**; `ImageLightbox` kept custom (zoom viewer). (5) Tests relocated to the flat `frontend/tests/` dir. New §3 rules: *primitives over raw divs*, *anchor spacing/font to the scale*, *don't hand-roll what Mantine ships*. | Follow-up review of the shipped drawer: raw-div soup and off-scale pixel values were hard to maintain and couldn't be driven from `theme.ts`; a hand-rolled carousel duplicated a packaged component; star color carried no member identity. |
| 2026-07-23 | **CSS Modules formally permitted** (Mantine-first, `*.module.css` where warranted; §3). Updates the older `frontend/AGENTS.md` "no bespoke CSS files" absolute, which the job-card work had already outgrown. Gradients remain **flat-only**. | Some layout/state visuals (pipeline track, meters, overflow control) can't be expressed cleanly through Mantine props; a scoped, token-driven module is clearer than prop gymnastics, without giving up theme consistency. |
| 2026-07-24 | **Listing Detail Drawer redesign** (shipped; commits `300b48e..cc1d299` on `dev-phase3`, interleaved with an unrelated locality feature). Seven equal-weight `Section`s → a **summary hero** (name/address, large primary image + thumbnail filmstrip, score/all-in/beds tiles, score tile flat-tinted by band with a `✦` on ≥10) + **five topic cards** (Why this score · Cost & fees · Floor plans · Notes & ratings · Sources) built on the new `SectionCard`. Additive score tally (baseline 10 → signed deltas → `X / 15`); shared `scoreBand`/`scoreColor`/`scoreLabel` so color+label never disagree; badge declutter (state dots + one `ⓘ`/row + plum override dot); all-in result box; promoted sage utilities block; per-plan score chips; 5-star half-step ratings showing the whole team + average; compact multi-source rows. Presentation-only — no contract/scoring/data changes. Built via subagent-driven TDD (11 tasks, each spec+quality reviewed); 226 frontend tests + build + lint green. Spec: `docs/superpowers/specs/2026-07-23-listing-detail-drawer-redesign-design.md`; plan: `docs/superpowers/plans/2026-07-23-listing-detail-drawer-redesign.md`. | The drawer holds the most information and read as clutter (equal weight, stacked tables, badge pile-ups). It deserved a clear hierarchy: scan the headline, drill into calm grouped detail. |
| 2026-07-22 | **Job cards redesign** (Tasks page). Unified active/history cards on a shared five-phase `PipelineTrack`; status → colored dot + legend (fewer badges); history retry; expandable run-detail timeline; compact stop control on active cards. First substantial use of co-located CSS Modules. | The old cards showed raw stage text and lacked a retry path; the pipeline needed a legible, alive visual and a consistent language across active/history. |
| 2026-07-09 | **Visual identity: "Dusk & clay"** (DESIGN §20). Muted dusk-indigo primary, warm neutrals (stone light / charcoal dark), clay accent for waiting, earthy status hues, Literata + Source Sans 3 self-hosted, tabular numerals, sentence-case badges. All through `theme.ts`. | The UI read as generic SaaS defaults; *manzil* deserves warmth and character. Token-level identity is what the single theme seam exists for. |
