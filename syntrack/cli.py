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


def _require_config(config_path: Path | None) -> Path:
    if config_path is None:
        typer.echo(
            "error: no config provided — pass --config <path> or set "
            "SYNTRACK_CONFIG in the environment",
            err=True,
        )
        raise typer.Exit(code=1)
    return config_path


@app.command(name="lint-data")
def lint_data(
    config_path: Path = typer.Option(
        None,
        "--config",
        "-c",
        envvar="SYNTRACK_CONFIG",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Path to syntrack_config.yaml. Falls back to $SYNTRACK_CONFIG.",
    ),
) -> None:
    """Load all genomes per the config and report per-genome filtering statistics."""
    from syntrack.loader import load_app_state

    config_path = _require_config(config_path)

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
        None,
        "--config",
        "-c",
        envvar="SYNTRACK_CONFIG",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Path to syntrack_config.yaml. Falls back to $SYNTRACK_CONFIG.",
    ),
    host: str = typer.Option(
        None,
        "--host",
        envvar="SYNTRACK_HOST",
        help="Bind address. Overrides server.host in the YAML. "
        "Use 0.0.0.0 inside a container so the published port is reachable.",
    ),
    port: int = typer.Option(
        None,
        "--port",
        envvar="SYNTRACK_PORT",
        help="Bind port. Overrides server.port in the YAML.",
    ),
    reload: bool = typer.Option(False, "--reload", help="Enable uvicorn auto-reload."),
    dev_cors: bool = typer.Option(
        False,
        "--dev-cors",
        help="Allow http://localhost:5173 (Vite dev server). Off in production.",
    ),
) -> None:
    """Start the FastAPI server on the host:port from the config (or overrides)."""
    import uvicorn

    from syntrack.api.app import create_app
    from syntrack.loader import load_app_state

    config_path = _require_config(config_path)

    state = load_app_state(config_path)
    app_instance = create_app(state, dev_cors=dev_cors)

    bind_host = host or state.config.server.host
    bind_port = port or state.config.server.port

    typer.echo("")
    typer.echo(f"SynTrack v{__version__} listening on http://{bind_host}:{bind_port}")
    if bind_host in {"0.0.0.0", "::"}:
        typer.echo(f"  Local browser:   http://localhost:{bind_port}/")
        typer.echo(
            f"  Remote? First forward the port: "
            f"ssh -L {bind_port}:localhost:{bind_port} <this-host>"
        )
    typer.echo("")

    uvicorn.run(
        app_instance,
        host=bind_host,
        port=bind_port,
        reload=reload,
        log_level="info",
    )


if __name__ == "__main__":
    app()
