"""Metadata Enricher CLI."""

import typer

app = typer.Typer(help="Metadata Enricher — automatic metadata generation", no_args_is_help=True)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Metadata Enricher CLI."""
    if ctx.invoked_subcommand is None:
        typer.echo("Metadata Enricher v0.1.0 — use --help for commands")
