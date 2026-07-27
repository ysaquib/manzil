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
- **Data honesty over visual optimism.** Extracted, estimated, unknown, disputed, and human-overridden
  values remain distinguishable. Never make uncertainty quieter than the decision it can affect.
- **Design for the decision.** Dense screens should answer “what matters, what changed, and what can I
  do next?” at a glance. Progressive disclosure may hide supporting detail, never the current state,
  primary action, blocking error, or consequence of an action.

## 2. The theme is the single styling seam

- **`src/theme.ts` + `src/colors.ts` are the source of truth** for color, spacing, radius, shadow,
  typography, and component default props. Components consume Mantine props or CSS variables
  (`c="dimmed"`, `p="md"`, `shadow="sm"`, `var(--mantine-color-*)`) and **never hardcode hex**.
- Palette is defined once in `colors.ts` (named scales: `warm_stone`, `dark_dusky`, `dusky`,
  `sage`, `olive`, `muted_ochre`, `burnt_clay`, `dusty_brick`, etc.) and mapped to Mantine slots +
  score roles in `theme.ts`. Swap a role there, not per-usage.
- **Prefer the most semantic token available:** a component default or semantic role first, then a
  named Mantine palette value, then a raw Mantine CSS variable. Hardcoded color, spacing, radius,
  shadow, or ordinary font-size values inside a feature are the exception, not a parallel system.
- If the same visual choice appears across components, promote it to a component default, shared
  component, or named theme role. Do not copy an inline style or CSS declaration around the app.
- **Dynamic color** follows the `scoreColor`/`scoreBand` pattern: a pure function returns a Mantine
  **color name**, never a hex. Any new "color by value" logic does the same and is unit-tested.

## 3. Components: Mantine-first, CSS Modules where warranted

**Default to Mantine.** Compose from `@mantine/core` primitives (`Card`, `Stack`, `Group`, `Table`,
`Badge`, `Rating`, `Drawer`, `Popover`, `HoverCard`, …) and set look via **props + theme default
props**. Most surfaces need no custom CSS at all.

**Mantine primitives over raw structural HTML.** Use `Box`, `Stack`, `Group`, `Flex`, `SimpleGrid`,
`Paper`/`Card`, `AspectRatio`, `Text`, and `Title` instead of bare `<div>`, `<span>`, or `<p>` nodes.
Use Mantine's polymorphic `component` prop when the DOM needs a landmark or semantic element
(`Box component="section"`, for example). Raw HTML is reserved for a semantic element with no useful
Mantine equivalent (`pre`/`code` are common examples) or an integration that requires a literal DOM
node. It is not a shortcut for layout. Likewise, never use a styled `Box` as a button, link, input,
or table cell when the real interactive or semantic component exists.

**Use this styling order:**

1. **Theme defaults and component props** — `size`, `variant`, `color`, `gap`, `p`, `radius`,
   `shadow`, `visibleFrom`, and similar APIs.
2. **Mantine style props or a one-off inline `style`** for a root-only adjustment that belongs to
   exactly one instance. A single `miw={0}` or `style={{ fontVariantNumeric: "tabular-nums" }}` is
   clearer than creating a class solely for that declaration; a one-off type adjustment should stay
   on `Text` (`size="xs"` or, for the documented sub-`xs` exception, `fz="0.625rem"`).
3. **The component `styles` API** when one Mantine component needs adjustments to its internal slots.
4. **A co-located CSS Module** when selectors, pseudo-states, keyframes, complex layout, or several
   coordinated declarations make inline styling harder to understand.
5. **A shared component or theme rule** once a pattern repeats or becomes part of the product
   language.

Inline styling follows the same token rules as CSS. Do not create a class for one ordinary
declaration, and do not keep growing a dense `style={{ ... }}` object after the styling has acquired
states, selectors, or a reusable concept. Runtime-computed visuals should pass a token, Mantine color
name, or CSS custom property into a stable component style rather than generate arbitrary CSS.

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

- **Colors are always tokens**, never raw hex: `var(--mantine-color-sage-6)` or a semantic variable
  such as `var(--mantine-color-default-border)`. `color-mix()` is acceptable for a genuinely derived
  tint when Mantine does not already expose the needed light/fill variable.
- **Use Mantine scales for nearly all visual values.** Prefer named component props in TSX and the
  matching variables in CSS or inline styles: `var(--mantine-spacing-*)`,
  `var(--mantine-radius-*)`, `var(--mantine-shadow-*)`, `var(--mantine-font-size-*)`, and
  `var(--mantine-font-family-monospace)`. This applies to margin, padding, gap, surface radius,
  elevation, and typography; snap to the nearest scale step instead of inventing a nearly identical
  value. Never override a themed `Card` radius or shadow with a bespoke value.
- **Sub-`xs` type is the narrow exception.** Use it only for nonessential micro-labels or constrained
  visualizations where Mantine `xs` cannot fit; it must not carry a primary action, form instruction,
  error, or decision-relevant value. Set it in `rem`, in `0.125rem` increments below `0.75rem`
  (`0.625rem`, then `0.5rem`) — never arbitrary values such as `0.68rem`. For larger text, use the
  Mantine text scale or an appropriate themed `Title`; if a new display size truly recurs, add it to
  the theme instead of hardcoding it in a feature.
- **Optical geometry stays explicit.** Dot/track/pip/avatar pixel sizes, `border-width`,
  `letter-spacing`, unitless `line-height`, and fixed grid-column widths are not spacing/font tokens.
  They may remain tuned px/rem values (see `PipelineTrack.module.css`/`HistoryCard.module.css`) when
  snapping to a space token would change the geometry's meaning. A focus or pulse ring expressed
  through `box-shadow` is also geometry; ordinary surface elevation still uses the shadow scale.
- **Theme-aware** via `:global([data-mantine-color-scheme="dark"]) .foo { … }` (no
  `postcss-preset-mantine`, so no `light-dark()` mixin). Audit both schemes.
- Keep modules **co-located** with their component and scoped to it, except a **composed surface** (e.g. Listing Detail Drawer) may own one token-driven `ListingDetailDrawer.module.css` imported by its dedicated child sections; each child still keeps unique layout/state geometry in its own module. No global stylesheets, no app-wide CSS layer, no inline hex in `.tsx`.
- Respect `prefers-reduced-motion`; give interactive chrome a visible focus state.

Reference implementations for an appropriate CSS Module boundary:
`features/rubric/CriterionViewCard.module.css` and `features/rubric/CriterionPicker.module.css`.

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
  single `ⓘ` affordance with accessible detail, over stacking word-badges. Plum/grape =
  manual/human-entered (Overrides); sage/ochre/hollow = actual/estimated/unknown. Color reinforces
  the state but never carries it alone: pair it with text, shape, position plus a visible legend, or
  an accessible name.
- **Affordance hierarchy.** Frequent/important actions are always visible (primary `Button`,
  persistent controls). Rare/destructive actions are tucked but reachable (`Menu`, `Tooltip`/
  `HoverCard` for provenance, confirm `Modal` for destructive). Nothing important lives only behind a
  hover; nothing rare occupies prime real estate.
- **Complete state design.** Every data surface defines loading, empty, partial/stale, error, and
  success states. Preserve the existing layout during background refetches; use `Skeleton` for
  first-load structure, local errors with a relevant retry action, and purposeful empty states that
  explain the next step. Do not replace an entire usable page with a spinner for a local mutation.
- **Forms protect momentum.** Use Mantine inputs with visible labels, concise help only where needed,
  inline validation near the field, and explicit saving/saved/error feedback. Disable an action only
  when the reason is apparent; use confirmation for destructive or difficult-to-reverse actions, not
  routine edits.

## 5. Responsive, dark mode, accessibility

- **Phone-first (~375px) always.** Detail is a right `Drawer` on mobile and desktop; tables hide
  secondary columns or stack; forms/steppers stack. Prefer Mantine responsive props,
  `visibleFrom`/`hiddenFrom`, and theme breakpoints; use `useMediaQuery` only when behavior or rendered
  structure must change, not for ordinary styling. **No horizontal page scroll, ever** — wide
  content scrolls inside its own labeled container.
- **Dark mode via Mantine.** `defaultColorScheme="auto"`; header toggle persists `light`/`dark`
  (`manzil-color-scheme`); pre-mount script prevents flash. Contrast fixes go through `theme.ts`
  (`autoContrast`, `primaryShade`), not per-component hex. Audit every new surface in both schemes.
- **Interaction targets.** On touch layouts, primary controls and icon-only actions should provide a
  comfortable target (normally at least `2.75rem` in both dimensions), even when the visible icon is
  smaller. Keep adequate separation between adjacent destructive and routine actions.
- **Accessibility is structural.** Preserve heading order and landmarks; use real buttons, links,
  labels, lists, and table semantics; add accessible names to icon-only controls; keep focus visible;
  return or move focus sensibly when Drawers and Modals close; and announce meaningful async results
  through Notifications or an appropriate live region. Tooltip/HoverCard content must also work by
  keyboard and touch, and essential information must exist outside hover. Honor reduced motion.

## 6. Data & testing (pointers)

- Server state via TanStack Query only; render persisted `scores.breakdown` directly (never recompute
  client-side). Mutations invalidate keys. See `frontend/AGENTS.md` for the two-client split and
  `frontend/API_ASSUMPTIONS.md` for endpoint assumptions.
- **TDD.** Vitest + Testing Library tests live in the flat `frontend/tests/` directory. Test behavior
  through roles and accessible names; pure view-model/helper logic (`scoreColor`, `scoreLabel`, phase
  mappers, star-fill math) is unit-tested at boundaries. No snapshot tests. Visual changes are
  screenshot-verified at phone and desktop widths in both themes; keyboard-check every changed
  interaction.

## 7. UI review checklist

Before considering a surface complete:

- Mantine supplies the components and structure; any raw HTML or hand-built control has a concrete
  semantic or integration reason.
- Styling followed the escalation order, uses Mantine tokens, and introduces no repeated one-off
  values or arbitrary sub-`xs` typography.
- Hierarchy makes the primary information and next action obvious without hiding uncertainty,
  errors, or consequences.
- Loading, empty, partial/stale, error, success, and permission-appropriate states are intentional.
- The surface works at ~375px and desktop width, in light and dark schemes, with keyboard-only
  navigation, visible focus, and no color-only meaning.
- Behavior has focused tests; changed visuals have been inspected rather than approved from code
  alone.

---

## UI Decision Log

Newest first. Each entry: what changed, and why.

| Date | Change | Why |
|---|---|---|
| 2026-07-26 | **Map surfaces** — a `Location` card near the bottom of the Listing Detail Drawer and a `Map` tab at `/h/:huntId/map` (DESIGN §20 2026-07-26, `features/map/`). Both render Google Maps through `MapFrame`, which owns the four non-map states (no key / loading / failed / empty) so they can't drift apart. **Colour comes from the theme, not from the vendor**: marker fills, outline, and the dark basemap are read out of `--mantine-color-*` custom properties at paint time (`mapTheme.ts`), so score pins use the same `scoreColor` bands as the table and the chrome tracks `theme.ts` in both schemes. The pin outline **inverts against the basemap** — black on the pale light map, white on the charcoal dark one — rather than matching the page body, because the marker's job is to separate from the map beneath it, not from the surrounding chrome — the one place literal colours appear is the basemap `styles` array, which a raster map cannot take CSS variables for. No cloud Map ID, deliberately: that would move styling into a Google console and out of the repo. **Pin colour carries the honest fact, and only colour does**: one pin is one Listing, and a property whose Unit Groups land in different bands is *sliced* into equal sectors (best at 12 o'clock, hairline dividers) rather than averaged — the rule is the same one behind `scoreBand`/`scoreLabel`, that colour must never claim something the number doesn't. Solid and sliced pins are one silhouette at one size with one anchor; a test pins that equality. The marker is a single teardrop path (head and point share one continuous outline, and the slices are clipped to it so the point takes its share of the colour) — an earlier revision drew a circle plus a separate triangle with a hub dot on split pins, which clipped the point off, cut a visible arc across the neck, and made sliced pins read as a different kind of object. Clicking a multi-group pin opens a `Modal` picker (group label, rent range, band-coloured score badge) before the drawer, matching §9.4's rule that the Unit Group is the entity users curate. Pins whose data doesn't exist are stated, not hidden: an omission footnote counts "not scored yet" separately from "no mapped location". The drawer card doesn't repeat the address already in the drawer header. Filter state moved from `OverviewPage` into a hunt-keyed provider (`filterState.tsx`) so the Map and the table filter identically. | The app could only answer "where is this?" as a line of text. The two questions a map is actually for — where is this one, and where are all of them relative to each other — map exactly onto a card in the drawer and a tab of its own. Everything else was a refusal to spend: no new vendor, no new dependency, no geocoding, and no invented average score. |
| 2026-07-26 | **Overview table + row list redesign** (`OverviewTable`, new `OverviewRowList`, `OverviewFilterBar`). Grouped columns under a header band (Fit · Identity · Unit · Money · Timing · Place · Curation · People) with hairline group rules; selection/score/property pinned via `position: sticky` (module-owned stripe/hover, since Mantine paints those on `<tr>` with zero-specificity selectors a sticky `<td>` can't inherit) and a scroll shadow that only appears once a column is genuinely scrolled underneath (`data-scrolled`, toggled on `scrollLeft > 0`). **Pipeline hand-off**: a row still being fetched or whose last run failed shows a spinner/warning marker, states its stage or error inline, and links to `/tasks` or `/tasks?tab=history` (`rowState.ts`, `TasksPage` tab now URL-driven) instead of opening an empty drawer; a listing with no job at all is unaffected, and a scored group that's merely refreshing keeps its data and only swaps the marker. **Status**: the 140px `Select` + `Checkbox` pair becomes a `StatusChip` badge-menu + labelled `Visited` toggle (`interestStatus.ts` maps all ten statuses to a Mantine colour name — cyan/indigo/ochre/sage/brick/stone — and a Title Case label); the same tone drives a pinned dot in the identity cell (`RowMarker`, one slot, pipeline state outranks interest state) so status reads at every scroll position, not only when Curation is in view. **Ratings**: `RatingSummary` replaces five overlapping `Rating` widgets with a mono average + one member-coloured dot each + a comment count (hidden at zero); old `RatingDots` removed. **Filters**: `Filters` and the search box share one edge instead of a floating pill; 22 fields regroup into labelled sections in a `SimpleGrid`, paired bounds share a row with a dash, and small vocabularies (availability/status/visited/laundry/parking/pets/cooling/dishwasher) become `Chip.Group` toggles in Title Case (`titleCase` in `lib/text.ts`) — closed panel unmounts so its footer count can't linger in the accessibility tree. **Mobile**: below `48em` (`useMediaQuery`) the `<table>` — whose minimum width was the entire cause of a 701px-wide page at a 390px viewport — is replaced by `OverviewRowList`: collapsed rows show only score, property, unit, and all-in monthly; a borderless chevron expands to stat tiles (rent/sqft/available/deposit/city/added) then a full-width Status/People row then Listing/Compare/Archive actions; tapping the row still opens the drawer. Header renamed "All-In Monthly" (was "All-in / mo"). Presentation-only — `overviewRows.ts`'s pure row/sort/filter logic is unchanged. The stored column-picker key bumped to `-v2` since the redesign adds a `rent` column a v1 array wouldn't carry. Draft: `claude.ai/code/artifact/6f575fce`. | Measured before: `document.scrollWidth` 701px against a 390px viewport — the exact UI_DESIGN §5 violation. The table also spent its width on a flat one-fact-per-column spread with a dead gap at the right, hid curation behind permanent form chrome in every row, squeezed ratings into unreadable overlap at `maw={16}`, and gave no indication a row was still being fetched or had failed, silently opening an empty drawer for either. |
| 2026-07-25 | **Rubric categories re-grouped** (7 groups, none smaller than two criteria) and ordered by decision weight — The unit · Costs · Lease terms & rules · Location · Fittings & condition · Building & amenities · Management & service. Labels are the renter's words, so `catalogGroups.ts` no longer says "Floor plan and unit". The ruling and the full re-assignment live in **DESIGN §20 2026-07-25**: `category` is presentation vocabulary with no functional readers, so this is a label change made in `shared/catalog.py` + one sync migration rather than a frontend-only display map. Hue and icon-fallback maps follow the new vocabulary. | The redesign made the taxonomy's problem obvious once the groups were coloured: one 12-criterion drawer mixing a pool with an online rent portal, and two categories holding a single criterion while still costing a full heading and rule. Grouping by the question being asked survives catalog growth; an "other" bucket only grows. |
| 2026-07-25 | **Rubric cards redesign** (view + edit). (1) **Category hue**: `criterionCategory.ts` maps each catalog category to a Mantine palette name (slate blue/ochre/fog blue/sage/burnt clay/storm/dusty rose), rendered as a `ThemeIcon` identity tile on the card and a short rule under the group heading. Grape (human-entered) and dusty brick (danger/gates) are deliberately excluded so a tile can never read as a status. (2) **Points ledger**: signed mono tabular figures with a diverging magnitude bar scaled to the criterion's *own* largest delta (`deltaBar.ts`); dealbreaker rows show their set score and no bar. (3) **Markers**: `bonus` / `non-negotiable` word-badges → one tinted glyph each with the words on hover (§4). (4) **Unscored criteria** collapse from one empty card each into a single dashed add-pill strip per category (`CriterionPicker`). (5) Group headings moved from `Text fw={700}` to serif `Title order={4}`; grids no longer stretch cards to the tallest sibling; view mode goes to four columns at `xl`. (6) All 32 seeded catalog keys now have their own icon — twelve Property criteria had been falling through to the same house fallback — guarded by a test asserting no seeded key resolves to its category fallback. (7) JetBrains Mono actually installed (`@fontsource/jetbrains-mono`); `theme.ts` had named it since the identity pass while every figure silently fell back to system mono. Presentation-only: no contract, scoring, or API change. Editor page height 2205px → ~1840px *while showing every category instead of stopping at five*. Draft: `claude.ai/code/artifact/9b5aab9f`. | The rubric page spent its space on things that weren't being scored: 29 of 32 cards held nothing but a switch and a label, and the equal-height grid dragged a void beside every card that *was* scored. It also had no colour and no scanning aid — reading "which option actually moves the score" meant reading every digit. |
| 2026-07-25 | **Mantine-first authoring hierarchy and token discipline** (§§2–7). Mantine components and polymorphic primitives now precede raw structural HTML; styling escalates from theme/component props → one-off inline or style props → component `styles` → co-located CSS Module → shared theme/component. Colors, spacing, radii, shadows, and ordinary type use Mantine tokens; sub-`xs` type is limited to `0.125rem` increments. Added state, form, responsive, touch, accessibility, and review criteria; corrected test location to `frontend/tests/`. | The previous guide encouraged Mantine and tokens but left the everyday choice between inline styles and CSS Modules ambiguous, allowed off-scale type above `xl`, and treated accessibility/state coverage too narrowly. The explicit order keeps one-off styling lightweight without creating a second design system or class-per-declaration CSS. |
| 2026-07-24 | **Listing Detail Drawer shared CSS module** — exact cross-section primitives (header type, ledger state dots, band text colors, tabular nums, exceptional marker) live in `ListingDetailDrawer.module.css`; child sections import it for those tokens only and keep unique layout/tints locally. Mantine `Text`/`Box` pass on drawer children (no nested `<p>`). | Duplicated drawer tokens drifted across six modules; centralizing only byte-identical or intentionally shared rules cuts duplication without forcing unlike surfaces (fee vs all-in grids, plan chip colors) into one abstraction. |
| 2026-07-24 | **Drawer polish + Mantine-hardening pass** (`dev-phase3`). (1) Star ratings now take the member's color, yellow fallback (`starColorCss`). (2) `DrawerHero` recomposed from raw `<div>`s onto `Box`/`Text`/`Group`/`Title` primitives (typographic roles → props), output unchanged. (3) Token-anchoring tightened and swept across the drawer's module CSS — in-range spacing/font now use `var(--mantine-spacing-*)`/`var(--mantine-font-size-*)`; §3 rules updated. (4) The hand-rolled carousels (`DrawerImageGallery`, `PropertyImageCarousel`) rebuilt on **`@mantine/carousel`**; `ImageLightbox` kept custom (zoom viewer). (5) Tests relocated to the flat `frontend/tests/` dir. New §3 rules: *primitives over raw divs*, *anchor spacing/font to the scale*, *don't hand-roll what Mantine ships*. | Follow-up review of the shipped drawer: raw-div soup and off-scale pixel values were hard to maintain and couldn't be driven from `theme.ts`; a hand-rolled carousel duplicated a packaged component; star color carried no member identity. |
| 2026-07-24 | **Listing Detail Drawer redesign** (shipped; commits `300b48e..cc1d299` on `dev-phase3`, interleaved with an unrelated locality feature). Seven equal-weight `Section`s → a **summary hero** (name/address, large primary image + thumbnail filmstrip, score/all-in/beds tiles, score tile flat-tinted by band with a `✦` on ≥10) + **five topic cards** (Why this score · Cost & fees · Floor plans · Notes & ratings · Sources) built on the new `SectionCard`. Additive score tally (baseline 10 → signed deltas → `X / 15`); shared `scoreBand`/`scoreColor`/`scoreLabel` so color+label never disagree; badge declutter (state dots + one `ⓘ`/row + plum override dot); all-in result box; promoted sage utilities block; per-plan score chips; 5-star half-step ratings showing the whole team + average; compact multi-source rows. Presentation-only — no contract/scoring/data changes. Built via subagent-driven TDD (11 tasks, each spec+quality reviewed); 226 frontend tests + build + lint green. Spec: `docs/superpowers/specs/2026-07-23-listing-detail-drawer-redesign-design.md`; plan: `docs/superpowers/plans/2026-07-23-listing-detail-drawer-redesign.md`. | The drawer holds the most information and read as clutter (equal weight, stacked tables, badge pile-ups). It deserved a clear hierarchy: scan the headline, drill into calm grouped detail. |
| 2026-07-23 | **CSS Modules formally permitted** (Mantine-first, `*.module.css` where warranted; §3). Updates the older `frontend/AGENTS.md` "no bespoke CSS files" absolute, which the job-card work had already outgrown. The no-gradients rule remains in force. | Some layout/state visuals (pipeline track, meters, overflow control) can't be expressed cleanly through Mantine props; a scoped, token-driven module is clearer than prop gymnastics, without giving up theme consistency. |
| 2026-07-22 | **Job cards redesign** (Tasks page). Unified active/history cards on a shared five-phase `PipelineTrack`; status → colored dot + legend (fewer badges); history retry; expandable run-detail timeline; compact stop control on active cards. First substantial use of co-located CSS Modules. | The old cards showed raw stage text and lacked a retry path; the pipeline needed a legible, alive visual and a consistent language across active/history. |
| 2026-07-09 | **Visual identity: "Dusk & clay"** (DESIGN §20). Muted dusk-indigo primary, warm neutrals (stone light / charcoal dark), clay accent for waiting, earthy status hues, Literata + Source Sans 3 self-hosted, tabular numerals, sentence-case badges. All through `theme.ts`. | The UI read as generic SaaS defaults; *manzil* deserves warmth and character. Token-level identity is what the single theme seam exists for. |
