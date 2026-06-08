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
    from syntrack.perf import configure_logging

    configure_logging()
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


def _resolve_pairs(spec: str, genome_ids: list[str]) -> list[tuple[str, str]]:
    """Turn a --pairs spec into an ordered list of (g1, g2) pairs.

    ``all``       — every ordered pair (N*(N-1)).
    ``adjacent``  — manifest-order neighbours, both directions.
    ``g1:g2,...`` — explicit colon-separated pairs.
    """
    import itertools

    known = set(genome_ids)
    spec = spec.strip()
    if spec == "all":
        return list(itertools.permutations(genome_ids, 2))
    if spec == "adjacent":
        out: list[tuple[str, str]] = []
        for a, b in itertools.pairwise(genome_ids):
            out.extend([(a, b), (b, a)])
        return out
    pairs: list[tuple[str, str]] = []
    for raw_token in spec.split(","):
        token = raw_token.strip()
        if not token:
            continue
        g1, sep, g2 = token.partition(":")
        if not sep or g1 not in known or g2 not in known or g1 == g2:
            raise typer.BadParameter(
                f"invalid pair {token!r}; expected 'g1:g2' with distinct known genome ids"
            )
        pairs.append((g1, g2))
    if not pairs:
        raise typer.BadParameter("no pairs parsed from --pairs")
    return pairs


@app.command()
def precompute(
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
    output: Path = typer.Option(
        None,
        "--output",
        "-o",
        file_okay=False,
        help="Cache directory to write. Defaults to data.cache_dir from the config.",
    ),
    pairs: str = typer.Option(
        "all",
        "--pairs",
        help="Which pairs: 'all', 'adjacent', or a list like 'A:B,B:A,C:D'.",
    ),
) -> None:
    """Derive pairs and write a `.npz` disk cache so `serve` skips re-derivation."""
    from syntrack.config import load_config
    from syntrack.diskcache import write_cache
    from syntrack.io.manifest import read_manifest
    from syntrack.loader import _to_block_params, _to_filter_params
    from syntrack.perf import configure_logging
    from syntrack.store.genome import GenomeStore
    from syntrack.store.scm import SCMStore

    configure_logging()
    config_path = _require_config(config_path)
    cfg = load_config(config_path)

    out_dir = output or cfg.data.cache_dir
    if out_dir is None:
        typer.echo(
            "error: no output directory — pass --output or set data.cache_dir in the config",
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        manifest = read_manifest(cfg.data.genomes_csv)
        genome_store = GenomeStore.load(manifest, cfg.palette, cfg.genome_labels)
        scm_store = SCMStore.load(manifest, _to_filter_params(cfg), genome_store)
        pair_list = _resolve_pairs(pairs, scm_store.genome_ids)
    except (FileNotFoundError, ValueError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    total = len(pair_list)
    typer.echo(f"Precomputing {total} pairs into {out_dir} ...")

    def _progress(i: int, total: int, g1: str, g2: str, n_shared: int) -> None:
        typer.echo(f"  [{i + 1:>4}/{total}] {g1} -> {g2}: {n_shared:,} shared SCMs")

    write_cache(
        out_dir,
        scm_store,
        pair_list,
        blast_params=_to_filter_params(cfg),
        block_params=_to_block_params(cfg),
        manifest=manifest,
        progress=_progress,
    )

    disk_bytes = sum(f.stat().st_size for f in out_dir.glob("*.npz"))
    typer.echo("")
    typer.echo(f"Done: {total} pairs, {disk_bytes / 1e9:.2f} GB in {out_dir}")
    typer.echo("Set data.cache_dir to this path (or it already is) and `syntrack serve`.")


if __name__ == "__main__":
    app()
