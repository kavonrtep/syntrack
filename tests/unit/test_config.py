from pathlib import Path

import pytest
from pydantic import ValidationError

from syntrack.config import Config, load_config


def test_defaults_are_complete() -> None:
    cfg = Config.model_validate({"data": {"genomes_csv": "/dev/null"}})
    assert cfg.blast_filtering.min_pident == 95.0
    assert cfg.blast_filtering.uniqueness_ratio == 1.5
    assert cfg.block_detection.max_gap == 300_000  # D10 default
    assert cfg.block_detection.min_block_size == 3
    assert cfg.pair_cache.max_pairs == 30
    assert cfg.server.port == 8765
    assert cfg.palette.distinct_top_n == 12
    assert cfg.palette.minor_color == "#888888"


def test_load_resolves_relative_csv_path(tmp_path: Path) -> None:
    cfg_yaml = """\
data:
  genomes_csv: ./genomes.csv
blast_filtering:
  min_pident: 90.0
block_detection:
  max_gap: 500000
"""
    cfg_file = tmp_path / "syntrack.yaml"
    cfg_file.write_text(cfg_yaml)
    csv_file = tmp_path / "genomes.csv"
    csv_file.write_text("genome_id,fai,SCM\n")

    cfg = load_config(cfg_file)

    assert cfg.data.genomes_csv == csv_file.resolve()
    assert cfg.blast_filtering.min_pident == 90.0
    assert cfg.block_detection.max_gap == 500_000
    # untouched fields stay at defaults
    assert cfg.block_detection.min_block_size == 3
    assert cfg.blast_filtering.uniqueness_ratio == 1.5


def test_absolute_csv_path_preserved(tmp_path: Path) -> None:
    abs_csv = tmp_path / "abs_genomes.csv"
    abs_csv.write_text("genome_id,fai,SCM\n")
    cfg_file = tmp_path / "syntrack.yaml"
    cfg_file.write_text(f"data:\n  genomes_csv: {abs_csv}\n")

    cfg = load_config(cfg_file)
    assert cfg.data.genomes_csv == abs_csv


def test_unknown_top_level_field_rejected() -> None:
    with pytest.raises(ValidationError):
        Config.model_validate(
            {"data": {"genomes_csv": "/dev/null"}, "typo_field": True},
        )


def test_unknown_nested_field_rejected() -> None:
    with pytest.raises(ValidationError):
        Config.model_validate(
            {
                "data": {"genomes_csv": "/dev/null"},
                "block_detection": {"max_gap": 1, "extra_field": "oops"},
            },
        )


def test_config_root_must_be_mapping(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("- just\n- a\n- list\n")
    with pytest.raises(ValueError, match="config root must be a mapping"):
        load_config(bad)
