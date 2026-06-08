"""Top-level loader: config -> manifest -> GenomeStore -> SCMStore -> PairCache."""

from __future__ import annotations

from pathlib import Path

from syntrack.api.state import AppState
from syntrack.cache import PairCache
from syntrack.config import Config, load_config
from syntrack.derive.block import BlockParams
from syntrack.io.blast import BlastFilterParams
from syntrack.io.manifest import read_manifest
from syntrack.perf import timed
from syntrack.store.genome import GenomeStore
from syntrack.store.scm import SCMStore


def _to_filter_params(cfg: Config) -> BlastFilterParams:
    return BlastFilterParams(
        min_pident=cfg.blast_filtering.min_pident,
        min_length=cfg.blast_filtering.min_length,
        max_evalue=cfg.blast_filtering.max_evalue,
        uniqueness_ratio=cfg.blast_filtering.uniqueness_ratio,
    )


def _to_block_params(cfg: Config) -> BlockParams:
    return BlockParams(
        max_gap=cfg.block_detection.max_gap,
        min_block_size=cfg.block_detection.min_block_size,
    )


def load_app_state(config_path: Path) -> AppState:
    """Build a fully-populated AppState from a config file."""
    cfg = load_config(config_path)
    manifest = read_manifest(cfg.data.genomes_csv)
    with timed("load.genome_store", n_genomes=len(manifest)):
        genome_store = GenomeStore.load(manifest, cfg.palette, cfg.genome_labels)
    with timed("load.scm_store", n_genomes=len(manifest)):
        scm_store = SCMStore.load(manifest, _to_filter_params(cfg), genome_store)
    block_params = _to_block_params(cfg)
    pair_cache = PairCache(
        scm_store,
        block_params,
        max_pairs=cfg.pair_cache.max_pairs,
    )
    paint_cache = PairCache(
        scm_store,
        block_params,
        max_pairs=cfg.pair_cache.paint_max_pairs,
    )
    return AppState(
        config=cfg,
        genome_store=genome_store,
        scm_store=scm_store,
        pair_cache=pair_cache,
        paint_cache=paint_cache,
    )
