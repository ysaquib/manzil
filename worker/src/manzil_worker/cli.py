"""Phase 0 entry point: `manzil ingest <url>` plus corpus/census tooling
(DESIGN §6, §10.2, §19).

The CLI and the Phase 1+ queue worker are two entry points calling the same
`run_job` — the CLI is not throwaway work. Pipeline wiring lands in P0-10.
"""

import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

import typer

app = typer.Typer(no_args_is_help=True)

DEFAULT_CENSUS_URLS = Path("infra/census_urls.txt")
DEFAULT_CENSUS_OUT = Path("docs/hostile-domain-census.csv")


def _fetchers(tier2: bool) -> dict[int, object]:
    from manzil_worker.fetching.tiers import Tier1Fetcher, Tier2Fetcher

    fetchers: dict[int, object] = {1: Tier1Fetcher()}
    if tier2:
        fetchers[2] = Tier2Fetcher()
    return fetchers


@app.callback()
def main() -> None:
    """Manzil worker CLI."""


@app.command()
def ingest(
    url: str,
    tier2: bool = typer.Option(True, "--tier2/--no-tier2", help="Allow browser escalation"),
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
            fetchers=_fetchers(tier2),  # type: ignore[arg-type]
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


@app.command("llm-smoke")
def llm_smoke() -> None:
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
def clean_corpus() -> None:
    """Regenerate cleaned.txt for every corpus page (run after cleaner changes)."""
    from manzil_worker.fetching.corpus import regenerate_cleaned

    report = regenerate_cleaned()
    if not report:
        typer.echo("corpus is empty — save pages with `manzil save-page`", err=True)
        raise typer.Exit(code=1)
    for slug, raw_bytes, cleaned_chars in report:
        typer.echo(f"{slug}: {raw_bytes} B raw -> {cleaned_chars} chars cleaned")
    typer.echo(f"regenerated {len(report)} pages")


@app.command("save-page")
def save_page_cmd(
    url: str,
    slug: str,
    official: bool = typer.Option(False, "--official", help="Mark source as official site"),
    notes: str = typer.Option("", "--notes"),
    tier2: bool = typer.Option(True, "--tier2/--no-tier2", help="Allow browser escalation"),
) -> None:
    """Fetch a listing page through the tier ladder and save it as a corpus fixture."""
    from manzil_worker.fetching.corpus import save_page
    from manzil_worker.fetching.ladder import fetch_with_ladder
    from manzil_worker.fetching.registry import InMemoryRegistry, PostgresRegistry

    async def run() -> None:
        dsn = os.environ.get("DATABASE_URL")
        registry = PostgresRegistry(dsn) if dsn else InMemoryRegistry()
        ladder = await fetch_with_ladder(url, registry, _fetchers(tier2))  # type: ignore[arg-type]
        typer.echo(f"outcome: {ladder.outcome.value} (tier {ladder.result.tier})")
        if not ladder.result.body:
            typer.echo("no body fetched — nothing saved", err=True)
            raise typer.Exit(code=1)
        page_dir = save_page(ladder.result, slug, is_official=official, notes=notes)
        typer.echo(f"saved {page_dir}")

    asyncio.run(run())


@app.command()
def census(
    urls_file: Path = typer.Argument(DEFAULT_CENSUS_URLS),
    out: Path = typer.Option(DEFAULT_CENSUS_OUT, "--out"),
    tier2: bool = typer.Option(True, "--tier2/--no-tier2", help="Allow browser escalation"),
) -> None:
    """Probe candidate domains through the tier ladder; emit the census CSV (§19)."""
    from manzil_worker.fetching.census import read_url_file, run_census

    urls = read_url_file(urls_file)
    if not urls:
        typer.echo(f"no URLs in {urls_file}", err=True)
        raise typer.Exit(code=1)
    path = asyncio.run(run_census(urls, _fetchers(tier2), out))  # type: ignore[arg-type]
    typer.echo(f"census written to {path} ({len(urls)} URLs)")
