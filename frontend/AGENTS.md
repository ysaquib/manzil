# Frontend — Agent Instructions

Scope: everything under `frontend/`. These rules extend the repo-root `AGENTS.md` (which still
applies — glossary terms, phase discipline, pinned contracts). DESIGN.md §13 owns frontend design
intent.

## Design & UX rules

> Craft-level guidance (visual language, component approach, consistency patterns) and the UI
> decision log live in **`frontend/UI_DESIGN.md`**. Read it before building or reshaping a surface.
> Where a bullet here and that doc drift, the doc is the current word.

- **No gradients.** Flat colors only, everywhere — backgrounds, buttons, badges, charts, score tiles.
- **Refactoring UI principles govern visual design:**
  - Constrained palette with semantic roles; pick colors from the Mantine theme, never ad hoc.
  - Hierarchy via font weight, size, and gray shades (`dimmed`, `gray.6`) — not via decoration,
    borders, or shouting colors.
  - Whitespace is the primary grouping tool; prefer spacing over divider lines.
  - De-emphasize secondary content instead of emphasizing everything; labels are lighter than data.
- **Mantine-first theming.** All colors, spacing, radii, and shadows flow through `src/theme.ts`
  (semantic palette, component default props). No inline hex values in components — use Mantine color
  tokens (`green`, `gray.5`, `var(--mantine-color-*)`). `scoreColor` returning Mantine color names is
  the pattern for dynamic color. Co-located `*.module.css` files are allowed **where warranted** (see
  `UI_DESIGN.md §3`): still token-driven (no raw hex), theme-aware, scoped to their component — never a
  global stylesheet.
- **Intelligent affordance hierarchy.** Frequent/important actions are immediately visible
  (primary `Button`, always-visible controls: submit-URL, score filter, save). Seldom-used or
  destructive actions are tucked away but deliberately reachable: row-level rarities in a kebab
  `Menu`, provenance/attribution/detail-on-demand behind `Tooltip`/`HoverCard`, destructive
  actions behind a confirmation `Modal`. Nothing important lives only behind a hover; nothing rare
  occupies prime real estate.
- **Mobile-friendly and responsive, always.** Every surface must work at phone width (~375px):
  the detail panel is a right `Drawer` on mobile and desktop (DESIGN §13.2); tables hide secondary
  columns at narrow breakpoints or degrade to stacked cards; forms and steppers stack vertically.
  Use Mantine breakpoints + `useMediaQuery` — no bespoke media queries. No horizontal page scroll,
  ever.
- **Dark mode via Mantine only.** `defaultColorScheme="auto"` (system preference); header
  `ColorSchemeToggle` persists explicit `light`/`dark` in localStorage (`manzil-color-scheme`).
  Pre-mount inline script in `index.html` prevents flash. Audit semantic colors in both schemes;
  contrast fixes go through `theme.ts` (`autoContrast`, `primaryShade`) — not per-component hex.

## Data-layer rules (from the Phase 1 plan)

- Two clients: `supabase-js` for continuously-rendered table reads; `apiClient` for every mutation
  plus the one polled read (`GET /v1/hunts/{id}/jobs`).
- Server state exclusively via TanStack Query, keyed `[table/resource, huntId, ...]`; no
  `useEffect` fetching. Mutations invalidate the affected keys.
- Scores never recompute client-side: render persisted `scores.breakdown` directly (§9.3), and
  score changes arrive by re-fetch after the async rescore job — never synchronously.

## Living endpoint-assumptions document

`frontend/API_ASSUMPTIONS.md` lists every endpoint and direct-Supabase read the frontend assumes
exists, with its shape source and backend status. **Any change that adds, removes, or reshapes a
data hook must update that file in the same commit.** It is the reconciliation point when backend
tasks land.

## Testing

Vitest + Testing Library for anything with logic; no snapshot tests. Component tests live next to
the component (`Foo.test.tsx`).
