"""Tests for syntrack.derive.block — every continuity-break branch."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from syntrack.config import load_config
from syntrack.derive.block import BlockParams, detect_blocks
from syntrack.derive.pair import PAIRWISE_DTYPE, PairwiseSCM, derive_pair
from syntrack.io.blast import BlastFilterParams
from syntrack.io.manifest import read_manifest
from syntrack.store.genome import GenomeStore
from syntrack.store.scm import SCMStore


def _row(
    g1_seq: int,
    g1_start: int,
    g2_seq: int,
    g2_start: int,
    *,
    g1_strand: int = 1,
    g2_strand: int = 1,
    scm_idx: int = 0,
    span: int = 100,
) -> tuple[int, int, int, int, int, int, int, int, int]:
    return (
        scm_idx,
        g1_seq,
        g2_seq,
        g1_start,
        g1_start + span,
        g2_start,
        g2_start + span,
        g1_strand,
        g2_strand,
    )


def _pair(rows: list[tuple[int, int, int, int, int, int, int, int, int]]) -> PairwiseSCM:
    arr = np.array(rows, dtype=PAIRWISE_DTYPE)
    # caller is responsible for providing rows in g1-sorted order
    return PairwiseSCM(g1_id="A", g2_id="B", rows=arr)


DEFAULT = BlockParams(max_gap=300_000, min_block_size=3)
SMALL = BlockParams(max_gap=300_000, min_block_size=1)


# ------------------------------- Empty / trivial ---------------------------


def test_empty_pair_no_blocks() -> None:
    pair = PairwiseSCM(g1_id="A", g2_id="B", rows=np.empty(0, dtype=PAIRWISE_DTYPE))
    assert detect_blocks(pair, DEFAULT) == []


def test_single_scm_below_min_size_filtered() -> None:
    pair = _pair([_row(0, 100, 0, 100)])
    assert detect_blocks(pair, DEFAULT) == []


def test_single_scm_kept_with_min_size_one() -> None:
    pair = _pair([_row(0, 100, 0, 100)])
    blocks = detect_blocks(pair, SMALL)
    assert len(blocks) == 1
    assert blocks[0].scm_count == 1


# ------------------------------- Happy path --------------------------------


def test_collinear_run_one_block() -> None:
    pair = _pair(
        [
            _row(0, 100, 0, 200),
            _row(0, 300, 0, 400),
            _row(0, 600, 0, 700),
            _row(0, 900, 0, 1000),
            _row(0, 1200, 0, 1400),
        ]
    )
    blocks = detect_blocks(pair, DEFAULT)
    assert len(blocks) == 1
    b = blocks[0]
    assert b.scm_count == 5
    assert b.g1_start == 100
    assert b.g1_end == 1300  # last g1_start + span
    assert b.g2_start == 200
    assert b.g2_end == 1500  # last g2_start + span
    assert b.relative_strand == 1


def test_negative_strand_collinear_block() -> None:
    """For relative strand -1, g2 must monotonically decrease."""
    pair = _pair(
        [
            _row(0, 100, 0, 1000, g1_strand=1, g2_strand=-1),
            _row(0, 300, 0, 800, g1_strand=1, g2_strand=-1),
            _row(0, 600, 0, 500, g1_strand=1, g2_strand=-1),
        ]
    )
    blocks = detect_blocks(pair, DEFAULT)
    assert len(blocks) == 1
    assert blocks[0].relative_strand == -1
    assert blocks[0].scm_count == 3
    # g2 bounds use min/max regardless of strand
    assert blocks[0].g2_start == 500
    assert blocks[0].g2_end == 1100  # max g2 end (1000 + 100)


# ------------------------------- Continuity breaks --------------------------


def test_order_break_splits_block() -> None:
    """A backward jump in g2 closes the current block and starts a new one."""
    pair = _pair(
        [
            _row(0, 100, 0, 100),
            _row(0, 200, 0, 200),
            _row(0, 300, 0, 50),  # backwards in g2 → breaks order
            _row(0, 400, 0, 400),
            _row(0, 500, 0, 500),
        ]
    )
    blocks = detect_blocks(pair, SMALL)
    # First block [r0, r1] (size 2). r2 starts a new block; r3, r4 are
    # then collinear with r2 (50 -> 400 -> 500), so they merge into one.
    sizes = [b.scm_count for b in blocks]
    assert sizes == [2, 3]


def test_repeated_backward_jumps_yield_singletons() -> None:
    """Each backward jump in a strictly-decreasing-after-first pattern starts fresh."""
    pair = _pair(
        [
            _row(0, 100, 0, 500),
            _row(0, 200, 0, 400),  # g2 decreased: order break (we're in +strand)
            _row(0, 300, 0, 300),  # decreased again: another break
            _row(0, 400, 0, 200),  # decreased: another break
        ]
    )
    blocks = detect_blocks(pair, SMALL)
    # Each row breaks order with the previous → 4 singleton "blocks"
    assert [b.scm_count for b in blocks] == [1, 1, 1, 1]


def test_strand_flip_splits_block() -> None:
    pair = _pair(
        [
            _row(0, 100, 0, 100, g1_strand=1, g2_strand=1),
            _row(0, 200, 0, 200, g1_strand=1, g2_strand=1),
            _row(0, 300, 0, 300, g1_strand=1, g2_strand=-1),  # rel strand flips
            _row(0, 400, 0, 250, g1_strand=1, g2_strand=-1),
        ]
    )
    blocks = detect_blocks(pair, SMALL)
    assert [b.scm_count for b in blocks] == [2, 2]
    assert [b.relative_strand for b in blocks] == [1, -1]


def test_g1_seq_change_splits_block() -> None:
    pair = _pair(
        [
            _row(0, 100, 0, 100),
            _row(0, 200, 0, 200),
            _row(1, 100, 0, 300),  # g1_seq jump
            _row(1, 200, 0, 400),
        ]
    )
    blocks = detect_blocks(pair, SMALL)
    assert [b.scm_count for b in blocks] == [2, 2]
    assert blocks[0].g1_seq_idx == 0
    assert blocks[1].g1_seq_idx == 1


def test_g2_seq_change_splits_block() -> None:
    pair = _pair(
        [
            _row(0, 100, 0, 100),
            _row(0, 200, 0, 200),
            _row(0, 300, 1, 100),  # g2_seq jump
            _row(0, 400, 1, 200),
        ]
    )
    blocks = detect_blocks(pair, SMALL)
    assert [b.scm_count for b in blocks] == [2, 2]
    assert blocks[0].g2_seq_idx == 0
    assert blocks[1].g2_seq_idx == 1


def test_distance_break_splits_block() -> None:
    """A gap > max_gap on either genome should close the block."""
    params = BlockParams(max_gap=1000, min_block_size=1)
    pair = _pair(
        [
            _row(0, 100, 0, 100),
            _row(0, 500, 0, 500),
            _row(0, 100_000, 0, 100_000),  # > max_gap on both axes
        ]
    )
    blocks = detect_blocks(pair, params)
    assert [b.scm_count for b in blocks] == [2, 1]


def test_distance_break_g2_only_splits() -> None:
    """g1 gap fine, g2 gap exceeds max_gap → split."""
    params = BlockParams(max_gap=1000, min_block_size=1)
    pair = _pair(
        [
            _row(0, 100, 0, 100),
            _row(0, 500, 0, 100_000),  # g1 gap 400, g2 gap 99_900
        ]
    )
    blocks = detect_blocks(pair, params)
    assert [b.scm_count for b in blocks] == [1, 1]


# ------------------------------- min_block_size filter ---------------------


def test_min_block_size_filters_small_runs() -> None:
    """A 4-SCM run + a 2-SCM run with min_block_size=3 keeps only the 4-run."""
    pair = _pair(
        [
            # Run of 4 in (0,0)
            _row(0, 100, 0, 100),
            _row(0, 200, 0, 200),
            _row(0, 300, 0, 300),
            _row(0, 400, 0, 400),
            # Sequence change → break
            _row(1, 100, 0, 500),
            _row(1, 200, 0, 600),
        ]
    )
    blocks = detect_blocks(pair, BlockParams(max_gap=300_000, min_block_size=3))
    assert len(blocks) == 1
    assert blocks[0].scm_count == 4


# ------------------------------- Properties --------------------------------


def test_block_ids_are_sequential_starting_at_one() -> None:
    pair = _pair(
        [
            _row(0, 100, 0, 100),
            _row(0, 200, 0, 200),
            _row(0, 300, 0, 300),
            _row(1, 100, 1, 100),
            _row(1, 200, 1, 200),
            _row(1, 300, 1, 300),
        ]
    )
    blocks = detect_blocks(pair, DEFAULT)
    assert [b.block_id for b in blocks] == [1, 2]


def test_blocks_internally_collinear() -> None:
    """For every block, g1 must be monotone increasing within (we sort by g1)."""
    pair = _pair(
        [
            _row(0, 100, 0, 100),
            _row(0, 200, 0, 200),
            _row(0, 300, 0, 300),
            _row(0, 400, 0, 400),
            _row(0, 500, 0, 500),
        ]
    )
    blocks = detect_blocks(pair, DEFAULT)
    for b in blocks:
        assert b.g1_start <= b.g1_end
        assert b.g2_start <= b.g2_end


# ------------------------------- Integration -------------------------------


@pytest.mark.integration
def test_real_pea_pair_derives_and_blocks(pea_config_path: Path) -> None:
    """Derive one pair from the real pea data; block counts should be in a sane range."""
    cfg = load_config(pea_config_path)
    manifest = read_manifest(cfg.data.genomes_csv)
    gs = GenomeStore.load(manifest, cfg.palette, cfg.genome_labels)
    params = BlastFilterParams(
        min_pident=cfg.blast_filtering.min_pident,
        min_length=cfg.blast_filtering.min_length,
        max_evalue=cfg.blast_filtering.max_evalue,
        uniqueness_ratio=cfg.blast_filtering.uniqueness_ratio,
    )
    scm = SCMStore.load(manifest, params, gs)

    g1, g2 = scm.genome_ids[0], scm.genome_ids[1]
    pair = derive_pair(scm, g1, g2)
    assert pair.n_shared > 50_000

    block_params = BlockParams(
        max_gap=cfg.block_detection.max_gap,
        min_block_size=cfg.block_detection.min_block_size,
    )
    blocks = detect_blocks(pair, block_params)
    # Per design §1.4: 1K-10K blocks per pair is typical for related species.
    # With our strict-order + 300kb defaults expect ~the high end of that range
    # because pea is a complex pangenome. Cap at 100K as a sanity ceiling.
    assert 100 < len(blocks) < 100_000

    # Spot-check: every block has scm_count >= 3, coords ascending, sequences
    # within bounds.
    for b in blocks:
        assert b.scm_count >= 3
        assert b.g1_start < b.g1_end
        assert b.g2_start < b.g2_end
