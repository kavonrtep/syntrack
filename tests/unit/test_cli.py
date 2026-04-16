"""Tests for the typer CLI."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from syntrack import __version__
from syntrack.cli import app

runner = CliRunner()


def test_version_flag_prints_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_help_lists_subcommands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "lint-data" in result.stdout
    assert "serve" in result.stdout


def test_no_args_shows_help() -> None:
    # typer's CliRunner returns exit_code=2 when no_args_is_help fires;
    # the binary itself exits 0. Accept either; assert help text was rendered.
    result = runner.invoke(app, [])
    assert result.exit_code in (0, 2)
    assert "lint-data" in result.stdout


# ------------------------------ lint-data ----------------------------------


def _blast(qseqid: str, sseqid: str, sstart: int, send: int) -> str:
    return (
        "\t".join(
            str(x) for x in (qseqid, sseqid, 99.0, 100, 0, 0, 1, 100, sstart, send, 1e-50, 400.0)
        )
        + "\n"
    )


def _setup_dataset(tmp_path: Path) -> Path:
    """Write a tiny 2-genome dataset and return the config path."""
    a_fai = tmp_path / "A.fai"
    a_fai.write_text("chr1\t10000\n")
    b_fai = tmp_path / "B.fai"
    b_fai.write_text("chr1\t10000\n")

    (tmp_path / "A.blast").write_text(
        "".join(_blast(f"OG{i}", "chr1", i * 100, i * 100 + 99) for i in range(1, 6))
    )
    (tmp_path / "B.blast").write_text(
        "".join(_blast(f"OG{i}", "chr1", i * 100, i * 100 + 99) for i in range(3, 8))
    )
    (tmp_path / "genomes.csv").write_text("genome_id,fai,SCM\nA,A.fai,A.blast\nB,B.fai,B.blast\n")
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "data:\n  genomes_csv: ./genomes.csv\n"
        "blast_filtering:\n  min_pident: 80.0\n  min_length: 10\n  max_evalue: 1.0\n"
    )
    return cfg


def test_lint_data_succeeds_on_valid_dataset(tmp_path: Path) -> None:
    cfg = _setup_dataset(tmp_path)
    result = runner.invoke(app, ["lint-data", "--config", str(cfg)])
    assert result.exit_code == 0, result.stdout
    assert "Loaded 2 genomes" in result.stdout
    assert "SCM universe size: 7" in result.stdout  # OG1..OG7
    assert "A " in result.stdout or "A\t" in result.stdout or "A   " in result.stdout
    assert "B " in result.stdout or "B\t" in result.stdout or "B   " in result.stdout


def test_lint_data_fails_when_blast_missing(tmp_path: Path) -> None:
    cfg = _setup_dataset(tmp_path)
    (tmp_path / "B.blast").unlink()
    result = runner.invoke(app, ["lint-data", "--config", str(cfg)])
    assert result.exit_code == 1
    assert "error" in result.stdout.lower() or "error" in (result.stderr or "").lower()


def test_lint_data_fails_on_bad_config(tmp_path: Path) -> None:
    cfg = tmp_path / "bad.yaml"
    cfg.write_text("data:\n  genomes_csv: ./missing.csv\n")
    result = runner.invoke(app, ["lint-data", "--config", str(cfg)])
    assert result.exit_code == 1


def test_lint_data_reads_config_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without --config, SYNTRACK_CONFIG env var is used."""
    cfg = _setup_dataset(tmp_path)
    monkeypatch.setenv("SYNTRACK_CONFIG", str(cfg))
    result = runner.invoke(app, ["lint-data"])
    assert result.exit_code == 0, result.stdout
    assert "Loaded 2 genomes" in result.stdout


def test_lint_data_cli_flag_beats_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--config wins over SYNTRACK_CONFIG when both point at different files."""
    cfg = _setup_dataset(tmp_path)
    # Point env at a nonexistent file; CLI points at the real one.
    monkeypatch.setenv("SYNTRACK_CONFIG", str(tmp_path / "nope.yaml"))
    result = runner.invoke(app, ["lint-data", "--config", str(cfg)])
    assert result.exit_code == 0, result.stdout
    assert "Loaded 2 genomes" in result.stdout


def test_lint_data_errors_when_no_config_anywhere(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SYNTRACK_CONFIG", raising=False)
    result = runner.invoke(app, ["lint-data"])
    assert result.exit_code != 0
    # Error goes either to stderr or stdout (Typer mixes); check both.
    combined = (result.stdout or "") + (result.stderr or "")
    assert "config" in combined.lower()


@pytest.mark.integration
def test_lint_data_on_real_pea_dataset(pea_config_path: Path) -> None:
    result = runner.invoke(app, ["lint-data", "--config", str(pea_config_path)])
    assert result.exit_code == 0, result.stdout
    assert "Loaded 8 genomes" in result.stdout
    assert "JI1006_2026-01-19" in result.stdout
