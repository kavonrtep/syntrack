"""Typer CLI entry point — `syntrack`."""

from __future__ import annotations

from pathlib import Path

import typer

from syntrack import __version__

app = typer.Typer(no_args_is_help=True, add_completion=False, help="SynTrack CLI.")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """SynTrack — genome synteny visualization."""


@app.command(name="lint-data")
def lint_data(
    config_path: Path = typer.Option(
        ...,
        "--config",
        "-c",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Path to syntrack_config.yaml",
    ),
) -> None:
    """Load all genomes per the config and report per-genome filtering statistics."""
    typer.echo(f"lint-data: not yet implemented (config={config_path})")
    raise typer.Exit(code=2)


@app.command()
def serve(
    config_path: Path = typer.Option(
        ...,
        "--config",
        "-c",
        exists=True,
        dir_okay=False,
        readable=True,
    ),
    reload: bool = typer.Option(False, "--reload", help="Enable uvicorn auto-reload."),
) -> None:
    """Start the FastAPI server."""
    typer.echo(f"serve: not yet implemented (config={config_path}, reload={reload})")
    raise typer.Exit(code=2)


if __name__ == "__main__":
    app()
