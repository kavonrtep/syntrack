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
    from syntrack.loader import load_app_state

    try:
        state = load_app_state(config_path)
    except (FileNotFoundError, ValueError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Loaded {len(state.genome_store)} genomes from {config_path}")
    typer.echo(f"SCM universe size: {state.scm_store.universe_size}")
    typer.echo("")
    header = (
        f"{'genome_id':<28} {'raw':>10} {'+qual':>10} {'+uniq':>10} {'+valid':>10}  "
        "discarded (qual/multi/valid)"
    )
    typer.echo(header)
    typer.echo("-" * len(header))
    for genome in state.genome_store:
        s = state.scm_store.filtering_stats[genome.id]
        typer.echo(
            f"{genome.id:<28} "
            f"{s.raw_hits:>10} {s.after_quality:>10} "
            f"{s.after_uniqueness:>10} {s.after_validation:>10}  "
            f"{s.discarded_quality_rows} / "
            f"{s.discarded_multicopy_scms} / "
            f"{s.discarded_validation_scms}"
        )


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
    dev_cors: bool = typer.Option(
        False,
        "--dev-cors",
        help="Allow http://localhost:5173 (Vite dev server). Off in production.",
    ),
) -> None:
    """Start the FastAPI server on the host:port from the config."""
    import uvicorn

    from syntrack.api.app import create_app
    from syntrack.loader import load_app_state

    state = load_app_state(config_path)
    app_instance = create_app(state, dev_cors=dev_cors)

    typer.echo(
        f"SynTrack listening on http://{state.config.server.host}:{state.config.server.port}"
    )
    uvicorn.run(
        app_instance,
        host=state.config.server.host,
        port=state.config.server.port,
        reload=reload,
        log_level="info",
    )


if __name__ == "__main__":
    app()
