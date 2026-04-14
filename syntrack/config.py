"""Configuration model and YAML loader."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BlastFiltering(_StrictModel):
    """Filters applied while loading per-genome BLAST tables (design §3.2.1)."""

    min_pident: float = 95.0
    min_length: int = 100
    max_evalue: float = 1.0e-10
    uniqueness_ratio: float = 1.5
    """Bitscore ratio best/second-best required to keep an SCM with multiple hits.
    A value of 0 discards every multi-hit SCM."""


class BlockDetection(_StrictModel):
    """Collinear-block parameters (design §3.3, defaults per IMPLEMENTATION_PLAN D10)."""

    max_gap: int = 300_000
    min_block_size: int = 3


class PairCacheCfg(_StrictModel):
    max_pairs: int = 30


class ServerCfg(_StrictModel):
    host: str = "127.0.0.1"
    port: int = 8765


class RenderingDefaults(_StrictModel):
    block_threshold_bp_per_px: int = 50_000
    max_visible_scms: int = 5_000
    connection_opacity: float = 0.3
    highlight_opacity: float = 0.8
    dimmed_opacity: float = 0.05


class PaletteCfg(_StrictModel):
    """Karyotype-agnostic palette assignment (IMPLEMENTATION_PLAN D14)."""

    distinct_top_n: int = 12
    minor_color: str = "#888888"
    palette_overrides: dict[str, dict[str, str]] = Field(default_factory=dict)


class DataCfg(_StrictModel):
    genomes_csv: Path


class Config(_StrictModel):
    data: DataCfg
    blast_filtering: BlastFiltering = Field(default_factory=BlastFiltering)
    block_detection: BlockDetection = Field(default_factory=BlockDetection)
    pair_cache: PairCacheCfg = Field(default_factory=PairCacheCfg)
    server: ServerCfg = Field(default_factory=ServerCfg)
    rendering_defaults: RenderingDefaults = Field(default_factory=RenderingDefaults)
    palette: PaletteCfg = Field(default_factory=PaletteCfg)
    genome_labels: dict[str, str] = Field(default_factory=dict)


def load_config(path: Path) -> Config:
    """Load and validate a YAML config; resolve relative `genomes_csv` against the file dir."""
    with path.open() as fh:
        raw: Any = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise ValueError(f"config root must be a mapping, got {type(raw).__name__}")
    cfg = Config.model_validate(raw)
    if not cfg.data.genomes_csv.is_absolute():
        cfg.data.genomes_csv = (path.parent / cfg.data.genomes_csv).resolve()
    return cfg
