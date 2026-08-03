"""CLI entry point for the metagen command."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

import typer
from dotenv import find_dotenv, load_dotenv

from metadata_enricher import __version__
from metadata_enricher.config.loader import load_config, find_config
from metadata_enricher.input_sources.filesystem import FilesystemInputSource
from metadata_enricher.output import OutputWriter
from metadata_enricher.pipeline import Pipeline
from metadata_enricher.schemas import get_registry
from metadata_enricher.validation import PreFlightValidator

logger = logging.getLogger(__name__)

app = typer.Typer(
    name="metagen",
    help="Metadata Enricher — automatic metadata generation",
    no_args_is_help=True,
)


def _setup_logging(verbose: bool, quiet: bool) -> None:
    if quiet:
        level = logging.WARNING
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s", stream=sys.stderr)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"metagen {__version__}")
        raise typer.Exit()


@app.callback()
def callback(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        help="Show version and exit",
        callback=_version_callback,
        is_eager=True,
    ),
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to YAML config file"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Minimal output"),
) -> None:
    # usecwd=True: search from the directory the user actually runs metagen from
    # (not from this source file's location under site-packages/src).
    load_dotenv(find_dotenv(usecwd=True))
    _setup_logging(verbose, quiet)
    ctx.obj = {"config_path": config, "verbose": verbose, "quiet": quiet}


def _resolve_config_path(explicit: Optional[Path], ctx_config: Optional[Path]) -> Path:
    """Resolve the config path to use, or exit with a friendly message.

    Never lets ``find_config``'s ``FileNotFoundError`` surface as a raw traceback.
    """
    config_path = explicit or ctx_config
    if config_path is not None:
        return config_path
    try:
        return find_config()
    except FileNotFoundError as exc:
        typer.echo(f"Error: {exc}", err=True)
        typer.echo("Use --config/-c to specify a config file explicitly.", err=True)
        raise typer.Exit(1)


@app.command(name="list-schemas")
def list_schemas(ctx: typer.Context) -> None:
    """List all registered metadata schemas."""
    registry = get_registry()
    schemas = registry.list_schemas()
    if not schemas:
        typer.echo("No schemas registered.")
        return
    typer.echo("Available schemas:")
    for name in schemas:
        schema = registry.get(name)
        typer.echo(f"  - {schema.name} (v{schema.version})")


@app.command(name="list-providers")
def list_providers(
    ctx: typer.Context,
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to YAML config"),
) -> None:
    """List providers defined in a config file."""
    ctx_config = ctx.obj.get("config_path") if ctx.obj else None
    config_path = _resolve_config_path(config, ctx_config)
    try:
        pipeline_config = load_config(config_path)
    except Exception as e:
        typer.echo(f"Error loading config: {e}", err=True)
        raise typer.Exit(1)
    typer.echo(f"Providers in {config_path}:")
    for p in pipeline_config.providers:
        default = " (default)" if p.name == pipeline_config.default_provider else ""
        typer.echo(f"  - {p.name}: {p.base_url}{default}")


@app.command()
def validate(
    ctx: typer.Context,
    file: Path = typer.Argument(..., help="Path to input JSON file"),
    schema: str = typer.Option("datacite-4.6", "--schema", "-s", help="Schema name"),
) -> None:
    """Validate an input JSON file for processing."""
    if not file.exists():
        typer.echo(f"Error: File not found: {file}", err=True)
        raise typer.Exit(1)
    registry = get_registry()
    try:
        schema_obj = registry.get(schema)
    except KeyError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    source = FilesystemInputSource()
    try:
        resource = source.fetch(str(file))
    except (FileNotFoundError, ValueError) as e:
        typer.echo(f"Error reading input: {e}", err=True)
        raise typer.Exit(1)
    validator = PreFlightValidator(schema=schema_obj, registry=registry)
    result = validator.validate_resource(resource)
    if result.valid:
        typer.echo(f"\u2713 {file} is valid for processing")
        for w in result.warnings:
            typer.echo(f"  warning: {w}")
    else:
        typer.echo(f"\u2717 {file} is invalid")
        for err in result.errors:
            typer.echo(f"  error: {err}", err=True)
        for w in result.warnings:
            typer.echo(f"  warning: {w}")
        raise typer.Exit(1)


@app.command()
def process(
    ctx: typer.Context,
    input_path: Path = typer.Argument(..., help="Path to input JSON file or directory"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output file or directory"),
    schema: str = typer.Option("datacite-4.6", "--schema", "-s", help="Schema name"),
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to YAML config"),
) -> None:
    """Process input resources and generate metadata.

    Reads JSON input from a file or directory, runs the full agent pipeline,
    and writes enriched metadata to stdout, a file, or a directory.
    """
    if not input_path.exists():
        typer.echo(f"Error: Input not found: {input_path}", err=True)
        raise typer.Exit(1)

    ctx_config = ctx.obj.get("config_path") if ctx.obj else None
    config_path = _resolve_config_path(config, ctx_config)

    try:
        pipeline_config = load_config(config_path)
    except Exception as e:
        typer.echo(f"Error loading config: {e}", err=True)
        raise typer.Exit(1)

    registry = get_registry()
    try:
        schema_obj = registry.get(schema)
    except KeyError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    pipeline = Pipeline(config=pipeline_config)
    output_writer = OutputWriter(schema=schema_obj)
    input_source = FilesystemInputSource()

    results = pipeline.run(input_source, pattern=str(input_path))

    if not results:
        typer.echo("No resources matched the input.", err=True)
        raise typer.Exit(1)

    if len(results) > 1 and output is not None:
        if output.exists() and not output.is_dir():
            typer.echo(
                f"Error: multiple resources were processed but --output '{output}' is a "
                "single file. Pass a directory instead so each resource gets its own file.",
                err=True,
            )
            raise typer.Exit(1)
        output.mkdir(parents=True, exist_ok=True)

    success_count = 0
    for result in results:
        source_path = getattr(result, "source_path", None)
        source_path = source_path if isinstance(source_path, str) else None
        stem = Path(source_path).stem if source_path else None
        if result.success:
            assert result.document is not None
            output_writer.write(result.document, output_path=output, filename_hint=stem)
            success_count += 1
        else:
            source = source_path or result.resource.url or "unknown"
            typer.echo(f"Error processing {source}: {result.error}", err=True)

    total = len(results)
    typer.echo(f"Processed {success_count}/{total} resources successfully", err=True)

    if success_count == 0:
        raise typer.Exit(1)
    if success_count < total:
        raise typer.Exit(2)


if __name__ == "__main__":
    app()
