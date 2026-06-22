"""Metadata Enricher CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from metadata_enricher import __version__

app = typer.Typer(
    name="metagen",
    help="Metadata Enricher — automatic metadata generation",
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"metagen {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        help="Show version and exit",
        callback=_version_callback,
        is_eager=True,
    ),
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to YAML config file"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose output"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress output"),
) -> None:
    """Metadata Enricher CLI."""


@app.command()
def process(
    input_path: Path = typer.Argument(..., help="Input JSON file or glob pattern"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output file path"),
    schema: str = typer.Option("datacite-4.6", "--schema", "-s", help="Metadata schema to use"),
) -> None:
    """Process input metadata file(s) through the enrichment pipeline."""
    typer.echo("Not yet implemented")
    raise typer.Exit(1)


@app.command()
def validate(
    file: Path = typer.Argument(..., help="Metadata JSON file to validate"),
    schema: str = typer.Option("datacite-4.6", "--schema", "-s", help="Schema to validate against"),
) -> None:
    """Validate a metadata JSON file against a schema."""
    typer.echo("Not yet implemented")
    raise typer.Exit(1)


@app.command()
def list_schemas() -> None:
    """List available metadata schemas."""
    typer.echo("Not yet implemented")
    raise typer.Exit(1)


@app.command()
def list_providers() -> None:
    """List available LLM providers."""
    typer.echo("Not yet implemented")
    raise typer.Exit(1)


if __name__ == "__main__":
    app()
