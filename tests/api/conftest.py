"""Shared API test fixtures: builds an AppState with synthetic 3-genome data."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from syntrack.api.app import create_app
from syntrack.api.state import AppState
from syntrack.cache import PairCache
from syntrack.config import (
    BlastFiltering,
    BlockDetection,
    Config,
    DataCfg,
    PaletteCfg,
)
from syntrack.derive.block import BlockParams
from syntrack.io.blast import BlastFilterParams
from syntrack.io.manifest import GenomeEntry
from syntrack.store.genome import GenomeStore
from syntrack.store.scm import SCMStore


def _blast_row(qseqid: str, sseqid: str, sstart: int, send: int, *, bitscore: float = 400.0) -> str:
    return (
        "\t".join(
            str(x) for x in (qseqid, sseqid, 99.0, 100, 0, 0, 1, 100, sstart, send, 1e-50, bitscore)
        )
        + "\n"
    )


def _make_genome(
    tmp_path: Path,
    gid: str,
    sequences: list[tuple[str, int]],
    rows: list[str],
) -> GenomeEntry:
    fai = tmp_path / f"{gid}.fai"
    fai.write_text("".join(f"{n}\t{length}\n" for n, length in sequences))
    blast = tmp_path / f"{gid}.blast"
    blast.write_text("".join(rows))
    return GenomeEntry(genome_id=gid, fai_path=fai, blast_path=blast, label=None)


@pytest.fixture
def app_state(tmp_path: Path) -> AppState:
    """3 genomes (A, B, C) on chr1=10000bp with overlapping but distinct SCM sets.

    A: OG01..OG10 forward-strand at chr1 positions 100, 200, ..., 1000
    B: OG01..OG08 same positions; plus OG11, OG12 — collinear + with A
    C: OG05..OG14 reverse-strand at chr1 positions 4900, 4800, ..., 4000
       (spatial order opposite to A, on - strand → real inversion)

    Expected universe: OG01..OG14 = 14
    A ∩ B = OG01..OG08 (8); A ∩ C = OG05..OG10 (6); B ∩ C = OG05..OG08, OG11, OG12 (6)
    """
    a_rows = [_blast_row(f"OG{i:02d}", "chr1", i * 100, i * 100 + 99) for i in range(1, 11)]
    b_rows = [_blast_row(f"OG{i:02d}", "chr1", i * 100, i * 100 + 99) for i in range(1, 9)]
    b_rows += [
        _blast_row("OG11", "chr1", 900, 999),
        _blast_row("OG12", "chr1", 1000, 1099),
    ]
    # C: OG05..OG14 reverse-strand (sstart > send), at decreasing positions.
    # When sorted by g1 (A ascending), g2 (C) decreases monotonically — clean inversion.
    c_rows = []
    for j, i in enumerate(range(5, 15)):  # OG05..OG14, j = 0..9
        pos = 4900 - j * 100
        c_rows.append(_blast_row(f"OG{i:02d}", "chr1", pos + 99, pos))

    entries = [
        _make_genome(tmp_path, "A", [("chr1", 10_000)], a_rows),
        _make_genome(tmp_path, "B", [("chr1", 10_000)], b_rows),
        _make_genome(tmp_path, "C", [("chr1", 10_000)], c_rows),
    ]
    palette = PaletteCfg()
    gs = GenomeStore.load(entries, palette)
    params = BlastFilterParams(min_pident=80.0, min_length=10, max_evalue=1.0)
    scm = SCMStore.load(entries, params, gs)
    cfg = Config(
        data=DataCfg(genomes_csv=tmp_path / "stub.csv"),
        blast_filtering=BlastFiltering(),
        block_detection=BlockDetection(min_block_size=2),  # smaller for synthetic data
        palette=palette,
    )
    cache = PairCache(scm, BlockParams(min_block_size=2), max_pairs=30)
    return AppState(config=cfg, genome_store=gs, scm_store=scm, pair_cache=cache)


@pytest.fixture
def app(app_state: AppState) -> FastAPI:
    return create_app(app_state)


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)
