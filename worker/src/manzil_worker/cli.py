"""Phase 0 entry point: `manzil ingest <url>` plus corpus/census tooling
(DESIGN §6, §10.2, §19).

The CLI and the Phase 1+ queue worker are two entry points calling the same
`run_job` — the CLI is not throwaway work. Pipeline wiring lands in P0-10.
"""

import asyncio
import json
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
                    detail = ""
                    if gate.get("matched"):
                        detail = f" (matched {gate['matched']!r})"
                    elif gate.get("value") is None and "value" in gate:
                        detail = " (unknown)"
                    typer.echo(
                        f"  GATE {gate['kind']} on {gate['key']}{detail} -> {gate['set_score']}"
                    )
            if b["criteria"]:
                if b["gates"]:
                    typer.echo("  (informational deltas — total is gate-capped)")
                for c in b["criteria"]:
                    value = "unknown" if c.get("unknown") else repr(c["value"])
                    typer.echo(f"  {c['key']}: {value} -> {c['delta']:+g}")
            cap_note = " (gate cap)" if b["gates"] else ""
            typer.echo(f"  total: {b['total']}{cap_note}")
        typer.echo(f"\ncost: ${state.cost_usd:.4f}")

    asyncio.run(run())


@app.command("purge-images")
def purge_images_cmd(
    property_id: str = typer.Option(
        None, "--property", help="Scope the purge to one Property UUID (default: all)"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Report what would be removed without deleting anything"
    ),
) -> None:
    """Remove Storage objects for unreferenced, non-current images (P3-SC5).

    Deletes only images that are non-current AND carry no current Floor Plan
    association AND are cited by no Extraction. Inactive evidence is otherwise
    retained while its Property exists (DESIGN §9.3), so this is an explicit
    admin action rather than a scheduled sweep.

    Admin-only, service-role: connects via DATABASE_URL below the RLS boundary.
    Start with --dry-run.
    """
    import uuid

    import asyncpg
    import structlog

    from manzil_worker.enrich.images import SupabaseImageStore
    from manzil_worker.ops.purge_images import purge_unreferenced_images

    log = structlog.get_logger()

    async def run() -> None:
        dsn = os.environ.get("DATABASE_URL")
        if not dsn:
            typer.echo(
                "DATABASE_URL is not set — purge-images needs the service-role DB URL",
                err=True,
            )
            raise typer.Exit(code=2)
        store = SupabaseImageStore.from_env()
        if store is None:
            typer.echo(
                "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are not set — "
                "purge-images needs Storage credentials",
                err=True,
            )
            raise typer.Exit(code=2)
        pid = uuid.UUID(property_id) if property_id else None

        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
        try:
            async with pool.acquire() as conn, conn.transaction():
                result = await purge_unreferenced_images(
                    conn, store, property_id=pid, dry_run=dry_run
                )
        finally:
            await pool.close()

        log.info(
            "purge_images_done",
            property_id=str(pid) if pid else None,
            dry_run=dry_run,
            **result.__dict__,
        )
        prefix = "would remove" if dry_run else "removed"
        typer.echo(f"{result.considered} unreferenced image(s) considered")
        typer.echo(f"  {prefix} {result.deleted_objects} Storage object(s)")
        if not dry_run:
            typer.echo(f"  deleted {result.deleted_rows} row(s)")
        if result.retained_shared:
            typer.echo(f"  kept {result.retained_shared} object(s) still shared by other rows")

    asyncio.run(run())


@app.command("export-demo-capture")
def export_demo_capture_cmd(
    job_id: str = typer.Argument(..., help="A finished ingest Job to record"),
    out: Path = typer.Option(
        Path("frontend/src/features/demo/replay/capture.json"),
        "--out",
        help="Where to write the bundle",
    ),
) -> None:
    """Export a Replay Capture from a real ingest (DM-9, DESIGN §3).

    The demo never runs the pipeline: a Demo Account's submission is disclosed
    and then served by this recording, played back in the browser. Nothing is
    fetched, no Job is enqueued, and no row is written -- which is why the
    bundle has to come from a run that really happened.

    Any Job works, checkpoint or not: rendering a checkpoint prompt was cut from
    scope (DESIGN §20 v3.58) because it needed either publishing page excerpts
    into `capture.json` -- a world-readable build artifact, not something the
    demo session gates -- or a per-checkpoint-kind allow-list. A recorded
    checkpoint still replays, as an ordinary timeline beat.

    Service-role: connects via DATABASE_URL below the RLS boundary.
    """
    import uuid

    import asyncpg

    from manzil_worker.ops.export_demo_capture import CaptureError, export_demo_capture

    async def run() -> None:
        dsn = os.environ.get("DATABASE_URL")
        if not dsn:
            typer.echo("DATABASE_URL is not set", err=True)
            raise typer.Exit(code=2)
        conn = await asyncpg.connect(dsn)
        try:
            bundle = await export_demo_capture(conn, uuid.UUID(job_id))
        except CaptureError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
        finally:
            await conn.close()

        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n")

        events = bundle["events"]
        real = bundle["job"]["real_duration_ms"]
        console.print(
            f"[green]Wrote[/green] {out} — {len(events)} events, "
            f"{len({e['stage'] for e in events})} stages, "
            f"real duration {real / 1000:.0f}s"
            + (", includes a checkpoint" if bundle["has_checkpoint"] else "")
        )
        console.print(
            "[dim]Playback compresses this; see replayTiming.ts. Review the bundle "
            "for anything you would not publish before committing it.[/dim]"
        )

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


@app.command("backfill-locality")
def backfill_locality_cmd(
    property_id: list[str] = typer.Option(
        [],
        "--property-id",
        help="Limit to specific Property UUIDs (repeatable). Omit for all incomplete rows.",
    ),
) -> None:
    """Backfill `properties.city/state/county` for rows missing any locality field."""
    import uuid

    import asyncpg

    from manzil_worker.ops.backfill_locality import backfill_locality

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        typer.echo(
            "DATABASE_URL is not set — backfill-locality needs the service-role DB URL",
            err=True,
        )
        raise typer.Exit(code=1)

    ids = [uuid.UUID(value) for value in property_id] if property_id else None

    async def run() -> None:
        pool = await asyncpg.create_pool(dsn)
        try:
            async with pool.acquire() as conn:
                result = await backfill_locality(conn, property_ids=ids)
        finally:
            await pool.close()
        typer.echo(f"attempted={result.attempted} updated={result.updated} failed={result.failed}")

    asyncio.run(run())


@app.command("seed-dev-rubric")
def seed_dev_rubric_cmd(
    force: bool = typer.Option(
        False,
        "--force",
        help="Replace a locally modified development Rubric with the checked-in template",
    ),
) -> None:
    """Install the versioned P3-SC3 Rubric into its dedicated development Hunt."""
    import asyncpg

    from manzil_worker.dev_rubric import DevRubricDriftError, install_dev_rubric

    async def run() -> None:
        dsn = os.environ.get("DATABASE_URL")
        if not dsn:
            typer.echo("DATABASE_URL is not set — seed-dev-rubric needs the local DB URL", err=True)
            raise typer.Exit(code=2)
        conn = await asyncpg.connect(dsn)
        try:
            async with conn.transaction():
                try:
                    result = await install_dev_rubric(conn, force=force)
                except DevRubricDriftError as error:
                    typer.echo(f"error: {error}", err=True)
                    raise typer.Exit(code=1) from None
        finally:
            await conn.close()
        typer.echo(
            f"development Rubric v{result.template_version} {result.status}: "
            f"{result.criteria_count} criteria in Hunt {result.hunt_id}"
        )

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
    slugs: list[str] = typer.Option([], "--slug", help="Corpus slugs to clean"),
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


@app.command("vision-label-kit")
def vision_label_kit_cmd(
    property_id: list[str] = typer.Option(
        [],
        "--property-id",
        help=(
            "Property UUID to include (repeatable). Omit to select the 10 "
            "most recently imaged Properties."
        ),
    ),
    max_properties: int = typer.Option(10, "--max-properties"),
    max_images_per_property: int = typer.Option(30, "--max-images-per-property"),
    from_corpus: bool = typer.Option(
        False,
        "--from-corpus",
        help="Use saved local corpus pages when no Property images are stored yet.",
    ),
    out_dir: Path = typer.Option(
        Path("worker/tests/fixtures/vision_labels"),
        "--out-dir",
        help="Gitignored local output directory.",
    ),
    force: bool = typer.Option(False, "--force", help="Replace an existing local kit at --out-dir"),
) -> None:
    """Build the local P3-7 classifier labeling kit from current Property images.

    Reads the service-role database and private image bucket by default. With
    --from-corpus it discovers and downloads gallery images from saved local
    corpus pages instead. It writes only gitignored artifacts: contact-sheet,
    labels, manifest, and normalized copies. No LLM call or production mutation
    occurs.
    """
    import asyncpg

    from manzil_worker.enrich.images import SupabaseImageStore
    from manzil_worker.evals.vision_label_kit import (
        LabelKitError,
        collect_corpus_images,
        collect_current_images,
        write_label_kit,
    )

    async def run() -> None:
        try:
            if from_corpus:
                from manzil_worker.enrich.images import download_image

                corpus_set = await collect_corpus_images(
                    download_image,
                    max_properties=max_properties,
                    max_images_per_property=max_images_per_property,
                )

                async def local_image(path: str) -> bytes:
                    return corpus_set.contents[path]

                result = await write_label_kit(
                    corpus_set.images, local_image, out_dir=out_dir, force=force
                )
            else:
                dsn = os.environ.get("DATABASE_URL")
                store = SupabaseImageStore.from_env()
                if not dsn or store is None:
                    typer.echo(
                        "DATABASE_URL, SUPABASE_URL, and SUPABASE_SERVICE_ROLE_KEY are "
                        "required to build a vision label kit",
                        err=True,
                    )
                    raise typer.Exit(code=2)
                conn = await asyncpg.connect(dsn)
                try:
                    images = await collect_current_images(
                        conn,
                        property_ids=property_id,
                        max_properties=max_properties,
                        max_images_per_property=max_images_per_property,
                    )
                    result = await write_label_kit(images, store.get, out_dir=out_dir, force=force)
                finally:
                    await conn.close()
        except LabelKitError as error:
            typer.echo(str(error), err=True)
            raise typer.Exit(code=1) from None

        typer.echo(
            f"vision label kit: {result.image_count} images across "
            f"{result.property_count} Properties"
        )
        typer.echo(f"contact sheet: {result.contact_sheet}")
        typer.echo(f"labels: {result.labels_csv}")
        if result.image_count < 200:
            typer.echo(
                "warning: fewer than the 200-image classifier-bench target; "
                "add Properties or raise --max-images-per-property",
                err=True,
            )

    asyncio.run(run())


@app.command("vision-duplicate-suggestions")
def vision_duplicate_suggestions_cmd(
    out_dir: Path = typer.Option(
        Path("worker/tests/fixtures/vision_labels"),
        "--out-dir",
        help="Existing gitignored local labeling-kit directory.",
    ),
) -> None:
    """Generate dHash duplicate suggestions for human review without editing labels."""
    from manzil_worker.evals.vision_label_kit import LabelKitError, write_duplicate_suggestions

    try:
        result = write_duplicate_suggestions(out_dir)
    except LabelKitError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None
    typer.echo(
        f"duplicate suggestions: {result.cluster_count} groups / {result.image_count} images"
    )
    typer.echo(f"review sheet: {result.review_sheet}")
    typer.echo(f"suggestions: {result.suggestions_csv}")


@app.command("vision-classifier-bench")
def vision_classifier_bench_cmd(
    labels_dir: Path = typer.Option(
        Path("worker/tests/fixtures/vision_labels"),
        "--labels-dir",
        help="Completed local classifier label kit.",
    ),
    out: Path = typer.Option(
        Path("worker/evals/reports/vision-classifier-bench.json"),
        "--out",
        help="Gitignored local JSON report.",
    ),
    model: list[str] = typer.Option(
        [],
        "--model",
        help="Model to sweep (repeatable); defaults to the three approved candidates.",
    ),
) -> None:
    """Run the traced P3-7a2 classifier benchmark against human labels."""
    from manzil_worker.evals.vision_classifier import (
        DEFAULT_CLASSIFIER_BENCH_MODELS,
        ClassifierBenchError,
        report_json,
        run_classifier_bench,
    )

    try:
        results = asyncio.run(
            run_classifier_bench(
                labels_dir=labels_dir,
                models=tuple(model) if model else DEFAULT_CLASSIFIER_BENCH_MODELS,
            )
        )
    except ClassifierBenchError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report_json(results))
    for result in results:
        precision = (
            f"{result.selected_kitchen_precision:.1%}"
            if result.selected_kitchen_precision is not None
            else "n/a"
        )
        recall = (
            f"{result.kitchen_property_recall:.1%}"
            if result.kitchen_property_recall is not None
            else "n/a"
        )
        typer.echo(
            f"{result.model}: {'PASS' if result.passed else 'FAIL'} · "
            f"precision {precision} · recall {recall} · "
            f"${result.cost_per_property_usd:.4f}/Property · {result.latency_seconds:.1f}s"
        )
    typer.echo(f"report: {out}")


@app.command("vision-ml-bench")
def vision_ml_bench_cmd(
    benchmark_root: Path = typer.Option(
        Path("worker/tests/fixtures/vision_benchmark"),
        "--benchmark-root",
        help="Gitignored directory containing downloaded models and public datasets.",
    ),
    out: Path = typer.Option(
        Path("worker/evals/reports/vision-ml-benchmark.json"),
        "--out",
        help="Gitignored JSON report; a Markdown sibling is written beside it.",
    ),
    model: list[str] = typer.Option(
        [],
        "--model",
        help=(
            "Frozen model to run: siglip2, clip, clip-onnx, clip-onnx-int8, "
            "clip-onnx-uint8, or places365 (repeatable)."
        ),
    ),
    profile: str = typer.Option(
        "full",
        "--profile",
        help="`quick` verifies the harness; `full` uses the complete MIT test split.",
    ),
    device: str = typer.Option(
        "cpu",
        "--device",
        help="PyTorch device. Use cpu for the portable hosting baseline.",
    ),
    batch_size: int = typer.Option(16, "--batch-size", min=1),
) -> None:
    """Benchmark frozen local vision models without an LLM or network call."""
    from manzil_worker.evals.vision_ml_benchmark import (
        MODEL_NAMES,
        VisionMLBenchError,
        report_json,
        report_markdown,
        run_benchmark,
    )

    if profile not in {"quick", "full"}:
        typer.echo("--profile must be quick or full", err=True)
        raise typer.Exit(code=2)
    selected = tuple(model) if model else MODEL_NAMES
    try:
        report = run_benchmark(
            root=benchmark_root,
            models=selected,
            profile=profile,  # type: ignore[arg-type]
            device=device,
            batch_size=batch_size,
        )
    except VisionMLBenchError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report_json(report))
    markdown_out = out.with_suffix(".md")
    markdown_out.write_text(report_markdown(report))
    for result in report.results:
        kitchen_f1 = result.kitchen.f1 or 0.0
        diagram_f1 = result.diagram.metrics.f1 if result.diagram.metrics else None
        diagram = "n/a" if diagram_f1 is None else f"{diagram_f1:.1%}"
        typer.echo(
            f"{result.model}: kitchen F1 {kitchen_f1:.1%} · diagram F1 {diagram} · "
            f"{result.images_per_second:.2f} images/s · {result.peak_rss_mb:.0f} MB peak RSS"
        )
    typer.echo(f"JSON report: {out}")
    typer.echo(f"Markdown report: {markdown_out}")


@app.command("vision-ml-export-clip-onnx")
def vision_ml_export_clip_onnx_cmd(
    benchmark_root: Path = typer.Option(
        Path("worker/tests/fixtures/vision_benchmark"),
        "--benchmark-root",
        help="Gitignored directory containing the downloaded CLIP model and MIT dataset.",
    ),
    overwrite: bool = typer.Option(False, "--overwrite", help="Replace prior generated exports."),
) -> None:
    """Export vision-only CLIP FP32/signed/unsigned-int8 ONNX artifacts."""
    from manzil_worker.evals.clip_onnx import ClipONNXExportError, export_clip_onnx

    try:
        results = export_clip_onnx(benchmark_root, overwrite=overwrite)
    except ClipONNXExportError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None
    for variant, result in results.items():
        typer.echo(
            f"{variant}: {result['bytes'] / 1_000_000:.1f} MB · "
            f"max parity error {result['max_abs_error']:.3g} · {result['path']}"
        )


@app.command("extract-corpus")
def extract_corpus(slug: str) -> None:
    """Run only EXTRACT -> VERIFY for one saved corpus slug; emit raw JSON.

    Uses cleaned.txt without fetching or grading, and freezes date-sensitive
    verification to meta.json.saved_at like the bench. Honors MANZIL_LLM_MODE;
    record mode saves both LLM responses through the normal recording seam.
    """
    from manzil_shared.errors import ManzilError

    from manzil_worker.evals.corpus_run import run_corpus_extraction
    from manzil_worker.fetching.corpus import CORPUS_DIR
    from manzil_worker.phase0_rubric import phase0_rubric
    from manzil_worker.stages.base import StageCtx

    try:
        result = asyncio.run(
            run_corpus_extraction(
                slug,
                corpus_dir=CORPUS_DIR,
                ctx=StageCtx(rubric=phase0_rubric()),
            )
        )
    except (ManzilError, ValueError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None
    typer.echo(result.model_dump_json(indent=2))


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
    from manzil_worker.evals.labels import LABELS_DIR, LabelError, load_labels_split
    from manzil_worker.fetching.corpus import CORPUS_DIR
    from manzil_worker.llm.config import model_for_stage
    from manzil_worker.phase0_rubric import phase0_rubric
    from manzil_worker.stages.base import StageCtx

    try:
        # Unfinished-skeleton labels (null/empty values) are partitioned into
        # `skipped` and reported, not graded; only broken labels abort.
        labels, skipped = load_labels_split(slugs, LABELS_DIR)
    except LabelError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None
    if not labels and not skipped:
        typer.echo(
            f"no labels in {LABELS_DIR} — `manzil bench-skeleton <slug>` then label by hand",
            err=True,
        )
        raise typer.Exit(code=1)

    rubric = phase0_rubric()
    ctx = StageCtx(rubric=rubric)
    report = asyncio.run(
        run_bench(
            labels,
            corpus_dir=CORPUS_DIR,
            ctx=ctx,
            gate_keys=gate_keys_from(rubric),
            skipped=skipped,
        )
    )

    model_name = model_for_stage("extract").replace("/", "_")
    stem = name or (datetime.now(UTC).strftime("%Y%m%d-%H%M%S") + "--" + model_name)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{stem}.json"
    out.write_text(report.model_dump_json(indent=2) + "\n")
    console.print(Markdown(report_text(report)))
    typer.echo(f"\nreport written to {out}")
    if report.listings and all(listing.error is not None for listing in report.listings):
        raise typer.Exit(code=1)


@app.command("bench-audit-scoped")
def bench_audit_scoped(
    slugs: list[str] = typer.Option([], "--label", help="Canonical label slugs to audit"),
) -> None:
    """Audit P3-SC4 human-label count and required scoped/diagram cases."""
    from manzil_worker.evals.labels import (
        LABELS_DIR,
        SC6_REQUIRED_COVERAGE,
        SC7_REQUIRED_COVERAGE,
        LabelError,
        load_labels_split,
        scoped_coverage_audit,
        scoped_tranche_coverage_audit,
    )

    try:
        labels, skipped = load_labels_split(slugs, LABELS_DIR)
    except LabelError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None
    coverage = scoped_coverage_audit(labels)
    typer.echo(f"gradeable labels: {len(labels)} (canonical target: 10)")
    typer.echo(f"unfinished labels: {len(skipped)}")
    for case, contributors in coverage.items():
        status = "covered" if contributors else "MISSING"
        typer.echo(f"{case}: {status}" + (f" — {', '.join(contributors)}" if contributors else ""))
    tranche_coverage = scoped_tranche_coverage_audit(labels)
    tranche_missing = False
    for key, cases in tranche_coverage.items():
        required = SC7_REQUIRED_COVERAGE if key == "flooring_materials" else SC6_REQUIRED_COVERAGE
        missing = [case for case in required if not cases[case]]
        tranche_missing = tranche_missing or bool(missing)
        typer.echo(f"{key}: " + ("covered" if not missing else f"MISSING {', '.join(missing)}"))
    if (
        len(labels) != 10
        or skipped
        or any(not contributors for contributors in coverage.values())
        or tranche_missing
    ):
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


@app.command()
def costs(
    days: int = typer.Option(14, "--days", help="Window for the spend breakdown"),
    hunt_id: str | None = typer.Option(None, "--hunt-id", help="Limit to one Hunt"),
) -> None:
    """Spend by stage and tier-3 credit usage (AD-C).

    The readout that makes the credit counter usable before the admin panel's
    Costs tab exists: the free plan is a fixed monthly allowance, and until
    something reads it, exhausting it looks like an unexplained fetch failure.
    """
    import asyncpg
    from manzil_shared.config import TIER3_FREE_MONTHLY_CREDITS, TIER3_PRICES_USD

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        typer.echo("DATABASE_URL is not set — costs needs the service-role DB URL", err=True)
        raise typer.Exit(code=1)

    async def run() -> None:
        pool = await asyncpg.create_pool(dsn)
        try:
            stages = await pool.fetch(
                """
                select c.stage,
                       sum(c.llm_cost_usd)   as llm,
                       sum(c.fetch_cost_usd) as fetch,
                       sum(c.llm_calls)      as calls,
                       sum(c.fetch_calls)    as fetches
                from job_stage_costs c
                join jobs j on j.id = c.job_id
                where c.updated_at > now() - ($1 || ' days')::interval
                  and ($2::uuid is null or j.hunt_id = $2::uuid)
                group by c.stage
                order by sum(c.llm_cost_usd + c.fetch_cost_usd) desc
                """,
                str(days),
                hunt_id,
            )
            credits = await pool.fetch(
                "select provider, credits from tier3_credit_usage "
                "where month = date_trunc('month', now()) order by provider"
            )
        finally:
            await pool.close()

        if not stages:
            typer.echo(f"no recorded spend in the last {days} days")
        else:
            typer.echo(f"spend by stage, last {days} days")
            typer.echo(f"  {'stage':<16}{'llm':>10}{'fetch':>10}{'total':>10}  calls")
            total_llm = total_fetch = 0.0
            for row in stages:
                llm, fetch = float(row["llm"]), float(row["fetch"])
                total_llm += llm
                total_fetch += fetch
                typer.echo(
                    f"  {row['stage']:<16}{llm:>10.4f}{fetch:>10.4f}{llm + fetch:>10.4f}"
                    f"  {row['calls']} llm / {row['fetches']} fetch"
                )
            typer.echo(
                f"  {'TOTAL':<16}{total_llm:>10.4f}{total_fetch:>10.4f}"
                f"{total_llm + total_fetch:>10.4f}"
            )

        typer.echo("\ntier-3 credits, this calendar month")
        if not credits:
            typer.echo("  none used")
        for row in credits:
            provider, used = row["provider"], int(row["credits"])
            allowance = TIER3_FREE_MONTHLY_CREDITS.get(provider)
            price = TIER3_PRICES_USD.get(provider)
            spent = f"${used * price:.4f}" if price is not None else "unpriced"
            if allowance:
                pct = 100.0 * used / allowance
                typer.echo(f"  {provider}: {used:,} / {allowance:,} ({pct:.1f}%) · {spent}")
            else:
                typer.echo(f"  {provider}: {used:,} (no recorded allowance) · {spent}")

    asyncio.run(run())
