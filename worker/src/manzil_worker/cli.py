"""Phase 0 entry point: `manzil ingest <url>` (DESIGN §6, §10.2).

The CLI and the Phase 1+ queue worker are two entry points calling the same
`run_job` — the CLI is not throwaway work. Pipeline wiring lands in P0-10.
"""

import typer

app = typer.Typer(no_args_is_help=True)


@app.callback()
def main() -> None:
    """Manzil worker CLI."""


@app.command()
def ingest(url: str) -> None:
    """Run the ingest pipeline for a listing URL and print the score breakdown."""
    typer.echo(f"ingest {url}: pipeline not implemented yet (P0-10)", err=True)
    raise typer.Exit(code=1)
