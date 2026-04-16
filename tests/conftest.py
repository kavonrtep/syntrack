"""Shared fixtures for integration tests that need the real pea example_data."""

from __future__ import annotations

from pathlib import Path

import pytest


def _example_data_ready() -> Path | None:
    """Return the pea example config path if the full example_data tree is
    linked (both the YAML config and the generated ``genomes.csv`` exist),
    otherwise ``None``.

    The YAML config is committed to the repo, but ``genomes.csv`` and the
    FAI / BLAST symlinks are produced by ``example_data/link_data.sh`` and
    are gitignored — so checking the config alone doesn't guarantee the
    dataset is usable. CI (which doesn't run the link script) sees the
    YAML but not the CSV, and tests using this fixture skip cleanly there.
    """
    cfg = Path("example_data/syntrack_config.yaml")
    csv = Path("example_data/genomes.csv")
    if cfg.exists() and csv.exists():
        return cfg
    return None


@pytest.fixture
def pea_config_path() -> Path:
    """Resolve to the pea ``syntrack_config.yaml``; skip the test if the
    example_data symlinks aren't in place."""
    cfg = _example_data_ready()
    if cfg is None:
        pytest.skip(
            "example_data not linked; run example_data/link_data.sh first",
        )
    return cfg
