# Listing Detail Drawer Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the `ListingDetailDrawer` as an at-a-glance **summary hero + five topic cards**, replacing the seven equal-weight `Section`s, with reduced badge clutter — presentation only, no data/scoring/contract changes.

**Architecture:** New small presentational units (`SectionCard`, `DrawerHero`, `DrawerImageGallery`, `StarRating`, `TeamRatings`) plus a pure `scoreBand`/`scoreLabel` helper. Existing section components (`CriterionBreakdown`, `AllInBreakdown`, `FeeChecklist`, `FloorPlanPins`, `RatingControl`, `SourcesList`, `CommentsSection`) are **restyled in place** — their data hooks, draft/override/pin/save behavior, and existing tests stay green. `DrawerShell` recomposes them into the hero + cards. Styling follows the job-card precedent: Mantine composition + co-located token-driven `*.module.css`, theme-aware, flat colors only.

**Tech Stack:** React 18, Vite, Mantine v9 (`@mantine/core`), TypeScript, CSS Modules, Vitest + React Testing Library, `@tabler/icons-react`, TanStack Query (existing hooks only).

## Global Constraints

- **Flat colors only** — no gradients anywhere (score tile uses a flat band-color tint). (`frontend/AGENTS.md`, `UI_DESIGN.md §1`.)
- **Colors are always tokens** — no inline hex in `.tsx`, no raw hex in `.module.css`; use `var(--mantine-color-*)` (+ `color-mix(...)` of them). For **spacing and radius, use `--mantine-spacing-*` / `--mantine-radius-*` where a standard value maps cleanly** (e.g. `16px → var(--mantine-spacing-md)`), and **never override a themed `Card`'s radius with a bespoke value**. **Fine optical geometry** — bespoke asymmetric paddings, dot/track/pip pixel sizes, sub-token font-sizes and letter-spacing — **may be raw px/rem**, matching the already-shipped job-card module CSS (`PipelineTrack.module.css`, `HistoryCard.module.css`). (`UI_DESIGN.md §3`.)
- **Theme-aware**: every module audited in light + dark; dark overrides via `:global([data-mantine-color-scheme="dark"]) .x { … }`. (`UI_DESIGN.md §3`.)
- **Dynamic color returns Mantine color names**, never hex (`scoreColor` pattern). Score reads **`X / 15`**, base 10, clamp [0,15].
- **Presentation-only**: no changes to endpoints, `scores.breakdown`, RLS, persistence, or the draft-save/override/pin contracts. Scores never recomputed client-side.
- **Mobile-first (~375px)**; no horizontal page scroll; wide content scrolls in its own container.
- **TDD**: co-located `*.test.tsx`, watch each test fail first. No snapshot tests. `pnpm -C frontend test | build | lint` all green before "done".
- **Pixel reference:** `docs/superpowers/specs/2026-07-23-listing-detail-drawer-preview.html` (approved mock) is the authority for exact spacing/geometry/CSS values. Translate its CSS to module CSS with Mantine tokens (the mock's `--paper/--card/--ink/...` map to Mantine `--mantine-color-body` / `-default` / `-text` / etc.).
- **Score band table** (label + color share thresholds; inclusive-lower):

  | Total | color name | label |
  |---|---|---|
  | ≥ 10 | `scoreHighest` | Exceptional Match |
  | 8–10 | `scoreHigh` | Strong Match |
  | 6–8 | `scoreGood` | Acceptable Match |
  | 4–6 | `scoreMid` | Weak Match |
  | 2–4 | `scoreLow` | Poor Match |
  | < 2 | `scorePoor` | Unacceptable |

---

## File Structure

**New:**
- `frontend/src/features/listings/scoreBands.ts` — pure `scoreBand`, `scoreColor`, `scoreLabel`, `formatScore` (moved from `ScoreCell.tsx`; re-exported there for existing importers).
- `frontend/src/features/listings/scoreBands.test.ts` — band/label boundary tests.
- `frontend/src/components/SectionCard.tsx` + `.module.css` — the card shell (serif title + hint + body).
- `frontend/src/components/SectionCard.test.tsx`.
- `frontend/src/features/listings/DrawerImageGallery.tsx` + `.module.css` — large primary + thumbnail filmstrip (replaces `PropertyImageCarousel` in the drawer; reuses `ImageLightbox`).
- `frontend/src/features/listings/DrawerImageGallery.test.tsx`.
- `frontend/src/features/listings/DrawerHero.tsx` + `.module.css` — hero: name/address/gallery/stat strip.
- `frontend/src/features/listings/DrawerHero.test.tsx`.
- `frontend/src/features/collaboration/StarRating.tsx` — pure 5-star, half-step display (fill math).
- `frontend/src/features/collaboration/StarRating.test.tsx`.
- `frontend/src/features/collaboration/TeamRatings.tsx` — team ratings list + average (uses `useRatings`, `useMembers`).
- `frontend/src/features/collaboration/TeamRatings.test.tsx`.

**Modify (restyle, behavior preserved):**
- `frontend/src/features/listings/ScoreCell.tsx` — re-export from `scoreBands.ts`; add `✦` on `scoreHighest`.
- `frontend/src/features/listings/CriterionBreakdown.tsx` (+ new `.module.css`) — baseline row + signed-delta rows + total; badge declutter.
- `frontend/src/features/listings/AllInCost.tsx` (+ `.module.css`) — state dots at row front, flush amounts, all-in result box, utilities block.
- `frontend/src/features/listings/FeeChecklist.tsx` (+ `.module.css`) — restyle rows to state-dot + flush amount; keep slots/manual/estimate/move-in logic.
- `frontend/src/features/listings/FloorPlanPins.tsx` (+ `.module.css`) — pin rows; per-plan score chip on name line; rent/avail right.
- `frontend/src/features/collaboration/RatingControl.tsx` — your rating = half-step stars; render `TeamRatings` below.
- `frontend/src/features/listings/SourcesList.tsx` (+ `.module.css`) — compact rows; single-source reason only when one source.
- `frontend/src/features/listings/ListingDetailDrawer.tsx` — recompose `DrawerShell` into hero + five `SectionCard`s.

**Untouched behavior:** `ListingDetailDraft`, `OverrideControl`, `AllInOverrideControl`, `useExtractions/useOverrides/useFees/usePropertyImages`, `CommentsSection`, `ImageLightbox`, `unitGroups` resolvers.

---

### Task 1: Pure score band + label helper

**Files:**
- Create: `frontend/src/features/listings/scoreBands.ts`
- Create: `frontend/src/features/listings/scoreBands.test.ts`
- Modify: `frontend/src/features/listings/ScoreCell.tsx` (re-export; `✦` marker)

**Interfaces:**
- Produces: `scoreBand(total: number, base?: number): number` (0=highest … 5=poor, 6=poorest), `scoreColor(total, base?, max?): string`, `scoreLabel(total: number): string`, `formatScore(total: number): string`.
- Consumes: `SCORE_BASE`, `SCORE_MAX` from `../../lib/contracts`.

- [ ] **Step 1: Write the failing test**

```ts
// scoreBands.test.ts
import { describe, expect, it } from "vitest";
import { scoreBand, scoreColor, scoreLabel, formatScore } from "./scoreBands";

describe("scoreBand / scoreColor / scoreLabel", () => {
  it("maps totals to bands on inclusive-lower thresholds (base 10)", () => {
    expect(scoreBand(12.5)).toBe(0);
    expect(scoreBand(10)).toBe(0);   // exactly base = highest
    expect(scoreBand(9.5)).toBe(1);
    expect(scoreBand(8)).toBe(1);
    expect(scoreBand(6)).toBe(2);
    expect(scoreBand(4)).toBe(3);
    expect(scoreBand(2)).toBe(4);
    expect(scoreBand(0)).toBe(5);
  });
  it("labels match the bands", () => {
    expect(scoreLabel(12.5)).toBe("Exceptional Match");
    expect(scoreLabel(10)).toBe("Exceptional Match");
    expect(scoreLabel(9)).toBe("Strong Match");
    expect(scoreLabel(7)).toBe("Acceptable Match");
    expect(scoreLabel(5)).toBe("Weak Match");
    expect(scoreLabel(3)).toBe("Poor Match");
    expect(scoreLabel(1)).toBe("Unacceptable");
  });
  it("colors stay consistent with the pre-existing scoreColor bands", () => {
    expect(scoreColor(10)).toBe("scoreHighest");
    expect(scoreColor(8)).toBe("scoreHigh");
    expect(scoreColor(6)).toBe("scoreGood");
    expect(scoreColor(4)).toBe("scoreMid");
    expect(scoreColor(2)).toBe("scoreLow");
    expect(scoreColor(0)).toBe("scorePoor");
  });
  it("preserves the original base=0 edge (0/0 = NaN falls through to poorest)", () => {
    expect(scoreBand(0, 0)).toBe(6);
    expect(scoreColor(0, 0)).toBe("scorePoorest");
  });
  it("formats half-points, keeps integers clean", () => {
    expect(formatScore(9.5)).toBe("9.5");
    expect(formatScore(10)).toBe("10");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm -C frontend test --run src/features/listings/scoreBands.test.ts`
Expected: FAIL — `scoreBands` module not found.

- [ ] **Step 3: Write minimal implementation**

```ts
// scoreBands.ts
import { SCORE_BASE, SCORE_MAX } from "../../lib/contracts";

const COLORS = [
  "scoreHighest", "scoreHigh", "scoreGood", "scoreMid", "scoreLow", "scorePoor", "scorePoorest",
] as const;
const LABELS = [
  "Exceptional Match", "Strong Match", "Acceptable Match", "Weak Match", "Poor Match", "Unacceptable", "Unacceptable",
] as const;

// Band index 0..6 from total/base, inclusive-lower thresholds (5/5,4/5,…).
// Anchored on the §9.3 engine domain (base 10) so color and label agree.
// IMPORTANT: the `max > 0 ? … : 0` guard is copied VERBATIM from the original
// scoreColor so behavior is byte-for-byte preserved — including the base=0
// edge, where total/0 = NaN falls through every check to band 6 (poorest).
// Do NOT "simplify" it to `base > 0`; that regresses ScoreCell's existing
// "does not divide by zero" test (NaN→poorest becomes 0→poor).
export function scoreBand(total: number, base = SCORE_BASE, max = SCORE_MAX): number {
  const pct = max > 0 ? total / base : 0;
  if (pct >= 5 / 5) return 0;
  if (pct >= 4 / 5) return 1;
  if (pct >= 3 / 5) return 2;
  if (pct >= 2 / 5) return 3;
  if (pct >= 1 / 5) return 4;
  if (pct >= 0 / 5) return 5;
  return 6;
}

export function scoreColor(total: number, base = SCORE_BASE, max = SCORE_MAX): string {
  return COLORS[scoreBand(total, base, max)];
}

export function scoreLabel(total: number): string {
  return LABELS[scoreBand(total)];
}

// Half-point deltas are common (§8.2); 9.5 must not read as 10.
export function formatScore(total: number): string {
  return Number.isInteger(total) ? String(total) : total.toFixed(1);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm -C frontend test --run src/features/listings/scoreBands.test.ts`
Expected: PASS (all 4).

- [ ] **Step 5: Point `ScoreCell.tsx` at the shared helper + add `✦`**

In `ScoreCell.tsx`: delete the local `scoreColor` and `formatScore` definitions, and replace the import line `import { SCORE_BASE, SCORE_MAX } from "../../lib/contracts";` region with:

```tsx
import { scoreColor, scoreBand, formatScore } from "./scoreBands";
export { scoreColor, formatScore } from "./scoreBands"; // keep existing import sites (FloorPlanPins) working
```

Then in the `ScoreCell` component, mark the exceptional band. Replace the score `<Text>` with:

```tsx
<Text ff={"monospace"} fz="xs" fw={600} c={scoreColor(total)}>
  {formatScore(total)}
  {scoreBand(total) === 0 && (
    <Text span aria-hidden ml={2}>✦</Text>
  )}
</Text>
```

- [ ] **Step 6: Verify existing ScoreCell tests still pass**

Run: `pnpm -C frontend test --run src/features/listings/ScoreCell.test.tsx`
Expected: PASS — **all** existing assertions, unmodified. In particular the "does not divide by zero" test must stay green (the verbatim `max > 0` guard preserves `scoreColor`'s output exactly). The ONLY reason to touch a ScoreCell test is if one asserted an exact full-text equality to the number and the trailing `✦` on a `scoreHighest` row breaks it; if so, relax just that assertion. Do not change behavior to make a test pass.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/listings/scoreBands.ts frontend/src/features/listings/scoreBands.test.ts frontend/src/features/listings/ScoreCell.tsx
git commit -m "feat(listings): extract shared scoreBand/scoreLabel helper with exceptional marker"
```

---

### Task 2: `SectionCard` shell

**Files:**
- Create: `frontend/src/components/SectionCard.tsx`, `frontend/src/components/SectionCard.module.css`
- Create: `frontend/src/components/SectionCard.test.tsx`

**Interfaces:**
- Produces: `SectionCard({ title, hint?, children }: { title: string; hint?: ReactNode; children: ReactNode })`.

- [ ] **Step 1: Write the failing test**

```tsx
// SectionCard.test.tsx
import { render, screen } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { SectionCard } from "./SectionCard";

const wrap = (ui: React.ReactNode) => render(<MantineProvider>{ui}</MantineProvider>);

it("renders a titled card with an optional hint and its children", () => {
  wrap(
    <SectionCard title="Why this score" hint="13 criteria">
      <p>body</p>
    </SectionCard>,
  );
  expect(screen.getByRole("heading", { name: "Why this score" })).toBeInTheDocument();
  expect(screen.getByText("13 criteria")).toBeInTheDocument();
  expect(screen.getByText("body")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm -C frontend test --run src/components/SectionCard.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```tsx
// SectionCard.tsx
import { Card, Group, Title } from "@mantine/core";
import type { ReactNode } from "react";
import classes from "./SectionCard.module.css";

export function SectionCard({ title, hint, children }: {
  title: string; hint?: ReactNode; children: ReactNode;
}) {
  return (
    <Card className={classes.card} padding={0}>
      <Group className={classes.head} justify="space-between" wrap="nowrap">
        <Title order={5} className={classes.title}>{title}</Title>
        {hint != null && <span className={classes.hint}>{hint}</span>}
      </Group>
      <div className={classes.body}>{children}</div>
    </Card>
  );
}
```

```css
/* SectionCard.module.css */
.card { border-radius: 14px; }
.head { padding: 13px 16px 11px; gap: 10px; }
.title { font-size: 15.5px; letter-spacing: -0.005em; }
.hint { font-size: 12px; color: var(--mantine-color-dimmed); white-space: nowrap; }
.body { padding: 2px 16px 15px; }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm -C frontend test --run src/components/SectionCard.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/SectionCard.tsx frontend/src/components/SectionCard.module.css frontend/src/components/SectionCard.test.tsx
git commit -m "feat(components): add SectionCard shell for the detail drawer"
```

---

### Task 3: `DrawerImageGallery` (large primary + thumbnail strip)

**Files:**
- Create: `frontend/src/features/listings/DrawerImageGallery.tsx`, `DrawerImageGallery.module.css`, `DrawerImageGallery.test.tsx`

**Interfaces:**
- Consumes: `PropertyImage[]` and `loading` from `./api`; `ImageLightbox` from `./ImageLightbox`.
- Produces: `DrawerImageGallery({ images, loading }: { images: PropertyImage[]; loading: boolean })`.

Behavior: shows the image at `index` large (aspect 16/10, `object-fit: cover`), prev/next buttons + `n / N` counter (when >1), a thumbnail strip (fixed 58px, 16/10, cover) that sets `index` on click and scrolls if overflowing; clicking the primary opens `ImageLightbox` at `index`. Loading → skeleton; empty → the existing "No photos collected yet" copy. CSS values per the preview's `.gallery/.heroImg/.counter/.navBtn/.film/.fthumb`.

- [ ] **Step 1: Write the failing test**

```tsx
// DrawerImageGallery.test.tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { DrawerImageGallery } from "./DrawerImageGallery";

const imgs = [
  { id: "a", url: "http://x/a.webp", property_id: "p", position: 0 },
  { id: "b", url: "http://x/b.webp", property_id: "p", position: 1 },
] as any;
const wrap = (ui: React.ReactNode) => render(<MantineProvider>{ui}</MantineProvider>);

it("shows a counter and advances the primary image via next", () => {
  wrap(<DrawerImageGallery images={imgs} loading={false} />);
  expect(screen.getByText("1 / 2")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /next photo/i }));
  expect(screen.getByText("2 / 2")).toBeInTheDocument();
});

it("renders the empty state when there are no photos", () => {
  wrap(<DrawerImageGallery images={[]} loading={false} />);
  expect(screen.getByText(/No photos collected yet/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm -C frontend test --run src/features/listings/DrawerImageGallery.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement** (translate the preview `.gallery` markup; Mantine `Skeleton` for loading)

```tsx
// DrawerImageGallery.tsx
import { ActionIcon, Skeleton, Text, UnstyledButton } from "@mantine/core";
import { IconChevronLeft, IconChevronRight } from "@tabler/icons-react";
import { useState } from "react";
import type { PropertyImage } from "./api";
import { ImageLightbox } from "./ImageLightbox";
import classes from "./DrawerImageGallery.module.css";

export function DrawerImageGallery({ images, loading }: { images: PropertyImage[]; loading: boolean }) {
  const [index, setIndex] = useState(0);
  const [lightbox, setLightbox] = useState<number | null>(null);
  if (loading) return <Skeleton className={classes.primary} />;
  if (images.length === 0) {
    return <Text size="sm" c="dimmed">No photos collected yet — the image pass runs during ingestion.</Text>;
  }
  const clamp = (i: number) => (i + images.length) % images.length;
  const current = images[Math.min(index, images.length - 1)];
  return (
    <div className={classes.gallery}>
      <div className={classes.primaryWrap}>
        <UnstyledButton
          className={classes.primaryBtn}
          onClick={() => setLightbox(index)}
          aria-label={`open photo ${index + 1} of ${images.length}`}
        >
          <img className={classes.primary} src={current.url} alt={`listing photo ${index + 1} of ${images.length}`} />
        </UnstyledButton>
        {images.length > 1 && (
          <>
            <ActionIcon className={`${classes.nav} ${classes.prev}`} radius="xl"
              aria-label="previous photo" onClick={() => setIndex(clamp(index - 1))}>
              <IconChevronLeft size={16} stroke={2} />
            </ActionIcon>
            <ActionIcon className={`${classes.nav} ${classes.next}`} radius="xl"
              aria-label="next photo" onClick={() => setIndex(clamp(index + 1))}>
              <IconChevronRight size={16} stroke={2} />
            </ActionIcon>
            <span className={classes.counter}>{index + 1} / {images.length}</span>
          </>
        )}
      </div>
      {images.length > 1 && (
        <div className={classes.film}>
          {images.map((img, i) => (
            <button key={img.id} type="button"
              className={`${classes.thumb} ${i === index ? classes.active : ""}`}
              aria-label={`show photo ${i + 1}`} aria-pressed={i === index}
              onClick={() => setIndex(i)}>
              <img src={img.url} alt="" />
            </button>
          ))}
        </div>
      )}
      <ImageLightbox images={images} index={lightbox} onNavigate={setLightbox} onClose={() => setLightbox(null)} />
    </div>
  );
}
```

```css
/* DrawerImageGallery.module.css — see preview .heroImg/.film/.fthumb for exact values */
.gallery { display: flex; flex-direction: column; }
.primaryWrap { position: relative; }
.primaryBtn { display: block; width: 100%; cursor: zoom-in; }
.primary { width: 100%; aspect-ratio: 16 / 10; object-fit: cover; border-radius: var(--mantine-radius-md); display: block; }
.nav { position: absolute; top: 50%; transform: translateY(-50%); background: rgba(0,0,0,.38); color: #fff; border: 0; }
.prev { left: 10px; } .next { right: 10px; }
.counter { position: absolute; right: 10px; bottom: 10px; font-size: 11.5px; font-weight: 600; color: #fff; background: rgba(0,0,0,.42); padding: 3px 9px; border-radius: 999px; }
.film { display: flex; gap: 6px; margin-top: 8px; overflow-x: auto; padding-bottom: 2px; }
.thumb { flex: 0 0 auto; width: 58px; aspect-ratio: 16 / 10; border-radius: 6px; overflow: hidden; border: 0; padding: 0; cursor: pointer; opacity: .6; transition: opacity .12s; }
.thumb:hover { opacity: .85; }
.thumb.active { opacity: 1; box-shadow: 0 0 0 2px var(--mantine-color-grape-6); }
.thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pnpm -C frontend test --run src/features/listings/DrawerImageGallery.test.tsx`
Expected: PASS (both).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/listings/DrawerImageGallery.*
git commit -m "feat(listings): large-primary + thumbnail gallery for the detail drawer"
```

---

### Task 4: `DrawerHero`

**Files:**
- Create: `frontend/src/features/listings/DrawerHero.tsx`, `DrawerHero.module.css`, `DrawerHero.test.tsx`

**Interfaces:**
- Consumes: `scoreColor`, `scoreLabel`, `formatScore`, `scoreBand` from `./scoreBands`; `DrawerImageGallery`; `AllInComponents`, `PropertyImage` from `./types`/`./api`.
- Produces:
```ts
DrawerHero(props: {
  name: string; address: string;
  images: PropertyImage[]; imagesLoading: boolean;
  score: number | null;           // group.displayScore.total
  allIn: number | null;           // composition.total
  estimated: number | null;       // composition.estimated_total
  bedsBaths: string | null;       // e.g. "Studio · 1 bath" | "2 bd · 2 ba"
}): JSX.Element
```

The score tile: flat tint `color-mix(in srgb, var(--mantine-color-<band>-6) 14%, var(--mantine-color-body))` via a `data-band` attr → CSS; big serif number + `/15` + `✦` when `scoreBand===0`; `scoreLabel` beneath. All-in tile: `$allIn` + `~$est estimated`. Home tile: `bedsBaths`. When `score===null`, show a muted "Not scored yet" tile instead of the number.

- [ ] **Step 1: Write the failing test**

```tsx
// DrawerHero.test.tsx
import { render, screen } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { DrawerHero } from "./DrawerHero";

const wrap = (ui: React.ReactNode) => render(<MantineProvider>{ui}</MantineProvider>);

it("renders identity, the score with its label, all-in, and beds/baths", () => {
  wrap(<DrawerHero name="Maple Court" address="1420 Alder St" images={[]} imagesLoading={false}
    score={12.5} allIn={1845} estimated={210} bedsBaths="Studio · 1 bath" />);
  expect(screen.getByRole("heading", { name: "Maple Court" })).toBeInTheDocument();
  expect(screen.getByText("1420 Alder St")).toBeInTheDocument();
  expect(screen.getByText("12.5")).toBeInTheDocument();
  expect(screen.getByText("Exceptional Match")).toBeInTheDocument();
  expect(screen.getByText("$1,845")).toBeInTheDocument();
  expect(screen.getByText(/210 estimated/)).toBeInTheDocument();
  expect(screen.getByText("Studio · 1 bath")).toBeInTheDocument();
});

it("shows a not-scored tile when score is null", () => {
  wrap(<DrawerHero name="X" address="Y" images={[]} imagesLoading={false}
    score={null} allIn={null} estimated={null} bedsBaths={null} />);
  expect(screen.getByText(/Not scored yet/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm -C frontend test --run src/features/listings/DrawerHero.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement** (structure from preview `.hero`/`.stats`; use `formatScore` for the number and `.toLocaleString()` for money)

```tsx
// DrawerHero.tsx
import { Title } from "@mantine/core";
import { IconMapPin } from "@tabler/icons-react";
import type { PropertyImage } from "./api";
import { DrawerImageGallery } from "./DrawerImageGallery";
import { formatScore, scoreBand, scoreColor, scoreLabel } from "./scoreBands";
import classes from "./DrawerHero.module.css";

export function DrawerHero({ name, address, images, imagesLoading, score, allIn, estimated, bedsBaths }: {
  name: string; address: string; images: PropertyImage[]; imagesLoading: boolean;
  score: number | null; allIn: number | null; estimated: number | null; bedsBaths: string | null;
}) {
  const band = score === null ? null : scoreColor(score).replace("score", "").toLowerCase();
  return (
    <div className={classes.hero}>
      <div className={classes.eyebrow}>Listing</div>
      <Title order={3} className={classes.title}>{name}</Title>
      <div className={classes.addr}><IconMapPin size={13} stroke={2} /> {address}</div>
      <div className={classes.gallery}><DrawerImageGallery images={images} loading={imagesLoading} /></div>
      <div className={classes.stats}>
        {score === null ? (
          <div className={`${classes.stat} ${classes.notScored}`}>Not scored yet</div>
        ) : (
          <div className={classes.scoreStat} data-band={band}>
            <div className={classes.scoreNum}>
              {formatScore(score)}<small>/15</small>{scoreBand(score) === 0 && <span className={classes.exc}>✦</span>}
            </div>
            <div className={classes.matchTag}>{scoreLabel(score)}</div>
          </div>
        )}
        <div className={classes.stat}>
          <div className={classes.statLabel}>All-in / mo</div>
          <div className={classes.statBig}>{allIn === null ? "—" : `$${allIn.toLocaleString()}`}</div>
          {estimated ? <div className={classes.statSub}>~${estimated.toLocaleString()} estimated</div> : null}
        </div>
        <div className={classes.stat}>
          <div className={classes.statLabel}>Home</div>
          <div className={classes.statBig}>{bedsBaths ?? "—"}</div>
        </div>
      </div>
    </div>
  );
}
```

```css
/* DrawerHero.module.css — geometry per preview .hero/.stats; flat tint via data-band */
.hero { padding: 4px 2px; }
.eyebrow { font-size: 11px; letter-spacing: .09em; text-transform: uppercase; color: var(--mantine-color-dimmed); font-weight: 600; }
.title { font-size: 26px; line-height: 1.15; margin: 3px 0 4px; }
.addr { font-size: 13.5px; color: var(--mantine-color-text); opacity: .8; display: flex; align-items: center; gap: 7px; }
.gallery { margin: 16px 0 4px; }
.stats { display: grid; grid-template-columns: auto 1fr 1fr; gap: 10px; margin: 16px 0 6px; }
.stat { border-radius: 12px; padding: 12px 14px; border: 1px solid var(--mantine-color-default-border); background: var(--mantine-color-default); display: flex; flex-direction: column; justify-content: center; gap: 2px; }
.notScored { align-items: flex-start; color: var(--mantine-color-dimmed); font-size: 13px; }
.scoreStat { border-radius: 12px; padding: 12px 16px; display: flex; flex-direction: column; gap: 2px; }
.scoreStat[data-band="highest"] { background: color-mix(in srgb, var(--mantine-color-teal-6) 14%, var(--mantine-color-body)); border: 1px solid color-mix(in srgb, var(--mantine-color-teal-6) 24%, var(--mantine-color-default-border)); }
.scoreStat[data-band="high"] { background: color-mix(in srgb, var(--mantine-color-green-6) 14%, var(--mantine-color-body)); border: 1px solid color-mix(in srgb, var(--mantine-color-green-6) 24%, var(--mantine-color-default-border)); }
.scoreStat[data-band="good"] { background: color-mix(in srgb, var(--mantine-color-lime-6) 14%, var(--mantine-color-body)); border: 1px solid color-mix(in srgb, var(--mantine-color-lime-6) 24%, var(--mantine-color-default-border)); }
.scoreStat[data-band="mid"] { background: color-mix(in srgb, var(--mantine-color-yellow-6) 14%, var(--mantine-color-body)); border: 1px solid color-mix(in srgb, var(--mantine-color-yellow-6) 24%, var(--mantine-color-default-border)); }
.scoreStat[data-band="low"] { background: color-mix(in srgb, var(--mantine-color-orange-6) 14%, var(--mantine-color-body)); border: 1px solid color-mix(in srgb, var(--mantine-color-orange-6) 24%, var(--mantine-color-default-border)); }
.scoreStat[data-band="poor"], .scoreStat[data-band="poorest"] { background: color-mix(in srgb, var(--mantine-color-red-6) 14%, var(--mantine-color-body)); border: 1px solid color-mix(in srgb, var(--mantine-color-red-6) 24%, var(--mantine-color-default-border)); }
.scoreNum { font-family: var(--mantine-font-family-headings, serif); font-size: 34px; font-weight: 700; line-height: 1; display: flex; align-items: baseline; gap: 3px; }
.scoreStat[data-band="highest"] .scoreNum { color: var(--mantine-color-teal-7); }
.scoreStat[data-band="high"] .scoreNum { color: var(--mantine-color-green-7); }
.scoreStat[data-band="good"] .scoreNum { color: var(--mantine-color-lime-7); }
.scoreStat[data-band="mid"] .scoreNum { color: var(--mantine-color-yellow-7); }
.scoreStat[data-band="low"] .scoreNum { color: var(--mantine-color-orange-7); }
.scoreStat[data-band="poor"] .scoreNum, .scoreStat[data-band="poorest"] .scoreNum { color: var(--mantine-color-red-7); }
.scoreNum small { font-size: 13px; font-weight: 600; color: var(--mantine-color-dimmed); }
.exc { font-size: 16px; }
.statLabel { font-size: 10.5px; letter-spacing: .07em; text-transform: uppercase; color: var(--mantine-color-dimmed); font-weight: 600; }
.statBig { font-size: 20px; font-weight: 700; font-family: var(--mantine-font-family-headings, serif); }
.statSub { font-size: 12px; color: var(--mantine-color-dimmed); }
.matchTag { font-size: 11.5px; font-weight: 600; }
.scoreStat[data-band="highest"] .matchTag { color: var(--mantine-color-teal-7); }
.scoreStat[data-band="high"] .matchTag { color: var(--mantine-color-green-7); }
.scoreStat[data-band="good"] .matchTag { color: var(--mantine-color-lime-7); }
.scoreStat[data-band="mid"] .matchTag { color: var(--mantine-color-yellow-7); }
.scoreStat[data-band="low"] .matchTag { color: var(--mantine-color-orange-7); }
.scoreStat[data-band="poor"] .matchTag, .scoreStat[data-band="poorest"] .matchTag { color: var(--mantine-color-red-7); }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pnpm -C frontend test --run src/features/listings/DrawerHero.test.tsx`
Expected: PASS (both).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/listings/DrawerHero.*
git commit -m "feat(listings): DrawerHero summary with score/all-in/beds tiles"
```

---

### Task 5: Restyle `CriterionBreakdown` (baseline + delta tally)

**Files:**
- Modify: `frontend/src/features/listings/CriterionBreakdown.tsx`
- Create: `frontend/src/features/listings/CriterionBreakdown.module.css`
- Modify: `frontend/src/features/listings/CriterionBreakdown.test.tsx` (add rows; keep existing)

**Preserve:** gate-fired `Alert`; `EvidenceButton` (one `ⓘ` per row); `OverrideControl`; draft override + revert; property/floor-plan grouping; `formatCriterionValue`. **Change:** table → CSS-grid rows; a **Baseline 10.0** row on top; the points column shows the signed `criterion.delta` (`+1.5`/`−2.0`/`0`, colored sage/brick/neutral) instead of a badge; override shown as a plum dot + plum value (not a word badge); applicability/`sources disagree`/`awaiting grade` become one quiet text flag. A **Total score X / 15** row at the bottom (colored by `scoreColor`, `✦` on band 0) + the one-line legend. Compute total from `breakdown.total`; baseline from `breakdown.base`.

- [ ] **Step 1: Add failing tests** (append to `CriterionBreakdown.test.tsx`)

```tsx
it("shows the baseline, a signed delta per criterion, and the total out of 15", () => {
  // render with the file's existing helper/fixture that provides a breakdown
  // whose base=10, total=12.5, and a criterion with delta +1.5
  renderBreakdown({ base: 10, total: 12.5, criteria: [
    { key: "pets", value: "cats_dogs", matched: null, delta: 1.5 },
  ], gates: [] });
  expect(screen.getByText("Baseline")).toBeInTheDocument();
  expect(screen.getByText("10.0")).toBeInTheDocument();
  expect(screen.getByText("+1.5")).toBeInTheDocument();
  expect(screen.getByText(/12\.5/)).toBeInTheDocument();
  expect(screen.getByText("/ 15")).toBeInTheDocument();
});

it("renders one evidence affordance per criterion that has an extraction", () => {
  renderBreakdown({ base: 10, total: 11, criteria: [
    { key: "pets", value: "cats_dogs", matched: null, delta: 1 },
  ], gates: [] }, /* with an extraction for pets */);
  expect(screen.getAllByLabelText("evidence")).toHaveLength(1);
});
```

(Use the test file's existing render helper/fixtures; if none, add a `renderBreakdown(breakdown, extractions=[])` helper wrapping `MantineProvider` + `ListingDetailDraftProvider` mirroring the existing tests.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pnpm -C frontend test --run src/features/listings/CriterionBreakdown.test.tsx`
Expected: FAIL — no "Baseline"/delta/total markup yet.

- [ ] **Step 3: Implement the restyle** — replace the `Table` return with grid rows.

Add `import classes from "./CriterionBreakdown.module.css";` and `import { scoreColor, scoreBand, formatScore } from "./scoreBands";`. Keep the gate `Alert` branch unchanged. Replace the `<Table>…</Table>` with:

```tsx
<div className={classes.wrap}>
  <div className={classes.baseRow}>
    <span className={classes.baseLbl}>Baseline <span className={classes.baseNote}>— all your needs met</span></span>
    <span className={classes.baseVal}>{breakdown.base.toFixed(1)}</span>
  </div>
  {displayedCriteria.map((criterion, index) => {
    const entry = catalogByKey.get(criterion.key);
    const section = entry?.fact_scope === "property" ? "Property facts" : "Floor plan facts";
    const previous = index > 0 ? catalogByKey.get(displayedCriteria[index - 1].key) : undefined;
    const previousSection = previous?.fact_scope === "property" ? "Property facts" : "Floor plan facts";
    const extraction = extractionForFloorPlan(extractions, criterion.key, floorPlanId);
    const savedOverrideRow = effectiveOverrides.get(criterion.key);
    const savedOverride = overriddenKeys.has(criterion.key);
    const draftOverride = draftOverrides.get(criterion.key);
    const isPending = draftOverride !== undefined;
    const displayVal = isPending ? draftOverride.value : criterion.value;
    return (
      <Fragment key={criterion.key}>
        {(index === 0 || section !== previousSection) && (
          <div className={classes.groupLabel}>{section}</div>
        )}
        <CriterionRow
          criterion={criterion} entry={entry} extraction={extraction} displayValue={displayVal}
          savedOverride={savedOverride} isPending={isPending} isMobile={isMobile} floorPlanId={floorPlanId}
          onRevert={() => setDraftOverride(criterion.key, {
            value: null, note: REVERT_NOTE,
            target_scope: savedOverrideRow?.target_scope ?? "property",
            floor_plan_id: savedOverrideRow?.floor_plan_id ?? null,
            applicability: savedOverrideRow?.applicability ?? null,
          })}
        />
      </Fragment>
    );
  })}
  <div className={classes.legend}>Each criterion nudges the baseline · above 10 also meets your wants · capped 0–15.</div>
  <div className={classes.totalRow}>
    <span className={classes.totalLbl}>Total score</span>
    <span className={classes.totalVal} data-band={scoreColor(breakdown.total).replace("score","").toLowerCase()}>
      {formatScore(breakdown.total)}{scoreBand(breakdown.total) === 0 && <span className={classes.exc}>✦</span>}
      <span className={classes.denom}> / 15</span>
    </span>
  </div>
</div>
```

Rewrite `CriterionRow` to a grid row (`classes.crit`): name cell (override plum dot when `savedOverride && !isPending`, label, one quiet text flag for applicability/`disputed`/`awaiting grade`, then `EvidenceButton`); value cell (`formatCriterionValue`, plum when overridden); delta cell:

```tsx
<span className={`${classes.delta} ${criterion.delta > 0 ? classes.pos : criterion.delta < 0 ? classes.neg : classes.zero}`}>
  {criterion.delta > 0 ? "+" : ""}{criterion.delta.toFixed(1)}
</span>
```

Keep `OverrideControl` and the revert `ActionIcon` in a trailing actions group as today. Preserve `EvidenceButton` `aria-label="evidence"`.

```css
/* CriterionBreakdown.module.css — see preview .crit/.baseRow/.delta/.totalRow */
.wrap { display: flex; flex-direction: column; }
.baseRow { display: flex; justify-content: space-between; align-items: baseline; padding: 2px 0 8px; }
.baseLbl { font-size: 12.5px; color: var(--mantine-color-dimmed); }
.baseNote { opacity: .8; }
.baseVal { font-size: 13.5px; font-weight: 700; color: var(--mantine-color-text); font-variant-numeric: tabular-nums; }
.groupLabel { font-size: 10.5px; letter-spacing: .08em; text-transform: uppercase; color: var(--mantine-color-dimmed); font-weight: 700; margin: 12px 0 6px; }
.crit { display: grid; grid-template-columns: 1fr auto 52px auto; align-items: center; gap: 10px; padding: 7px 0; border-top: 1px solid var(--mantine-color-default-border); }
.delta { font-size: 13.5px; font-weight: 700; font-variant-numeric: tabular-nums; text-align: right; }
.pos { color: var(--mantine-color-green-7); }
.neg { color: var(--mantine-color-red-6); }
.zero { color: var(--mantine-color-dimmed); font-weight: 600; }
.dot { width: 6px; height: 6px; border-radius: 50%; display: inline-block; background: var(--mantine-color-grape-6); }
.overridden { color: var(--mantine-color-grape-7); }
.flag { font-size: 11px; color: var(--mantine-color-dimmed); font-weight: 500; }
.legend { font-size: 11px; color: var(--mantine-color-dimmed); margin-top: 10px; }
.totalRow { display: flex; justify-content: space-between; align-items: baseline; margin-top: 10px; padding-top: 12px; border-top: 1.5px solid var(--mantine-color-default-border); }
.totalLbl { font-size: 13px; font-weight: 600; color: var(--mantine-color-text); }
.totalVal { font-family: var(--mantine-font-family-headings, serif); font-size: 20px; font-weight: 700; }
.totalVal[data-band="highest"] { color: var(--mantine-color-teal-7); }
.totalVal[data-band="high"] { color: var(--mantine-color-green-7); }
.totalVal[data-band="good"] { color: var(--mantine-color-lime-7); }
.totalVal[data-band="mid"] { color: var(--mantine-color-yellow-7); }
.totalVal[data-band="low"] { color: var(--mantine-color-orange-7); }
.totalVal[data-band="poor"], .totalVal[data-band="poorest"] { color: var(--mantine-color-red-7); }
.denom { font-size: 13px; color: var(--mantine-color-dimmed); font-family: var(--mantine-font-family); font-weight: 400; }
.exc { font-size: 15px; }
:global([data-mantine-color-scheme="dark"]) .crit { border-top-color: var(--mantine-color-dark-4); }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pnpm -C frontend test --run src/features/listings/CriterionBreakdown.test.tsx`
Expected: PASS (new + existing). Fix any existing test that asserted `Table`/badge-specific text.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/listings/CriterionBreakdown.tsx frontend/src/features/listings/CriterionBreakdown.module.css frontend/src/features/listings/CriterionBreakdown.test.tsx
git commit -m "feat(listings): additive baseline+delta score breakdown, fewer badges"
```

---

### Task 6: Restyle `AllInCost` breakdown (dots, flush amounts, result box, utilities)

**Files:**
- Modify: `frontend/src/features/listings/AllInCost.tsx` (only `AllInBreakdown`; leave `AllInCell`, `AllInWarningIcon`, `AllInOverrideControl` behavior intact)
- Create: `frontend/src/features/listings/AllInCost.module.css`
- Modify: `frontend/src/features/listings/AllInCost.test.tsx`

**Change:** `AllInBreakdown` table → grid rows: a small state dot (actual=green, estimated=yellow, unknown=hollow) at the front of each component name; amounts flush right; the total becomes a contained **result box** (`All-in / mo` + `$total`) instead of a table footer row; add a "Monthly cost" sub-label above rows. `component.tag` drives the dot. Keep the `badges`/`CompositionBadges` (warnings) and the `overridden` marker. Utilities-included is rendered by `DrawerShell` (Task 11) as a promoted block — keep `UtilitiesIncludedLine` data but move its styling there.

- [ ] **Step 1: Add a failing test**

```tsx
it("renders component rows with flush amounts and an all-in result box", () => {
  renderBreakdown({ mode: "conservative", total: 1845, estimated_total: 210, overridden: false, badges: [],
    components: [
      { name: "base_rent", amount: 1635, tag: "actual", note: null },
      { name: "utilities", amount: 210, tag: "estimated", note: "gas heat" },
    ] });
  expect(screen.getByText("base rent")).toBeInTheDocument();
  expect(screen.getByText("$1,635")).toBeInTheDocument();
  expect(screen.getByText("All-in / mo")).toBeInTheDocument();
  expect(screen.getByText("$1,845")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `pnpm -C frontend test --run src/features/listings/AllInCost.test.tsx`
Expected: FAIL — new markup absent.

- [ ] **Step 3: Implement** — replace the `AllInBreakdown` `Table` block:

```tsx
import classes from "./AllInCost.module.css";
// inside AllInBreakdown, after the null guard:
return (
  <Stack gap="xs">
    {composition.badges.length > 0 && (
      <Group gap={6}><CompositionBadges badges={composition.badges} /></Group>
    )}
    <div className={classes.subhead}>Monthly cost</div>
    {composition.components.map((component, index) => (
      <div className={classes.row} key={`${component.name}:${index}`}>
        <div className={classes.name}>
          <span className={`${classes.qd} ${classes[component.tag] ?? classes.unknown}`} title={component.tag} />
          {component.name.replaceAll("_", " ")}
          {component.note && <div className={classes.note}>{component.note}</div>}
        </div>
        <div className={classes.amt}>
          {component.amount === null ? <span className={classes.dim}>unknown</span> : `$${component.amount.toLocaleString()}`}
        </div>
      </div>
    ))}
    <div className={classes.legend}>
      <span><span className={`${classes.qd} ${classes.actual}`} />actual</span>
      <span><span className={`${classes.qd} ${classes.estimated}`} />estimated</span>
      <span><span className={`${classes.qd} ${classes.unknown}`} />unknown</span>
    </div>
    <div className={classes.resultBox}>
      <div className={classes.rl}>All-in / mo {composition.overridden && (
        <Badge size="xs" color="manual" variant="light">override</Badge>)}</div>
      <div className={classes.rv}>{composition.total === null ? "unknown" : `$${composition.total.toLocaleString()}`}</div>
    </div>
  </Stack>
);
```

```css
/* AllInCost.module.css — preview .costRow/.qd/.allInBox/.utilBlock */
.subhead { font-size: 11px; letter-spacing: .06em; text-transform: uppercase; color: var(--mantine-color-dimmed); font-weight: 700; margin: 2px 0 8px; }
.row { display: grid; grid-template-columns: 1fr auto; align-items: center; gap: 12px; padding: 6px 0; }
.name { font-size: 13.5px; color: var(--mantine-color-text); display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.note { flex-basis: 100%; padding-left: 15px; font-size: 11.5px; color: var(--mantine-color-dimmed); }
.amt { font-size: 13.5px; font-weight: 600; text-align: right; font-variant-numeric: tabular-nums; }
.dim { color: var(--mantine-color-dimmed); font-weight: 500; font-style: italic; }
.qd { width: 7px; height: 7px; border-radius: 50%; flex: none; display: inline-block; }
.actual { background: var(--mantine-color-green-6); }
.estimated { background: var(--mantine-color-yellow-6); }
.unknown { background: transparent; border: 1px solid var(--mantine-color-dimmed); box-sizing: border-box; }
.legend { display: flex; gap: 14px; font-size: 11px; color: var(--mantine-color-dimmed); margin: 10px 0 2px; }
.legend span { display: inline-flex; align-items: center; gap: 5px; }
.resultBox { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 10px; padding: 11px 14px; border-radius: 10px; background: color-mix(in srgb, var(--mantine-color-grape-6) 8%, var(--mantine-color-default)); border: 1px solid color-mix(in srgb, var(--mantine-color-grape-6) 22%, var(--mantine-color-default-border)); }
.rl { font-size: 13.5px; font-weight: 700; display: flex; align-items: center; gap: 8px; }
.rv { font-family: var(--mantine-font-family-headings, serif); font-size: 22px; font-weight: 700; }
```

- [ ] **Step 4: Run to verify passes**

Run: `pnpm -C frontend test --run src/features/listings/AllInCost.test.tsx`
Expected: PASS (new + existing; fix any table-specific assertions).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/listings/AllInCost.tsx frontend/src/features/listings/AllInCost.module.css frontend/src/features/listings/AllInCost.test.tsx
git commit -m "feat(listings): all-in breakdown with state dots and result box"
```

---

### Task 7: Restyle `FeeChecklist` rows

**Files:**
- Modify: `frontend/src/features/listings/FeeChecklist.tsx` (+ new `FeeChecklist.module.css`)
- Modify: `frontend/src/features/listings/FeeChecklist.test.tsx` if present (else none)

**Change (presentation only):** keep monthly/one-time slot logic, `value_state`, manual-entry `Popover`, revert, `moveInEstimate`/`basisLabel`. Convert each fee row from a `Table` row with a `STATE_COLOR` badge to a grid row: a state dot at the front (extracted=green, estimated=yellow, manual=plum, unknown=hollow — reuse the `.qd` convention), the label + subtitle, amount flush right, and the same edit/revert affordances trailing. Section sub-labels "Monthly" / "Move-in & one-time". No checkboxes, no assignees (not in the model).

- [ ] **Step 1: Add a failing test** (co-locate a new `FeeChecklist.test.tsx` if none exists)

```tsx
import { render, screen } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { ListingDetailDraftProvider } from "./ListingDetailDraft";
// minimal fixture: one extracted monthly fee slot with amount 50
it("shows a fee with a flush amount and a state dot", () => {
  renderFees(/* fees=[{slot:'application', value_state:'extracted', amount:50,...}] */);
  expect(screen.getByText("$50")).toBeInTheDocument();
  expect(screen.getByTestId("fee-state-application")).toHaveAttribute("data-state", "extracted");
});
```

(Add `data-testid={`fee-state-${slot}`} data-state={entry.value_state}` to the dot for the assertion.)

- [ ] **Step 2: Run to verify it fails**

Run: `pnpm -C frontend test --run src/features/listings/FeeChecklist.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement** — replace the `FeeRow` `Table.Tr` markup with a grid row using `FeeChecklist.module.css` (mirror Task 6's `.row/.qd/.amt`, add a `.plum` dot for `manual`). Keep every hook, popover, and estimate calc. Keep the `Table` container only if other logic depends on it; otherwise a `<div className={classes.list}>`.

```css
/* FeeChecklist.module.css */
.list { display: flex; flex-direction: column; }
.row { display: grid; grid-template-columns: 1fr auto auto; align-items: center; gap: 10px; padding: 6px 0; }
.qd { width: 7px; height: 7px; border-radius: 50%; flex: none; display: inline-block; }
.extracted { background: var(--mantine-color-green-6); }
.estimated { background: var(--mantine-color-yellow-6); }
.manual { background: var(--mantine-color-grape-6); }
.unknown { background: transparent; border: 1px solid var(--mantine-color-dimmed); box-sizing: border-box; }
.name { font-size: 13px; display: flex; align-items: center; gap: 8px; }
.sub { padding-left: 15px; font-size: 11.5px; color: var(--mantine-color-dimmed); }
.amt { font-size: 13px; font-weight: 600; font-variant-numeric: tabular-nums; text-align: right; }
.subhead { font-size: 11px; letter-spacing: .06em; text-transform: uppercase; color: var(--mantine-color-dimmed); font-weight: 700; margin: 16px 0 8px; }
```

- [ ] **Step 4: Run to verify passes + no regressions**

Run: `pnpm -C frontend test --run src/features/listings/FeeChecklist.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/listings/FeeChecklist.tsx frontend/src/features/listings/FeeChecklist.module.css frontend/src/features/listings/FeeChecklist.test.tsx
git commit -m "feat(listings): restyle fees checklist to state dots + flush amounts"
```

---

### Task 8: Restyle `FloorPlanPins`

**Files:**
- Modify: `frontend/src/features/listings/FloorPlanPins.tsx` (+ `FloorPlanPins.module.css`)

**Change:** keep the `Radio.Group` draft-pin semantics (`"best"` + plan ids, `setDraftPin`, `saving`). Restyle each `Radio.Card` to the preview `.plan` row: pin indicator, plan name with the per-plan **score chip on the name line** (band color via `scoreColor`), meta line (beds/baths · rent range · sqft · avail), rent emphasized on the right + availability. Score chip uses `scoreColor(planScore.total)` and `formatScore`.

- [ ] **Step 1: Add a failing test**

```tsx
it("shows each plan's score chip on the name line", () => {
  renderPins(/* group with one plan scored 11.0 */);
  expect(screen.getByText("11")).toBeInTheDocument(); // formatScore(11)
  // chip sits with the plan name, not in a separate right column
  expect(screen.getByText("The Birch")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `pnpm -C frontend test --run src/features/listings/FloorPlanPins.test.tsx`
Expected: FAIL — no co-located test yet / new markup absent.

- [ ] **Step 3: Implement** the row restyle with `FloorPlanPins.module.css` (`.plan`, `.planScore.<band>`, `.planRight`), using `scoreColor`/`formatScore` from `./scoreBands`. Keep `formatRange`, `unit_types`. `Radio.Card`/`Radio.Indicator` stay for a11y + selection.

```css
/* FloorPlanPins.module.css — preview .plan/.planScore/.planRight */
.pn { display: flex; align-items: center; gap: 8px; font-weight: 600; }
.planScore { font-size: 11px; font-weight: 700; font-variant-numeric: tabular-nums; padding: 0 6px; border-radius: 5px; }
.highest, .high { color: var(--mantine-color-teal-7); background: color-mix(in srgb, var(--mantine-color-teal-6) 14%, transparent); }
.good { color: var(--mantine-color-lime-7); background: color-mix(in srgb, var(--mantine-color-lime-6) 16%, transparent); }
.mid { color: var(--mantine-color-yellow-7); background: color-mix(in srgb, var(--mantine-color-yellow-6) 18%, transparent); }
.low { color: var(--mantine-color-orange-7); background: color-mix(in srgb, var(--mantine-color-orange-6) 16%, transparent); }
.poor, .poorest { color: var(--mantine-color-red-7); background: color-mix(in srgb, var(--mantine-color-red-6) 14%, transparent); }
```

(Map `scoreColor(...).replace("score","").toLowerCase()` → the chip class.)

- [ ] **Step 4: Run to verify passes**

Run: `pnpm -C frontend test --run src/features/listings/FloorPlanPins.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/listings/FloorPlanPins.tsx frontend/src/features/listings/FloorPlanPins.module.css frontend/src/features/listings/FloorPlanPins.test.tsx
git commit -m "feat(listings): restyle floor-plan pins with inline score chips"
```

---

### Task 9: `StarRating` + `TeamRatings`, extend `RatingControl`

**Files:**
- Create: `frontend/src/features/collaboration/StarRating.tsx`, `StarRating.module.css`, `StarRating.test.tsx`
- Create: `frontend/src/features/collaboration/TeamRatings.tsx`, `TeamRatings.test.tsx`
- Modify: `frontend/src/features/collaboration/RatingControl.tsx`

**Interfaces:**
- `StarRating({ value, size? }: { value: number; size?: "sm" | "lg" })` — read-only 5-star with half-step fill = `value / 5 * 100%`.
- `TeamRatings({ listingId, unitGroupKey, members, currentUserId }: { listingId: string; unitGroupKey: string; members: HuntMember[]; currentUserId?: string })` — lists each member's rating for this group (star + value or "Not rated yet"), plus average of present ratings.

- [ ] **Step 1: Failing test for `StarRating`**

```tsx
// StarRating.test.tsx
import { render } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { StarRating } from "./StarRating";
it("fills to the rating fraction", () => {
  const { container } = render(<MantineProvider><StarRating value={4.5} /></MantineProvider>);
  const fill = container.querySelector('[data-fill]') as HTMLElement;
  expect(fill.style.width).toBe("90%");
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `pnpm -C frontend test --run src/features/collaboration/StarRating.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `StarRating`**

```tsx
// StarRating.tsx
import classes from "./StarRating.module.css";
export function StarRating({ value, size = "sm" }: { value: number; size?: "sm" | "lg" }) {
  const pct = Math.max(0, Math.min(100, (value / 5) * 100));
  return (
    <span className={`${classes.stars} ${classes[size]}`} aria-label={`${value} of 5`}>
      <span className={classes.base}>★★★★★</span>
      <span className={classes.fill} data-fill style={{ width: `${pct}%` }}>★★★★★</span>
    </span>
  );
}
```

```css
/* StarRating.module.css */
.stars { position: relative; display: inline-block; white-space: nowrap; line-height: 1; }
.base { color: color-mix(in srgb, var(--mantine-color-dimmed) 42%, transparent); }
.fill { position: absolute; left: 0; top: 0; overflow: hidden; color: var(--mantine-color-yellow-6); }
.lg { font-size: 26px; letter-spacing: 3px; }
.sm { font-size: 14px; letter-spacing: 1.5px; }
```

- [ ] **Step 4: Run to verify passes**

Run: `pnpm -C frontend test --run src/features/collaboration/StarRating.test.tsx`
Expected: PASS.

- [ ] **Step 5: Failing test for `TeamRatings`**

```tsx
// TeamRatings.test.tsx — mock useRatings to return two ratings for the group
vi.mock("./api", async (orig) => ({ ...(await orig()),
  useRatings: () => ({ data: [
    { hunt_listing_id: "l", unit_group_key: "g", user_id: "u1", rating: 4 },
    { hunt_listing_id: "l", unit_group_key: "g", user_id: "u2", rating: 4.5 },
  ] }) }));
it("lists members' ratings, a not-rated state, and the average", () => {
  renderTeam({ members: [
    { user_id: "u1", display_name: "Amara", color: null },
    { user_id: "u2", display_name: "Maya", color: null },
    { user_id: "u3", display_name: "Dev", color: null },
  ] });
  expect(screen.getByText("Amara")).toBeInTheDocument();
  expect(screen.getByText("Not rated yet")).toBeInTheDocument(); // Dev
  expect(screen.getByText(/avg 4\.3/)).toBeInTheDocument();       // (4 + 4.5)/2 = 4.25 → 4.3
});
```

- [ ] **Step 6: Run to verify it fails**

Run: `pnpm -C frontend test --run src/features/collaboration/TeamRatings.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 7: Implement `TeamRatings`** (uses `useRatings`, `StarRating`, `memberColor`)

```tsx
// TeamRatings.tsx
import { useRatings, type HuntMember } from "./api";
import { StarRating } from "./StarRating";
import { memberColor } from "./memberColors";
import classes from "./TeamRatings.module.css";

export function TeamRatings({ listingId, unitGroupKey, members }: {
  listingId: string; unitGroupKey: string; members: HuntMember[]; currentUserId?: string;
}) {
  const { data: ratings = [] } = useRatings(listingId);
  const byUser = new Map(ratings.filter((r) => r.unit_group_key === unitGroupKey).map((r) => [r.user_id, r.rating]));
  const present = members.map((m) => byUser.get(m.user_id)).filter((v): v is number => v != null);
  const avg = present.length ? present.reduce((a, b) => a + b, 0) / present.length : null;
  const initials = (name: string | null) => (name ?? "?").trim().charAt(0).toUpperCase() || "?";
  return (
    <div className={classes.team}>
      <div className={classes.head}>
        <span>The team</span>
        {avg != null && <span className={classes.avg}>avg {avg.toFixed(1)} · {present.length} of {members.length} rated</span>}
      </div>
      {members.map((m) => {
        const r = byUser.get(m.user_id);
        return (
          <div className={classes.rater} key={m.user_id}>
            <span className={classes.av} style={{ background: memberColor(m.color) }}>{initials(m.display_name)}</span>
            <span className={classes.name}>{m.display_name ?? "Member"}</span>
            {r != null ? (<><StarRating value={r} /><span className={classes.val}>{r.toFixed(1)}</span></>)
              : <span className={classes.none}>Not rated yet</span>}
          </div>
        );
      })}
    </div>
  );
}
```

```css
/* TeamRatings.module.css — preview .teamRate/.rater */
.team { border-top: 1px solid var(--mantine-color-default-border); padding-top: 12px; }
.head { font-size: 11px; letter-spacing: .06em; text-transform: uppercase; color: var(--mantine-color-dimmed); font-weight: 700; display: flex; justify-content: space-between; margin-bottom: 8px; }
.avg { text-transform: none; letter-spacing: 0; color: var(--mantine-color-text); }
.rater { display: flex; align-items: center; gap: 10px; padding: 5px 0; }
.av { width: 26px; height: 26px; border-radius: 50%; display: grid; place-items: center; font-size: 11px; font-weight: 700; color: #fff; flex: none; }
.name { font-size: 13px; }
.rater :global(.mantine-focus-auto) { margin-left: auto; }
.val { font-size: 12.5px; font-weight: 700; color: var(--mantine-color-text); width: 26px; text-align: right; font-variant-numeric: tabular-nums; }
.none { margin-left: auto; font-size: 12px; color: var(--mantine-color-dimmed); font-style: italic; }
```

(Put the `StarRating` in a wrapper with `margin-left:auto` so it right-aligns; add `.rstars { margin-left: auto; }` and wrap accordingly.)

- [ ] **Step 8: Run to verify passes**

Run: `pnpm -C frontend test --run src/features/collaboration/TeamRatings.test.tsx`
Expected: PASS.

- [ ] **Step 9: Extend `RatingControl`** — your rating as half-step stars + render `TeamRatings`

```tsx
// RatingControl.tsx
import { Group, Rating, Text } from "@mantine/core";
import { useAuth } from "../../auth/useAuth";
import { useMembers } from "./api";
import { useRatings, useSetRating } from "./api";
import { TeamRatings } from "./TeamRatings";

export function RatingControl({ listingId, unitGroupKey, huntId, color = "yellow" }: {
  listingId: string; unitGroupKey: string; huntId: string; color?: string;
}) {
  const { session } = useAuth();
  const { data: ratings = [] } = useRatings(listingId);
  const { data: members = [] } = useMembers(huntId);
  const setRating = useSetRating(listingId, unitGroupKey);
  const current = ratings.find(
    (r) => r.unit_group_key === unitGroupKey && r.user_id === session?.user.id,
  )?.rating ?? null;
  return (
    <div>
      <Group gap="md" align="center" mb="sm">
        <Text size="sm" fw={600}>Your rating</Text>
        <Rating value={current ?? 0} onChange={(v) => setRating.mutate(v)} fractions={2} color={color} size="lg" />
        {current != null && <Text ff="heading" fw={700} ml="auto">{current.toFixed(1)}<Text span size="xs" c="dimmed">/5</Text></Text>}
      </Group>
      <TeamRatings listingId={listingId} unitGroupKey={unitGroupKey} members={members} currentUserId={session?.user.id} />
    </div>
  );
}
```

Note: `RatingControl` gains a required `huntId` prop — update the call site in `DrawerShell` (Task 11). `color` default changes to `yellow` (ochre) to match the star fill.

- [ ] **Step 10: Update the RatingControl test** if one exists (`RatingDots.test.tsx` is a different component — leave it). Run collaboration tests:

Run: `pnpm -C frontend test --run src/features/collaboration`
Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add frontend/src/features/collaboration/StarRating.* frontend/src/features/collaboration/TeamRatings.* frontend/src/features/collaboration/RatingControl.tsx
git commit -m "feat(collaboration): half-step star ratings with team ratings list"
```

---

### Task 10: Restyle `SourcesList` (compact rows)

**Files:**
- Modify: `frontend/src/features/listings/SourcesList.tsx` (+ `SourcesList.module.css`)

**Change:** keep `SingleSourceBadge` (only when `singleSourceReason` set) and the editable Source Policy `Select`. Convert each source `Group` into a compact row: a favicon dot (teal if `is_official`, else neutral), `site_domain` name, `url` host (dimmed, ellipsis), an `official` tag when `is_official`, an external-link `Anchor`. `last_fetched_at` becomes a title/tooltip on the row (declutter) rather than inline text.

- [ ] **Step 1: Add a failing test**

```tsx
it("renders compact source rows and only shows the reason with a single source", () => {
  renderSources({ sources: [
    { id: "1", site_domain: "maplecourt.com", url: "https://maplecourt.com/x", is_official: true, last_fetched_at: null },
    { id: "2", site_domain: "apartments.com", url: "https://apartments.com/y", is_official: false, last_fetched_at: null },
  ], singleSourceReason: null });
  expect(screen.getByText("maplecourt.com")).toBeInTheDocument();
  expect(screen.getByText("official")).toBeInTheDocument();
  expect(screen.queryByTestId("single-source")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `pnpm -C frontend test --run src/features/listings/SourcesList.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement** the compact rows with `SourcesList.module.css` (`.source/.favdot/.tier/.extLink`), keeping the `Select` and `SingleSourceBadge`.

```css
/* SourcesList.module.css — preview .source/.favdot/.tier */
.source { display: flex; align-items: center; gap: 10px; padding: 8px 0; border-top: 1px solid var(--mantine-color-default-border); }
.source:first-of-type { border-top: 0; }
.favdot { width: 9px; height: 9px; border-radius: 50%; flex: none; }
.official { background: var(--mantine-color-teal-6); }
.listing { background: var(--mantine-color-dimmed); }
.name { font-size: 13px; font-weight: 600; white-space: nowrap; }
.host { font-size: 12px; color: var(--mantine-color-dimmed); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; min-width: 0; }
.tier { font-size: 9.5px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; padding: 1px 6px; border-radius: 5px; color: var(--mantine-color-teal-7); background: color-mix(in srgb, var(--mantine-color-teal-6) 15%, transparent); flex: none; }
```

- [ ] **Step 4: Run to verify passes**

Run: `pnpm -C frontend test --run src/features/listings/SourcesList.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/listings/SourcesList.tsx frontend/src/features/listings/SourcesList.module.css frontend/src/features/listings/SourcesList.test.tsx
git commit -m "feat(listings): compact source rows"
```

---

### Task 11: Recompose `DrawerShell` (hero + five SectionCards)

**Files:**
- Modify: `frontend/src/features/listings/ListingDetailDrawer.tsx`

**Change:** replace the `Drawer.Header` title block + the `Stack` of `Section`s with:
- `Drawer.Header` keeps the `CloseButton` only (identity moves into the hero); or keep a minimal title. Recommended: drop the header title, let the hero own identity.
- Body: `DrawerHero` (props from `listing`, `group`, `images`, `composition`), then five `SectionCard`s in order:
  1. **Why this score** — the `CriterionBreakdown` branch (with its loading/unavailable/not-scored fallbacks).
  2. **Cost & fees** — `AllInBreakdown` + `AllInOverrideControl`, then `FeeChecklist`, then the **promoted utilities block** (render `utilities_included` here with the preview `.utilBlock` styling via a small local `UtilitiesBlock`).
  3. **Floor plans** — `FloorPlanPins` (hint = plan count).
  4. **Notes & ratings** — `RatingControl` (now needs `huntId`), then `CommentsSection`.
  5. **Sources** — `SourcesList`.
- Keep the dirty-state save bar (clay-tinted), the discard-confirm `Modal`, close interception, mobile logic, and every data hook exactly as-is.
- `bedsBaths` string built from `group` (reuse `unitLabel`).

- [ ] **Step 1: Add an integration test** `ListingDetailDrawer.test.tsx` (or extend if present)

```tsx
it("renders the hero and the five section cards for a scored listing", () => {
  renderDrawer(/* seeded listing with a scored group, composition, images */);
  expect(screen.getByRole("heading", { name: /Why this score/ })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: /Cost & fees/ })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: /Floor plans/ })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: /Notes & ratings/ })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: /Sources/ })).toBeInTheDocument();
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `pnpm -C frontend test --run src/features/listings/ListingDetailDrawer.test.tsx`
Expected: FAIL — old `Section` titles differ / cards absent.

- [ ] **Step 3: Implement** the recomposition (swap `Section` → `SectionCard`, insert `DrawerHero`, add `UtilitiesBlock`, pass `huntId` to `RatingControl`). Wrap the five cards in a `Stack gap="md"`. Add the `UtilitiesBlock`:

```tsx
function UtilitiesBlock({ extraction }: { extraction: Extraction | undefined }) {
  if (!extraction) return null;
  const included = Array.isArray(extraction.value) ? (extraction.value as string[]) : [];
  return (
    <div className={drawerClasses.utilBlock}>
      <IconDroplet size={18} stroke={2} className={drawerClasses.utilIcon} />
      <div>
        <div className={drawerClasses.utilLabel}>Utilities included</div>
        <div className={drawerClasses.utilValue}>{included.length ? included.map(s => s.replace(/_/g," ")).join(" · ") : "None stated"}</div>
      </div>
    </div>
  );
}
```

Add `ListingDetailDrawer.module.css` with `.utilBlock/.utilIcon/.utilLabel/.utilValue` (preview `.utilBlock`, sage-tinted) and a `.saveBar` (clay-tinted) if migrating the inline save-bar styles.

- [ ] **Step 4: Run to verify passes + full suite**

Run: `pnpm -C frontend test --run src/features/listings/ListingDetailDrawer.test.tsx`
then `pnpm -C frontend test --run`
Expected: PASS across the suite.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/listings/ListingDetailDrawer.tsx frontend/src/features/listings/ListingDetailDrawer.module.css frontend/src/features/listings/ListingDetailDrawer.test.tsx
git commit -m "feat(listings): recompose detail drawer into hero + five topic cards"
```

---

### Task 12: Full verification, screenshots, docs

**Files:**
- Modify: `frontend/UI_DESIGN.md` (flip the drawer log entry from "in progress" to shipped, dated), `frontend/API_ASSUMPTIONS.md` if any hook usage changed (none expected — reuse only).
- Verify: whole frontend.

- [ ] **Step 1: Lint, types, tests, build**

Run: `pnpm -C frontend lint && pnpm -C frontend test --run && pnpm -C frontend build`
Expected: all green.

- [ ] **Step 2: Screenshot both themes** against a seeded scored listing (per the memory workflow: IPv4 vite `npx vite --host 127.0.0.1 --port 5173 --strictPort`, Mailpit magic-link login, the user's own hunt). Capture the drawer open in light and dark; confirm hero tiers, card edges, dot legends, star rows, compact sources, flush amounts, no horizontal scroll, dark-mode contrast.

- [ ] **Step 3: Manual a11y pass** — keyboard focus visible on gallery nav, pins, stars, info popovers; `aria-label`s present; reduced-motion honored.

- [ ] **Step 4: Update `UI_DESIGN.md` decision-log entry** to "shipped (2026-07-23)" and commit docs.

```bash
git add frontend/UI_DESIGN.md docs/superpowers/specs/2026-07-23-listing-detail-drawer-*.md docs/superpowers/plans/2026-07-23-listing-detail-drawer-redesign.md
git commit -m "docs: record listing detail drawer redesign"
```

---

## Self-Review notes (author)

- **Spec coverage:** hero (T4) incl. gallery (T3) + score tile (T1); five cards — Why this score (T5), Cost & fees (T6+T7+utilities in T11), Floor plans (T8), Notes & ratings (T9), Sources (T10); shell recomposition + save bar/modal preserved (T11); flat/tokens/theme-aware constraints in every task; TDD each task; screenshots + docs (T12). Band table + labels (T1) match the engine. ✔
- **Behavior preserved:** overrides/revert (T5), all-in override + warnings (T6), fee slots/manual/estimate (T7), draft pins (T8), rating mutation (T9), source policy edit (T10), draft-save/close-intercept (T11). ✔
- **Type consistency:** `scoreColor/scoreBand/scoreLabel/formatScore` names stable from T1 and reused T4/T5/T8; `RatingControl` `huntId` prop added in T9 and supplied in T11; `DrawerHero` prop names match T4 test + T11 call. ✔
- **Risks:** existing table-oriented tests in `CriterionBreakdown.test.tsx`/`AllInCost.test.tsx` may assert removed markup — each task's step 4 calls this out to fix. `FeeChecklist` has no existing co-located test; T7 adds one.
