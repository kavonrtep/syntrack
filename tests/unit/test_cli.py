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


def test_lint_data_stub_not_implemented(tmp_path: object) -> None:
    cfg_file = tmp_path / "cfg.yaml"  # type: ignore[operator]
    cfg_file.write_text("data:\n  genomes_csv: ./genomes.csv\n")
    result = runner.invoke(app, ["lint-data", "--config", str(cfg_file)])
    assert result.exit_code == 2
    assert "not yet implemented" in result.stdout
