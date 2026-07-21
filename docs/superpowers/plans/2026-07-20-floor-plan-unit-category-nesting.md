# Floor-plan unit/category nesting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In the HTML cleaner, keep each apartments.com-style floor-plan's category (name + beds/baths) attached to its units by nesting the unit rows under the plan header in the appended `[FLOOR PLANS]` section.

**Architecture:** Extend the existing `_floor_plan_lines()` structural guard in `cleaner.py`. After locating a plan's header region (as today), climb to the smallest ancestor card that also contains distinct unit rows, then emit the header line with each unit row indented beneath it. Two guardrails prevent mis-association: stop at the first ancestor that adds unit rows, and abort nesting (header-only) if an ancestor spans more than one plan name. Nothing else in the pipeline changes.

**Tech Stack:** Python 3.12, `lxml.html`, `trafilatura`, `readability-lxml`, `pytest`. Package: `manzil-worker` (uv workspace).

## Global Constraints

- No provider SDK imports; `cleaner.py` is pure text processing, no LLM calls. (AGENTS.md)
- The mechanism stays **general/structural** — no apartments.com-specific class names. Trigger is the existing `_PLAN_NAME_HINT` on `class`/`id` plus structural facts. (spec Non-goals)
- Do NOT parse the header into `name | beds | sqft | rent` columns — the association (grouping) is the value; header stays as concatenated text. (spec Non-goals)
- Over-capture (wrong beds/baths on a unit) is worse than under-capture (falls back to today's header-only). When ambiguous, degrade to header-only. (spec Guardrails)
- Run worker tests with: `uv run --package manzil-worker pytest worker/tests/test_cleaner.py -v`
- The fixture corpus (`worker/tests/fixtures/corpus/`) is gitignored and local-only; CI does not have it. Any test that reads it MUST `pytest.skip` when absent. (AGENTS.md Testing)
- Commit only when the user asks (user global rule). Steps below include `git add`/`commit` as the intended unit boundaries, but the executor must confirm with the user before actually committing.

## File Structure

- **Modify** `worker/src/manzil_worker/fetching/cleaner.py`
  - Add module constant `_UNIT_ROW_ID`.
  - Add helper `_unit_rows(card, header) -> list[str]`.
  - Rewrite `_floor_plan_lines(html) -> list[tuple[str, str]]` to return `(name, block)` where `block` is header + indented units.
  - Update the caller inside `clean_html` (rename local `summary` → `block`).
  - Update the docstring (lines ~13–18) to describe unit nesting.
- **Modify** `worker/tests/test_cleaner.py`
  - Extend the two existing `FLOOR_PLAN_CARD_HTML` tests to assert nesting.
  - Add: multi-card-container guardrail test, real-fixture nesting test, corpus regression sweep.
- **Regenerate (local only, not committed to CI)** `worker/tests/fixtures/corpus/apartments.com--*/cleaned.txt`.

---

### Task 1: `_unit_rows` helper + `_UNIT_ROW_ID`

**Files:**
- Modify: `worker/src/manzil_worker/fetching/cleaner.py`
- Test: `worker/tests/test_cleaner.py`

**Interfaces:**
- Consumes: existing module helpers `_normalize`, `_text_without_actions`, and constants `_PRICE_TOKEN`, `_RENT_STATUS`.
- Produces: `_UNIT_ROW_ID: re.Pattern`; `_unit_rows(card: lxml.html.HtmlElement, header: lxml.html.HtmlElement) -> list[str]` — compact text of unit rows inside `card` but outside `header`, deduped, order-preserving.

- [ ] **Step 1: Write the failing test**

Add to `worker/tests/test_cleaner.py` (import `lxml.html` at top if not present):

```python
import lxml.html
from manzil_worker.fetching.cleaner import _unit_rows


def test_unit_rows_extracts_identifier_rows_and_skips_headers() -> None:
    html = """
    <div id="card">
      <div class="modelName-wrap"><span class="modelName">The Elm</span>
        <span>1 Bed 1 Bath 700 Sq Ft $1,400</span></div>
      <div class="grid">
        <div class="unitGridHeaderRow">Unit Base Price Sq Ft Availability</div>
        <ul>
          <li>Unit 12-104 price $1,400 square feet 700 availibility Now</li>
          <li>Unit 12-106 price $1,450 square feet 700 availibility Sep 2</li>
        </ul>
        <div>2 Available units</div>
      </div>
    </div>
    """
    tree = lxml.html.fromstring(html)
    card = tree.xpath("//*[@id='card']")[0]
    header = tree.xpath("//*[contains(@class,'modelName-wrap')]")[0]

    rows = _unit_rows(card, header)

    assert rows == [
        "Unit 12-104 price $1,400 square feet 700 availibility Now",
        "Unit 12-106 price $1,450 square feet 700 availibility Sep 2",
    ]
    # The grid header row ("Unit Base Price…") has no unit identifier -> excluded.
    # "2 Available units" has no price and no identifier -> excluded.
    assert not any("Base Price" in r for r in rows)
    assert not any("Available units" in r for r in rows)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package manzil-worker pytest worker/tests/test_cleaner.py::test_unit_rows_extracts_identifier_rows_and_skips_headers -v`
Expected: FAIL with `ImportError: cannot import name '_unit_rows'`.

- [ ] **Step 3: Write minimal implementation**

In `cleaner.py`, after the `_RENT_STATUS` constant (around line 63) add:

```python
_UNIT_ROW_ID = re.compile(
    r"\b(?:unit|apt|apartment|suite)\b[\s#:.-]*[\w-]*\d|#\s?\d", re.IGNORECASE
)
```

After `_text_without_actions` (around line 145) add:

```python
def _unit_rows(
    card: lxml.html.HtmlElement, header: lxml.html.HtmlElement
) -> list[str]:
    """Compact text of unit rows inside ``card`` but outside its ``header``.

    A unit row carries a price (or rent-status) *and* a unit identifier such as
    ``Unit 03-205``. Requiring the identifier is what keeps grid header rows
    ("Unit Base Price Sq Ft") and availability blurbs ("1 Available unit") out.
    Structured ``<li>``/``<tr>`` rows are preferred; otherwise the smallest
    identifier-bearing elements (those with no matching descendant) are used.
    """
    header_nodes = set(header.iter())
    rows: list[str] = []
    seen: set[str] = set()

    def _is_unit(text: str) -> bool:
        return bool(
            text
            and _UNIT_ROW_ID.search(text)
            and (_PRICE_TOKEN.search(text) or _RENT_STATUS.search(text))
        )

    for element in card.xpath(".//li | .//tr"):
        if element in header_nodes:
            continue
        row = _normalize(_text_without_actions(element))
        if _is_unit(row) and row not in seen:
            seen.add(row)
            rows.append(row)
    if rows:
        return rows

    for element in card.iter():
        if element in header_nodes or element is header:
            continue
        row = _normalize(_text_without_actions(element))
        if not _is_unit(row) or row in seen:
            continue
        # Skip containers: keep only the minimal element with no matching child.
        if any(
            _is_unit(_normalize(_text_without_actions(child))) for child in element
        ):
            continue
        seen.add(row)
        rows.append(row)
    return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package manzil-worker pytest worker/tests/test_cleaner.py::test_unit_rows_extracts_identifier_rows_and_skips_headers -v`
Expected: PASS.

- [ ] **Step 5: Commit** (confirm with user first)

```bash
git add worker/src/manzil_worker/fetching/cleaner.py worker/tests/test_cleaner.py
git commit -m "feat(cleaner): add _unit_rows helper for floor-plan unit extraction"
```

---

### Task 2: Nest units in `_floor_plan_lines` with over-capture guardrails

**Files:**
- Modify: `worker/src/manzil_worker/fetching/cleaner.py:147-216`
- Test: `worker/tests/test_cleaner.py`

**Interfaces:**
- Consumes: `_unit_rows` (Task 1); existing `_PLAN_NAME_HINT`, `_PRICE_TOKEN`, `_RENT_STATUS`, `_FLOOR_PLAN_FACT`, `_normalize`, `_text_without_actions`.
- Produces: `_floor_plan_lines(html: str) -> list[tuple[str, str]]` returning `(name, block)` where `block` is the header summary optionally followed by `\n` + two-space-indented unit lines. The `clean_html` caller appends `block`s whose `name` is absent from the extracted text under `FLOOR_PLAN_MARKER`.

- [ ] **Step 1: Write the failing tests**

Extend the existing `test_floor_plan_cards_survive_when_unit_prices_mask_primary_loss` in `worker/tests/test_cleaner.py` — add these assertions at the end of the test body (keep all existing assertions):

```python
    # Units now nest (two-space indent) under their plan header.
    assert "  Unit 03-205 price $1,320 square feet 625" in cleaned.text
    assert "  Unit 04-102 price $1,480 square feet 775" in cleaned.text
    # The Dogwood has no distinct unit -> header-only, no nested unit line.
    dogwood_tail = cleaned.text.split("The Dogwood", 1)[1]
    assert not dogwood_tail.lstrip().startswith("Unit")
```

Add a new guardrail test:

```python
FLOOR_PLAN_GROUP_HTML = """
<html><body><main>
  <h1>Grouped Apartments</h1>
  <p>{filler}</p>
  <div class="fp-group">
    <div class="model-row">
      <span class="modelName">Plan Alpha</span>
      <span>1 Bed 1 Bath 800 Sq Ft $1,500</span>
    </div>
    <div class="model-row">
      <span class="modelName">Plan Beta</span>
      <span>2 Beds 2 Baths 1,100 Sq Ft $1,900</span>
    </div>
    <ul>
      <li>Unit A1 price $1,500 square feet 800 availibility Now</li>
      <li>Unit B1 price $1,900 square feet 1,100 availibility Now</li>
    </ul>
  </div>
</main></body></html>
""".format(filler="Apartments in Detroit, Michigan. " * 40)


def test_multi_card_container_falls_back_to_header_only(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Force the floor-plan guard to run by making primary extraction lossy but
    # price-retaining.
    monkeypatch.setattr(
        cleaner_module,
        "_extract_primary",
        lambda html: "Grouped apartments in Detroit. $1,500. $1,900.",
    )

    cleaned = clean_html(FLOOR_PLAN_GROUP_HTML)

    assert FLOOR_PLAN_MARKER in cleaned.text
    assert "Plan Alpha 1 Bed 1 Bath 800 Sq Ft $1,500" in cleaned.text
    assert "Plan Beta 2 Beds 2 Baths 1,100 Sq Ft $1,900" in cleaned.text
    # A shared container spans two plan names, so units must NOT be nested
    # (nesting would mis-attribute Unit B1 to Plan Alpha).
    assert "  Unit A1" not in cleaned.text
    assert "  Unit B1" not in cleaned.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --package manzil-worker pytest worker/tests/test_cleaner.py::test_floor_plan_cards_survive_when_unit_prices_mask_primary_loss worker/tests/test_cleaner.py::test_multi_card_container_falls_back_to_header_only -v`
Expected: FAIL — the survive test fails on the new `  Unit 03-205` assertion (units not yet nested); the guardrail test fails because `_floor_plan_lines` still returns `(name, summary)` header-only tuples and the group produces no nesting logic yet (it may pass trivially — that's fine; the survive test is the failing driver).

- [ ] **Step 3: Rewrite `_floor_plan_lines`**

Replace the body of `_floor_plan_lines` (currently `cleaner.py:147-184`) with:

```python
def _floor_plan_lines(html: str) -> list[tuple[str, str]]:
    """Return ``(name, block)`` for compact, semantic Floor Plan cards.

    ``block`` is the header summary (name, rent range, beds/baths, sqft); when
    the card carries a distinct unit grid, each available unit is indented
    beneath it, so the extractor-dropped category stays attached to its units.

    The signal is structural, not domain-specific: a class/id such as
    ``floorplan-name``, ``modelName`` or ``fp-name`` inside a card that also
    carries a price and a Floor Plan fact. Unit nesting is bounded by two
    guardrails against mis-association (see inline comments).
    """
    try:
        tree = lxml.html.fromstring(html)
    except Exception:
        return []

    lines: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for element in tree.xpath("//*[@class or @id]"):
        hint = " ".join((element.get("class", ""), element.get("id", "")))
        if not _PLAN_NAME_HINT.search(hint):
            continue
        name = _normalize(_text_without_actions(element))
        if not name or "\n" in name or len(name) > 160:
            continue

        # 1. Header region: the smallest ancestor whose text has a price/rent
        #    status and a Floor Plan fact.
        header = None
        header_summary = ""
        context = element
        for _ in range(7):
            summary = _text_without_actions(context)
            has_rent = _PRICE_TOKEN.search(summary) or _RENT_STATUS.search(summary)
            if has_rent and _FLOOR_PLAN_FACT.search(summary):
                header = context
                header_summary = _normalize(summary)
                break
            parent = context.getparent()
            if parent is None:
                break
            context = parent
        if header is None:
            continue

        key = (name, header_summary)
        if key in seen:
            continue
        seen.add(key)

        # 2. Climb to the smallest ancestor that adds unit rows. Guardrails:
        #    (a) stop as soon as unit rows appear — never keep climbing;
        #    (b) abort nesting (header-only) if an ancestor spans more than one
        #        plan name, i.e. a multi-card container, where units cannot be
        #        safely attributed to a single plan.
        unit_rows: list[str] = []
        card = header.getparent()
        for _ in range(5):
            if card is None:
                break
            name_hits = sum(
                1
                for node in card.iter()
                if _PLAN_NAME_HINT.search(
                    " ".join((node.get("class", ""), node.get("id", "")))
                )
            )
            if name_hits > 1:
                break
            rows = _unit_rows(card, header)
            if rows:
                unit_rows = rows
                break
            card = card.getparent()

        if unit_rows:
            block = header_summary + "\n" + "\n".join(f"  {row}" for row in unit_rows)
        else:
            block = header_summary
        lines.append((name, block))
    return lines
```

- [ ] **Step 4: Update the caller in `clean_html`**

In `clean_html` (currently `cleaner.py:212-216`), rename the loop variable for clarity — replace:

```python
    floor_plan_lines = _floor_plan_lines(html)
    missing_plans = [summary for name, summary in floor_plan_lines if name not in text]
```

with:

```python
    floor_plan_lines = _floor_plan_lines(html)
    missing_plans = [block for name, block in floor_plan_lines if name not in text]
```

(The rest — `section = f"{FLOOR_PLAN_MARKER}\n" + "\n".join(missing_plans)` — is unchanged.)

- [ ] **Step 5: Run the full cleaner test file**

Run: `uv run --package manzil-worker pytest worker/tests/test_cleaner.py -v`
Expected: PASS — all existing tests plus the new nesting and guardrail assertions.

- [ ] **Step 6: Commit** (confirm with user first)

```bash
git add worker/src/manzil_worker/fetching/cleaner.py worker/tests/test_cleaner.py
git commit -m "feat(cleaner): nest floor-plan units under their category header"
```

---

### Task 3: Real-fixture association test + corpus regression sweep

**Files:**
- Test: `worker/tests/test_cleaner.py`

**Interfaces:**
- Consumes: `clean_html`, `FLOOR_PLAN_MARKER`; local corpus fixtures under `worker/tests/fixtures/corpus/` (gitignored — tests skip when absent).
- Produces: no source symbols; verification only.

- [ ] **Step 1: Write the tests**

Add to `worker/tests/test_cleaner.py` (add `from pathlib import Path` and `import pytest` at top if not present):

```python
_FIXTURES = Path(__file__).parent / "fixtures"


def _floor_plan_blocks(section: str) -> dict[str, list[str]]:
    """Parse a [FLOOR PLANS] section into {header_line: [unit_line, ...]}."""
    blocks: dict[str, list[str]] = {}
    current: str | None = None
    for line in section.splitlines():
        if not line.strip():
            continue
        if line.startswith("  ") and current is not None:
            blocks[current].append(line.strip())
        elif not line.startswith("  "):
            current = line
            blocks[current] = []
    return blocks


def test_apartments_com_units_nest_under_their_category() -> None:
    raw_path = _FIXTURES / "corpus/apartments.com--village-of-detroit/raw.html"
    if not raw_path.exists():
        pytest.skip("local corpus fixture not present (gitignored)")
    cleaned = clean_html(raw_path.read_text(encoding="utf-8", errors="ignore"))
    assert FLOOR_PLAN_MARKER in cleaned.text

    section = cleaned.text.split(FLOOR_PLAN_MARKER, 1)[1]
    blocks = _floor_plan_blocks(section)

    studio_hdr = next(h for h in blocks if "Studio 1 Bath" in h)
    assert any("Unit 03-205" in u for u in blocks[studio_hdr])

    two_bed_hdr = next(h for h in blocks if "2 Beds 2 Baths" in h)
    assert any("Unit 09-205" in u for u in blocks[two_bed_hdr])


def test_clean_html_survives_entire_corpus() -> None:
    raws = sorted((_FIXTURES / "corpus").glob("*/raw.html"))
    if not raws:
        pytest.skip("local corpus not present (gitignored)")
    for raw in raws:
        cleaned = clean_html(raw.read_text(encoding="utf-8", errors="ignore"))
        assert cleaned.text_hash, f"empty clean for {raw.parent.name}"
```

- [ ] **Step 2: Run the tests**

Run: `uv run --package manzil-worker pytest worker/tests/test_cleaner.py::test_apartments_com_units_nest_under_their_category worker/tests/test_cleaner.py::test_clean_html_survives_entire_corpus -v`
Expected: PASS locally (corpus present); these SKIP in CI where the corpus is absent.

- [ ] **Step 3: Commit** (confirm with user first)

```bash
git add worker/tests/test_cleaner.py
git commit -m "test(cleaner): assert unit-category nesting on real corpus + sweep"
```

---

### Task 4: Docstring update + regenerate local cleaned.txt fixtures

**Files:**
- Modify: `worker/src/manzil_worker/fetching/cleaner.py:13-18`
- Regenerate (local only): `worker/tests/fixtures/corpus/apartments.com--*/cleaned.txt`

**Interfaces:**
- Consumes: the completed cleaner from Tasks 1–2.
- Produces: updated module docstring; refreshed local `cleaned.txt` snapshots (not committed to CI — the corpus is gitignored).

- [ ] **Step 1: Update the module docstring**

Replace the "Floor-plan-card retention guard" paragraph (`cleaner.py:13-18`) with:

```python
Floor-plan-card retention guard: some listing pages put the Floor Plan summary
(name, rent range, beds/baths, sqft) in a span-only card and the available
Units in a separate sibling list. Generic extractors can keep enough Unit
prices to pass the price-retention guard while silently dropping every summary
card — severing each Unit from its category (beds/baths, plan name). Name- and
fact-bearing cards are therefore rendered compactly and appended when their
names are missing from the primary/fallback text; when a card carries a
distinct unit grid, its units are nested (indented) beneath the header so the
category stays attached to them. Two guardrails keep this from mis-associating
units across a multi-card container (see _floor_plan_lines).
```

- [ ] **Step 2: Verify the docstring change did not break import**

Run: `uv run --package manzil-worker python -c "import manzil_worker.fetching.cleaner"`
Expected: no output, exit 0.

- [ ] **Step 3: Regenerate local corpus cleaned.txt and eyeball the diff**

Identify the corpus-cleaning entry point (recent CLI: `clean-corpus` / `corpus-extract`):

Run: `uv run --package manzil-worker manzil --help`  (find the corpus clean command)
Then regenerate the apartments.com fixtures, e.g.:
Run: `uv run --package manzil-worker manzil clean-corpus --site apartments.com` (use the actual command/flags surfaced above)
Then inspect: `git status --porcelain worker/tests/fixtures/corpus/` — expect only apartments.com `cleaned.txt` changes; open `apartments.com--village-of-detroit/cleaned.txt` and confirm the `[FLOOR PLANS]` section now shows units indented under each header with correct beds/baths.

Note: these files are gitignored (local eval kit), so there is nothing to commit for this step — it is a local sanity check.

- [ ] **Step 4: Full worker test run (no regressions elsewhere)**

Run: `uv run --package manzil-worker pytest worker/tests/test_cleaner.py worker/tests/test_structured.py -v`
Expected: PASS.

- [ ] **Step 5: Commit the docstring** (confirm with user first)

```bash
git add worker/src/manzil_worker/fetching/cleaner.py
git commit -m "docs(cleaner): document floor-plan unit nesting in module docstring"
```

---

## Self-Review

**Spec coverage:**
- Root-cause fix (nest units under header) → Task 2. ✓
- General/structural mechanism, no site-specific classes → `_PLAN_NAME_HINT` + `_UNIT_ROW_ID` (Task 1/2). ✓
- Unit-row definition (li/tr preferred, identifier + price required, minimal element) → Task 1. ✓
- Guardrails (stop at first unit-bearing ancestor; abort on >1 plan name; per-block dedup) → Task 2 (`name_hits`, break) + Task 1 (`seen`). ✓
- Append gate unchanged (name-not-in-text); block dedup by `(name, header_summary)` → Task 2 (`seen`). ✓
- Backward compat: single-unit + no-hint sites unchanged → covered by existing tests staying green (Task 2 Step 5) + corpus sweep (Task 3). ✓
- Tests: updated FLOOR_PLAN tests, guardrail, real-fixture, sweep → Tasks 2–3. ✓
- Docstring update + regenerate cleaned.txt → Task 4. ✓
- Duplication-cost note (units appear in flat list + nested block) → accepted per spec; no code needed.

**Placeholder scan:** No TBD/TODO; every code step shows complete code. The only non-verbatim command is Task 4 Step 3 (regenerate CLI), because the exact flag must be read from `manzil --help` — flagged explicitly rather than guessed.

**Type consistency:** `_floor_plan_lines` returns `list[tuple[str, str]]` in both the interface block and Task 2 code; caller unpacks `(name, block)`. `_unit_rows(card, header) -> list[str]` consistent across Task 1 definition and Task 2 call site. `_UNIT_ROW_ID` defined once (Task 1), used in `_unit_rows` only. ✓
