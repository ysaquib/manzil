"""Phase 0 entry point: `manzil ingest <url>` plus corpus/census tooling
(DESIGN §6, §10.2, §19).

The CLI and the Phase 1+ queue worker are two entry points calling the same
`run_job` — the CLI is not throwaway work. Pipeline wiring lands in P0-10.
"""

import asyncio
import os
from logging import INFO, basicConfig, getLogger
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.logging import RichHandler
from rich.markdown import Markdown

load_dotenv()  # .env keys are read lazily inside commands, so loading here is early enough
console = Console()
app = typer.Typer(no_args_is_help=True)

logging_config = basicConfig(
    level=INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(console=console, rich_tracebacks=True)],
)
logger = getLogger()

DEFAULT_CENSUS_URLS = Path("infra/census_urls.txt")
DEFAULT_CENSUS_OUT = Path("docs/hostile-domain-census.csv")


def _fetchers(tier2: bool, tier3: bool = True) -> dict[int, object]:
    from manzil_worker.fetching.tier3 import Tier3Fetcher, tier3_configured
    from manzil_worker.fetching.tiers import Tier1Fetcher, Tier2Fetcher

    fetchers: dict[int, object] = {1: Tier1Fetcher()}
    if tier2:
        fetchers[2] = Tier2Fetcher()
    if tier3 and tier3_configured():  # no provider key = tier 3 stays off the ladder
        fetchers[3] = Tier3Fetcher()
    return fetchers


@app.callback()
def main() -> None:
    """Manzil worker CLI."""


@app.command()
def ingest(
    url: str,
    tier2: bool = typer.Option(True, "--tier2/--no-tier2", help="Allow browser escalation"),
    tier3: bool = typer.Option(
        True, "--tier3/--no-tier3", help="Allow unblocker escalation (needs a provider key)"
    ),
) -> None:
    """Run the ingest pipeline (validate-url → fetch → validate → extract →
    verify → score) for a listing URL and print the score breakdown.

    Spends tokens unless MANZIL_LLM_MODE=replay. Run state persists to
    .manzil/runs/<job_id>.json after every stage.
    """
    import uuid

    from manzil_shared.models import JobState, JobType

    from manzil_worker.fetching.registry import InMemoryRegistry, PostgresRegistry
    from manzil_worker.persistence import FilePersistence
    from manzil_worker.phase0_rubric import PHASE0_RUBRIC_VERSION, phase0_rubric
    from manzil_worker.runner import run_job
    from manzil_worker.stages.base import StageCtx
    from manzil_worker.state import RunState

    async def run() -> None:
        dsn = os.environ.get("DATABASE_URL")
        registry = PostgresRegistry(dsn) if dsn else InMemoryRegistry()
        mode = os.environ.get("MANZIL_MODE", "workflow")
        if mode != "workflow":
            typer.echo(f"mode {mode!r}: agents mode has no pipeline yet (L1+)", err=True)
            raise typer.Exit(code=2)
        persistence = FilePersistence()
        state = RunState(job_id=uuid.uuid4(), job_type=JobType.INGEST, url=url)
        ctx = StageCtx(
            fetchers=_fetchers(tier2, tier3),  # type: ignore[arg-type]
            registry=registry,  # type: ignore[arg-type]
            rubric=phase0_rubric(),
            rubric_version=PHASE0_RUBRIC_VERSION,
            persistence=persistence,
        )
        state = await run_job(state, ctx)

        typer.echo(f"job {state.job_id}: {state.status.value}")
        typer.echo(f"run file: {persistence.path_for(state.job_id)}")
        if state.status is JobState.FAILED:
            typer.echo(f"error: {state.error}", err=True)
            raise typer.Exit(code=1)
        if state.status is JobState.WAITING_USER and state.checkpoint is not None:
            typer.echo(f"checkpoint [{state.checkpoint.kind.value}]: {state.checkpoint.question}")
            typer.echo("(answering checkpoints arrives with the jobs UI — Phase 1)")
            raise typer.Exit(code=3)

        source = state.sources[0]
        typer.echo(f"source: tier {source.tier_used}, {len(source.cleaned_text)} chars cleaned")
        if state.verify_flags:
            typer.echo(f"verify flags ({len(state.verify_flags)}):")
            for flag in state.verify_flags:
                typer.echo(f"  [{flag.check}] {flag.criterion_key}: {flag.note}")
        for i, plan_score in enumerate(state.scores):
            b = plan_score.breakdown
            marker = " <- display score" if i == state.display_score_index else ""
            typer.echo(f"\nplan: {plan_score.plan_name or '(property-level)'}{marker}")
            if b["gates"]:
                for gate in b["gates"]:
                    typer.echo(f"  GATE {gate['kind']} on {gate['key']} -> {gate['set_score']}")
            for c in b["criteria"]:
                value = "unknown" if c.get("unknown") else repr(c["value"])
                typer.echo(f"  {c['key']}: {value} -> {c['delta']:+g}")
            typer.echo(f"  total: {b['total']}")
        typer.echo(f"\ncost: ${state.cost_usd:.4f}")

    asyncio.run(run())


@app.command("split-property")
def split_property_cmd(
    property_id: str = typer.Argument(..., help="Merged Property UUID to split"),
    source_url: str = typer.Option(
        ..., "--source-url", help="URL of the Source to peel onto a new Property"
    ),
    listing: list[str] = typer.Option(
        [],
        "--listing",
        help="Listing UUID to move (repeatable). Omit to derive from ingest jobs' URL.",
    ),
) -> None:
    """Unmerge a Property (P3-4, DESIGN §10.3, §17 R5): peel the Source at
    --source-url off PROPERTY_ID onto a fresh Property, re-point its extractions/
    floor plans/Listings, and enqueue a rescore per affected Hunt.

    Admin-only, service-role: connects via DATABASE_URL below the RLS boundary,
    like the worker. The reversal of a wrong DEDUPE merge — a false split is
    re-mergeable, so this is the safe direction to correct in.
    """
    import uuid

    import asyncpg
    import structlog

    from manzil_worker.ops.split_property import SplitError, split_property

    log = structlog.get_logger()

    async def run() -> None:
        dsn = os.environ.get("DATABASE_URL")
        if not dsn:
            typer.echo(
                "DATABASE_URL is not set — split-property needs the service-role DB URL",
                err=True,
            )
            raise typer.Exit(code=2)
        pid = uuid.UUID(property_id)
        listing_ids = [uuid.UUID(item) for item in listing] or None

        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
        try:
            async with pool.acquire() as conn:
                try:
                    result = await split_property(
                        conn, property_id=pid, source_url=source_url, listing_ids=listing_ids
                    )
                except SplitError as error:
                    typer.echo(f"error: {error}", err=True)
                    raise typer.Exit(code=1) from None
        finally:
            await pool.close()

        log.info(
            "split_property_done",
            property_id=str(pid),
            new_property_id=str(result.new_property_id),
            source_url=source_url,
        )
        typer.echo(f"split property {pid} -> new property {result.new_property_id}")
        typer.echo(f"  moved source: {result.moved_source_id}")
        typer.echo(
            f"  re-pointed {result.moved_extraction_count} extraction(s), "
            f"{result.moved_floor_plan_count} floor plan(s)"
        )
        if result.moved_listing_ids:
            typer.echo(f"  moved {len(result.moved_listing_ids)} listing(s):")
            for lid in result.moved_listing_ids:
                typer.echo(f"    {lid}")
        else:
            typer.echo(
                "  WARNING: no listings moved — no ingest job carried this URL. "
                "The global-fact split is still valid; move listings explicitly "
                "with --listing if a Listing should follow this Source."
            )
        typer.echo(f"  rescored {len(result.rescored_hunt_ids)} hunt(s):")
        for hid in result.rescored_hunt_ids:
            typer.echo(f"    {hid}")

    asyncio.run(run())


@app.command("llm-smoke")
def llm_smoke_cmd() -> None:
    """One structured call through the LLM seam (P0-7 gate: trace visible in Langfuse).

    Honors MANZIL_LLM_MODE — run with `record` to refresh the committed replay
    fixture, `replay` to prove the fixture serves without spending tokens.
    """
    from manzil_worker.llm.client import cost_tally, llm_mode
    from manzil_worker.llm.smoke import run_smoke

    async def run() -> None:
        with cost_tally() as tally:
            result = await run_smoke()
        typer.echo(f"mode: {llm_mode()}")
        typer.echo(f"echo: {result.echo}")
        typer.echo(f"model_family: {result.model_family}")
        typer.echo(
            f"tokens: {tally.input_tokens} in / {tally.output_tokens} out"
            f" (cache read {tally.cache_read_tokens}, write {tally.cache_write_tokens})"
        )
        typer.echo(f"cost: ${tally.cost_usd:.6f}")

    asyncio.run(run())


@app.command("clean-corpus")
def clean_corpus_cmd(
    slugs: list[str] = typer.Option([], "--slug", help="Corpus slugs to clean")
) -> None:
    """
    Regenerate cleaned.txt for every corpus page (run after cleaner changes).
    If slugs are provided, only clean the specified pages.
    """
    from manzil_worker.fetching.corpus import regenerate_cleaned
    report = regenerate_cleaned(slugs)
    if not report:
        typer.echo("corpus is empty — save pages with `manzil save-page`", err=True)
        raise typer.Exit(code=1)
    for slug, raw_bytes, cleaned_chars in report:
        typer.echo(f"{slug}: {raw_bytes} B raw -> {cleaned_chars} chars cleaned")
    typer.echo(f"regenerated {len(report)} pages")


@app.command("save-page")
def save_page_cmd(
    url: str,
    slug: str = typer.Argument(
        ..., help="Corpus slug WITHOUT the domain — the {domain}-- prefix is added automatically"
    ),
    official: bool = typer.Option(False, "--official", help="Mark source as official site"),
    notes: str = typer.Option("", "--notes"),
    tier2: bool = typer.Option(True, "--tier2/--no-tier2", help="Allow browser escalation"),
    tier3: bool = typer.Option(
        True, "--tier3/--no-tier3", help="Allow unblocker escalation (needs a provider key)"
    ),
) -> None:
    """Fetch a listing page through the tier ladder and save it as a corpus fixture."""
    from manzil_worker.fetching.corpus import save_page
    from manzil_worker.fetching.ladder import fetch_with_ladder
    from manzil_worker.fetching.registry import InMemoryRegistry, PostgresRegistry

    async def run() -> None:
        dsn = os.environ.get("DATABASE_URL")
        registry = PostgresRegistry(dsn) if dsn else InMemoryRegistry()
        ladder = await fetch_with_ladder(url, registry, _fetchers(tier2, tier3))  # type: ignore[arg-type]
        typer.echo(f"outcome: {ladder.outcome.value} (tier {ladder.result.tier})")
        if not ladder.result.body:
            typer.echo("no body fetched — nothing saved", err=True)
            raise typer.Exit(code=1)
        page_dir = save_page(ladder.result, slug, is_official=official, notes=notes)
        typer.echo(f"saved {page_dir}")

    asyncio.run(run())


@app.command("bench-skeleton")
def bench_skeleton(
    slug: str,
    force: bool = typer.Option(False, "--force", help="Overwrite an existing label file"),
) -> None:
    """Scaffold a bench label file from a saved corpus page (P0-11).

    Emits labels/{slug}.json with every extractable key set to null — fill in
    the true values by hand, move keys the page doesn't state to `unknown`,
    delete keys you don't want graded. The loader rejects unfilled skeletons.
    """
    from manzil_worker.evals.labels import LabelError, write_skeleton
    from manzil_worker.fetching.corpus import CORPUS_DIR

    try:
        path = write_skeleton(slug, corpus_dir=CORPUS_DIR, force=force)
    except LabelError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None
    typer.echo(f"skeleton written to {path}")
    typer.echo("manifest.md row added; fill in criteria values and its trait columns by hand")


@app.command("bench-run")
def bench_run(
    out_dir: Path = typer.Option(Path("worker/evals/reports"), "--out-dir"),
    name: str = typer.Option("", "--name", help="Report file stem (default: timestamp+model)"),
    slugs: list[str] = typer.Option([], "--label", help="Label slugs to bench"),
) -> None:
    """Run the eval harness over the bench labels (P0-12); write a JSON report.

    Spends tokens unless MANZIL_LLM_MODE=replay. Model sweeps (P0-13): set
    MANZIL_MODEL_EXTRACT / MANZIL_MODEL_VERIFY and give each run a --name,
    then `manzil bench-compare` the reports.
    """
    from datetime import UTC, datetime

    from manzil_worker.evals.harness import gate_keys_from, report_text, run_bench
    from manzil_worker.evals.labels import LABELS_DIR, LabelError, load_labels
    from manzil_worker.fetching.corpus import CORPUS_DIR
    from manzil_worker.llm.config import model_for_stage
    from manzil_worker.phase0_rubric import phase0_rubric
    from manzil_worker.stages.base import StageCtx
    try:
        labels = load_labels(slugs, LABELS_DIR)
    except LabelError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None
    if not labels:
        typer.echo(
            f"no labels in {LABELS_DIR} — `manzil bench-skeleton <slug>` then label by hand",
            err=True,
        )
        raise typer.Exit(code=1)

    rubric = phase0_rubric()
    ctx = StageCtx(rubric=rubric)
    report = asyncio.run(
        run_bench(labels, corpus_dir=CORPUS_DIR, ctx=ctx, gate_keys=gate_keys_from(rubric))
    )

    model_name = model_for_stage("extract").replace("/", "_")
    stem = name or (datetime.now(UTC).strftime("%Y%m%d-%H%M%S") + "--" + model_name)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{stem}.json"
    out.write_text(report.model_dump_json(indent=2) + "\n")
    console.print(Markdown(report_text(report)))
    typer.echo(f"\nreport written to {out}")
    if all(listing.error is not None for listing in report.listings):
        raise typer.Exit(code=1)


@app.command("bench-compare")
def bench_compare(
    reports: list[Path] = typer.Argument(..., help="Two or more bench-run report JSONs"),
) -> None:
    """Side-by-side comparison of bench reports (P0-13 model decision input)."""
    from manzil_worker.evals.compare import compare_table, load_report

    if len(reports) < 2:
        typer.echo("need at least two reports to compare", err=True)
        raise typer.Exit(code=1)
    typer.echo(compare_table({path.stem: load_report(path) for path in reports}))


@app.command()
def census(
    urls_file: Path = typer.Argument(DEFAULT_CENSUS_URLS),
    out: Path = typer.Option(DEFAULT_CENSUS_OUT, "--out"),
    tier2: bool = typer.Option(True, "--tier2/--no-tier2", help="Allow browser escalation"),
    tier3: bool = typer.Option(
        True, "--tier3/--no-tier3", help="Allow unblocker escalation (needs a provider key)"
    ),
) -> None:
    """Probe candidate domains through the tier ladder; emit the census CSV (§19)."""
    from manzil_worker.fetching.census import read_url_file, run_census

    urls = read_url_file(urls_file)
    if not urls:
        typer.echo(f"no URLs in {urls_file}", err=True)
        raise typer.Exit(code=1)
    path = asyncio.run(run_census(urls, _fetchers(tier2, tier3), out))  # type: ignore[arg-type]
    typer.echo(f"census written to {path} ({len(urls)} URLs)")
