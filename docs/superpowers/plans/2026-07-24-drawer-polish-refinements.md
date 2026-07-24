# Drawer Polish & Mantine-Hardening — Spec + Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]` tracking.

**Date:** 2026-07-24 · **Branch:** `dev-phase3` · **Status:** approved (design + decisions signed off 2026-07-24)

**Goal:** Six pieces of polish feedback on the just-shipped Listing Detail Drawer — star colors, Mantine-primitive hygiene, token anchoring, test-file organization, docs, and swapping the hand-rolled carousel for `@mantine/carousel`.

**Architecture:** Presentation/hygiene only. No domain-contract, scoring, data-fetch, endpoint, or RLS changes. Same information, same behavior. This is refinement of the already-approved drawer redesign (commits `300b48e..d300a9e`), so it carries a single combined spec+plan gate rather than separate spec-then-plan gates.

**Tech Stack:** React 19 + Vite + Mantine v9 (`@mantine/core`, `+ @mantine/carousel`), TypeScript, CSS Modules, Vitest + RTL, `@tabler/icons-react`.

## Context (established facts)

- `@mantine/notifications` and `@mantine/dates` are **already installed and in active use** — nothing to do there. `@mantine/modals` is **dropped** (raw `<Modal>` from `@mantine/core` is already Mantine, not reinvented).
- `@mantine/carousel` is **not** installed. The hand-rolled carousels are `DrawerImageGallery` (drawer: primary + thumbnail filmstrip) and `PropertyImageCarousel` (ComparePage: scroll-snap strip). `ImageLightbox` is a full-screen **zoom viewer** (not a carousel) and **stays custom** — Carousel can't express its fit↔full zoom.
- Vitest picks up `**/*.test.tsx` anywhere, so `__tests__/` subfolders need **no config change** (`vite.config.ts` `setupFiles: ["./tests/setup.ts"]` is unaffected).
- Member colors: `memberColors.ts` maps 6 tokens (`moss/ochre/brick/olive/stone/plum`) → `var(--mantine-color-*-6)`; `member.color` is one of these tokens or `null`.
- Score-tile band tints in `DrawerHero.module.css` are bespoke `color-mix` rules — they **stay** (colors are already tokenized).

## Global Constraints

- **Flat colors only** — no gradients anywhere. Colors are **always** Mantine tokens (`var(--mantine-color-*)`, color names, `color-mix` of them); never raw hex.
- **Mantine-first.** Prefer `@mantine/core` primitives (`Box`, `Stack`, `Group`, `Paper`, `Text`, `Title`, `SimpleGrid`, `AspectRatio`, …) and props over raw `<div>` + module CSS. Reach for a `*.module.css` only for what props can't express cleanly (bespoke grid/overflow, `data-*`-keyed state visuals, fine optical geometry). (`UI_DESIGN.md §3`.)
- **Token anchoring.** Spacing and font-size use the Mantine scale (`xs`–`xl`) whenever the value is within that range; snap to the nearest step. Raw values (rem-preferred over px) **only** when the value is *intentionally* below `xs` or above `xl`, or is a true optical one-off no token fits.
  - Spacing scale: `xs`=10px · `sm`=12px · `md`=16px · `lg`=20px · `xl`=32px.
  - Font scale: `xs`=12px · `sm`=14px · `md`=16px · `lg`=18px · `xl`=20px.
- **Theme-aware** via `:global([data-mantine-color-scheme="dark"])`; audit both schemes. Respect reduced motion; visible focus on interactive chrome.
- **Presentation-only.** No scoring/contract/data/endpoint/RLS changes. Preserve every existing behavior (ratings mutation, pins, overrides, fees, save-on-close, lightbox zoom).
- **Never stage `frontend/src/colors.ts`** — it is the user's uncommitted WIP. Exclude it from every commit.
- **Commit per task** on `dev-phase3`.

---

### Task 1: Star colors follow the member's color (fallback yellow)

**Files:**
- Modify: `frontend/src/features/collaboration/memberColors.ts` (add `starColorCss`)
- Modify: `frontend/src/features/collaboration/StarRating.tsx` (accept `color`)
- Modify: `frontend/src/features/collaboration/StarRating.module.css` (fill color = var, prop-overridable)
- Modify: `frontend/src/features/collaboration/TeamRatings.tsx` (pass per-member color)
- Modify: `frontend/src/features/collaboration/RatingControl.tsx` (compute current member's color internally)
- Test: `frontend/src/features/collaboration/__tests__/memberColors.test.ts` (new — or `memberColors.test.ts` co-located until Task 6 moves it), `.../StarRating.test.tsx`

**Interfaces:**
- Produces: `starColorCss(token: string | null): string` — returns a CSS color string. Known token → `var(--mantine-color-<mantine>-6)` (via existing `memberColor`); `null` → `var(--mantine-color-yellow-6)` (the yellow fallback the user asked for); unknown non-null → passes through (`memberColor` returns the raw value).
- Produces: `StarRating({ value, size?, color? })` — `color` is a CSS color string applied to the fill; omitted → CSS default `var(--mantine-color-yellow-6)`.

- [ ] **Step 1: Write failing test for `starColorCss`**

```ts
// memberColors.test.ts
import { starColorCss } from "./memberColors";
test("known token maps to its mantine color var", () => {
  expect(starColorCss("moss")).toBe("var(--mantine-color-green-6)");
  expect(starColorCss("plum")).toBe("var(--mantine-color-grape-6)");
});
test("null falls back to yellow", () => {
  expect(starColorCss(null)).toBe("var(--mantine-color-yellow-6)");
});
```

- [ ] **Step 2: Run — expect FAIL** (`starColorCss` not exported)

- [ ] **Step 3: Implement `starColorCss`**

```ts
// append to memberColors.ts
export function starColorCss(token: string | null): string {
  return token ? memberColor(token) : "var(--mantine-color-yellow-6)";
}
```

- [ ] **Step 4: `StarRating` accepts `color`**

```tsx
export function StarRating({ value, size = "sm", color }: { value: number; size?: "sm" | "lg"; color?: string }) {
  const pct = Math.max(0, Math.min(100, (value / 5) * 100));
  return (
    <span className={`${classes.stars} ${classes[size]}`} aria-label={`${value} of 5`}>
      <span className={classes.base}>★★★★★</span>
      <span className={classes.fill} data-fill style={{ width: `${pct}%`, color }}>★★★★★</span>
    </span>
  );
}
```
`StarRating.module.css` `.fill` keeps `color: var(--mantine-color-yellow-6);` as the fallback when the inline `color` is `undefined`.

- [ ] **Step 5: `TeamRatings` passes each member's color**

`<StarRating value={r} color={starColorCss(m.color)} />` (import `starColorCss`).

- [ ] **Step 6: `RatingControl` computes the current member's color; drop the `color` prop**

```tsx
// inside RatingControl, after members/session are available:
const currentMember = members.find((m) => m.user_id === session?.user.id);
const yourStarColor = starColorCss(currentMember?.color ?? null);
// <Rating ... color={yourStarColor} />
```
Remove the `color?` prop from the signature (no caller passes it — the drawer stopped passing color/memberColor). Mantine `<Rating color>` accepts the CSS-var string.

- [ ] **Step 7: StarRating test — custom color applied to fill**

```tsx
const { container } = render(<StarRating value={3} color="var(--mantine-color-grape-6)" />);
const fill = container.querySelector("[data-fill]") as HTMLElement;
expect(fill.style.color).toBe("var(--mantine-color-grape-6)");
```

- [ ] **Step 8: Run all collaboration tests — expect PASS**. Run: `pnpm -C frontend test --run src/features/collaboration`

- [ ] **Step 9: Commit** (exclude `colors.ts`): `feat(frontend): star ratings use member color with yellow fallback`

---

### Task 2: Replace `DrawerImageGallery` with `@mantine/carousel`

**Judgment task** (integration + responsive layout). Install deps, rebuild the drawer gallery on `@mantine/carousel` while preserving the approved look: one large **16:10 primary** (cover-crop, never stretch) that swipes, a **fixed-aspect thumbnail filmstrip** below that scrolls the primary, an `n / N` counter, and click-to-open the existing `ImageLightbox`. Keep the empty/loading states and `images`/`loading` props.

**Files:**
- Install: `@mantine/carousel`, `embla-carousel`, `embla-carousel-react`
- Modify: `frontend/src/main.tsx` (import `@mantine/carousel/styles.css` **after** `@mantine/core/styles.css`)
- Rewrite: `frontend/src/features/listings/DrawerImageGallery.tsx`
- Modify: `frontend/src/features/listings/DrawerImageGallery.module.css` (thumbnail strip + aspect geometry; drop primary-nav rules Carousel now owns)
- Keep: `frontend/src/features/listings/ImageLightbox.tsx` (unchanged)
- Test: `frontend/src/features/listings/DrawerImageGallery.test.tsx` (update assertions)

**Interfaces:** unchanged — `DrawerImageGallery({ images: PropertyImage[]; loading: boolean })`.

**Key API facts (Mantine v9 / embla 8):** install `embla-carousel` + `embla-carousel-react` explicitly; `import '@mantine/carousel/styles.css'` at root after core; `getEmblaApi={setEmbla}` yields `EmblaCarouselType` from `embla-carousel`; control via `emblaApi.scrollTo(i)`, subscribe with `emblaApi.on('select', ...)` and read `emblaApi.selectedScrollSnap()`; slide sizing/gap via `slideSize`/`slideGap`; embla options (`loop`, `align`) go under `emblaOptions`. The implementer should verify the responsive 16:10 approach in the browser (Carousel takes a `height`; wrap in `AspectRatio ratio={16/10}` or a CSS `aspect-ratio` viewport so the primary stays responsive and cover-cropped).

- [ ] **Step 1: Update the failing test first** — assert: renders `images.length` slides (or a primary image with correct `alt`), shows the `n / N` counter for >1 image, and shows the "No photos collected yet" empty state for `[]`. Keep it resilient to embla internals (query by `alt`/role/text, not embla classes).
- [ ] **Step 2: Install deps.** Run: `pnpm -C frontend add @mantine/carousel embla-carousel embla-carousel-react`. Verify `@mantine/carousel` version matches the pinned `@mantine/core` (`^9.4.1`).
- [ ] **Step 3: Add the styles import** to `main.tsx` after the core styles line.
- [ ] **Step 4: Rewrite `DrawerImageGallery`** — a `Carousel` for the primary (16:10, cover), `getEmblaApi` state, `onSlideChange`/`on('select')` to track index, an `n / N` counter overlay, and a thumbnail strip (buttons) calling `embla.scrollTo(i)`; active thumb reflects the selected snap; clicking the primary opens `ImageLightbox` at the current index. Preserve `loading` (Skeleton at 16:10) and empty states. Overlays use `var(--mantine-color-white)`; images `loading="lazy"`; nav controls get `aria-label`s; honor reduced motion.
- [ ] **Step 5: Trim `DrawerImageGallery.module.css`** — remove rules Carousel now owns (primary nav buttons/counter positioning if replaced by Carousel controls); keep/adjust the thumbnail-strip geometry (fixed 16:10, cover, horizontal scroll in its own container — no page h-scroll). Colors stay tokenized; apply Task-3 token anchoring here since this file is being rewritten.
- [ ] **Step 6: Run the gallery test — expect PASS.** Run: `pnpm -C frontend test --run src/features/listings/DrawerImageGallery`
- [ ] **Step 7: Typecheck/build sanity.** Run: `pnpm -C frontend build`
- [ ] **Step 8: Commit** (exclude `colors.ts`): `feat(frontend): rebuild drawer image gallery on @mantine/carousel`

---

### Task 3: Replace `PropertyImageCarousel` (ComparePage) with `@mantine/carousel`

**Judgment task.** The compare view's hand-rolled scroll-snap strip → a `@mantine/carousel` multi-slide strip, preserving its look (image strip, chevron paging, `n / N`, click-to-lightbox). Depends on Task 2 (deps + styles already installed).

**Files:**
- Rewrite: `frontend/src/features/listings/PropertyImageCarousel.tsx`
- Keep: `ImageLightbox` (unchanged)
- Test: none exists today; add a light `PropertyImageCarousel.test.tsx` (renders slides + empty state) if practical, else rely on `ComparePage.test.tsx`.

**Interfaces:** unchanged — `PropertyImageCarousel({ images, loading })`, still consumed by `ComparePage.tsx:70`.

- [ ] **Step 1:** Rewrite using `Carousel` with `slideSize` (~85%) + `slideGap`, `emblaOptions={{ align: 'start' }}`, chevron controls, `n / N` counter, click-to-lightbox. Preserve loading Skeletons and the empty state. Strip scrolls in its own container.
- [ ] **Step 2: Run** `pnpm -C frontend test --run src/features/listings/ComparePage` **and** any new test — expect PASS.
- [ ] **Step 3: Commit** (exclude `colors.ts`): `feat(frontend): rebuild compare-view carousel on @mantine/carousel`

---

### Task 4: `DrawerHero` — raw divs → Mantine primitives

**Judgment/visual task.** Recompose `DrawerHero.tsx`'s `<div>` soup into Mantine primitives (`Box`, `Stack`, `Group`, `Paper`, `Text`, `Title`, `SimpleGrid`) with **no visual change**. The score tile keeps its `data-band` element + `DrawerHero.module.css` band-tint rules (bespoke `color-mix` — can't be a prop). This task **owns `DrawerHero.module.css` entirely**, including its Task-3 token anchoring (so Task 5 doesn't touch it).

**Files:**
- Rewrite: `frontend/src/features/listings/DrawerHero.tsx`
- Modify: `frontend/src/features/listings/DrawerHero.module.css` (shrink to band-tint + true optical one-offs; token-anchor the rest)
- Test: `frontend/src/features/listings/DrawerHero.test.tsx` (keep passing; assertions target text/score/label/beds, not div structure)

**Interfaces:** unchanged props.

- [ ] **Step 1:** Map each `<div>` to a primitive — eyebrow → `Text tt="uppercase" fz` (below-xs size stays explicit rem); name → `Title order={3}`; address → `Group gap="xs"` + `Text` + `IconMapPin`; stat tiles → `Paper withBorder`; stats row → `SimpleGrid` or `Group`/grid (keep the `auto 1fr 1fr` intent). The score tile stays an element with `data-band` + module class. Preserve `✦`, `scoreLabel`, `formatScore`, "Not scored yet", `~est`.
- [ ] **Step 2:** Reduce `DrawerHero.module.css` to what props can't express (band tints, `.scoreNum`/`.title` >xl font sizes as explicit rem, sub-xs sizes as explicit rem); anything in `[xs,xl]` moves to props or tokens.
- [ ] **Step 3: Run** `pnpm -C frontend test --run src/features/listings/DrawerHero` — expect PASS.
- [ ] **Step 4: Commit** (exclude `colors.ts`): `refactor(frontend): compose DrawerHero from Mantine primitives`

*(Visual before/after screenshots are a main-session verification step around Tasks 2 & 4 — not a plan task.)*

---

### Task 5: Token-anchoring sweep across the remaining drawer module CSS

**Mechanical-with-judgment task.** Apply the Global-Constraints token rule to the drawer's module CSS files **except** `DrawerHero.module.css` (Task 4) and `DrawerImageGallery.module.css` (Task 2). Snap in-range spacing/font values to the nearest Mantine token; leave out-of-range (`<xs`/`>xl`) and true optical one-offs as explicit rem (convert px→rem where a raw value remains). Do **not** change layout intent or colors; visuals should be within a hair.

**Files (modify):** `AllInCost.module.css`, `CriterionBreakdown.module.css`, `FeeChecklist.module.css`, `FloorPlanPins.module.css`, `SourcesList.module.css`, `SectionCard.module.css`, `ListingDetailDrawer.module.css`, `TeamRatings.module.css`, `StarRating.module.css` (all under `src/features/listings/` and `src/features/collaboration/`).

- [ ] **Step 1:** For each file, replace in-range values: `gap/padding/margin` → `var(--mantine-spacing-*)`; `font-size` in `[12,20]px` → `var(--mantine-font-size-*)`. Values `<xs` or `>xl` → explicit `rem()` (px→rem). Keep `color-mix`/token colors as-is.
- [ ] **Step 2: Run the full drawer test slice** — `pnpm -C frontend test --run src/features/listings src/features/collaboration src/components` — expect PASS (no test asserts pixel values; failures indicate a structural slip).
- [ ] **Step 3: Commit** (exclude `colors.ts`): `refactor(frontend): anchor drawer CSS spacing/font to Mantine tokens`

---

### Task 6: Move tests into `__tests__/` subfolders

**Mechanical task.** Relocate every co-located `*.test.ts(x)` into a `__tests__/` subfolder within its current directory, fixing the relative imports (one level deeper: `./X` → `../X`). The shared setup at `frontend/tests/setup.ts` is unaffected (it's referenced absolutely from `vite.config.ts`). No Vitest config change needed (default glob finds `__tests__/`).

**Files:** all 46 files from `find frontend/src -name '*.test.ts' -o -name '*.test.tsx'`, each moved to `<dir>/__tests__/<name>` with imports repointed.

- [ ] **Step 1:** For each test file: `git mv <dir>/<name>.test.tsx <dir>/__tests__/<name>.test.tsx`; then bump every relative import that referenced a sibling (`from "./Foo"` → `from "../Foo"`, `from "./sub/x"` → `from "../sub/x"`). Do **not** rewrite imports that already reach up (`../../`) — add one `../` level to each.
- [ ] **Step 2: Run the entire suite** — `pnpm -C frontend test --run` — expect the same pass count as before the move (46 files).
- [ ] **Step 3: Lint** — `pnpm -C frontend lint` — expect clean.
- [ ] **Step 4:** Update `frontend/AGENTS.md` Testing bullet: "Component tests live in a `__tests__/` subfolder beside the component (`__tests__/Foo.test.tsx`)."
- [ ] **Step 5: Commit** (exclude `colors.ts`): `chore(frontend): move tests into __tests__ subfolders`

---

### Task 7: Documentation — UI_DESIGN rules + decision log

**Docs task** (done in main session). Add the new craft rules and log the change.

**Files:** `frontend/UI_DESIGN.md`, `frontend/AGENTS.md`.

- [ ] **Step 1: `UI_DESIGN.md §3`** — add a "Mantine primitives over raw divs" rule (default to `Box/Stack/Group/Paper/SimpleGrid/AspectRatio/Text/Title` and props; a bare `<div>` in a `.tsx` is a smell — reach for module CSS only for what props can't express), framed in RefactoringUI/maintainability terms (fewer nodes, semantic intent, theme reaches everything).
- [ ] **Step 2: `UI_DESIGN.md §3`** — tighten the token rule: spacing/font anchor to the Mantine scale (`xs`–`xl`) whenever in range; explicit **rem-preferred** values only when intentionally `<xs`/`>xl` or a true optical one-off. Note the scale values. This supersedes the looser "fine geometry is a judgment call" wording for spacing/font (bespoke dot/track pixel geometry remains a judgment call).
- [ ] **Step 3: `UI_DESIGN.md §3`** — note `@mantine/carousel` is the carousel primitive (don't hand-roll); `ImageLightbox` stays custom because it's a zoom viewer, not a carousel.
- [ ] **Step 4: `UI_DESIGN.md` decision log** — new dated row summarizing this pass (star colors; Mantine-primitive hygiene; token anchoring; `__tests__/` layout; `@mantine/carousel`).
- [ ] **Step 5: `frontend/AGENTS.md`** — align the "Mantine-first theming" bullet with the primitives-over-divs + token rules (point to `UI_DESIGN.md §3`).
- [ ] **Step 6: Commit** (exclude `colors.ts`): `docs(frontend): record drawer polish rules and decision-log entry`

---

## Execution notes

- Order: 1 → 2 → 3 → 4 → 5 → 6 → 7. Take a **baseline drawer screenshot** (desktop + mobile ~375px, light + dark) before Task 2; take an **after** set after Task 4; compare for parity (the user's explicit ask on #2). Screenshots run in the main session (Playwright) — no subagent spend.
- Routing: Tasks 2/3/4 are judgment/integration (`executor`); Tasks 5/6 are mechanical (`mech-executor`); Tasks 1/7 are small/local. Right-size reviews to risk.
- Every commit excludes `frontend/src/colors.ts`.
```
