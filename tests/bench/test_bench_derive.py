"""Performance benchmarks for the backend derivation kernels at ~1M-SCM scale.

These are the two functions that touch million-row arrays per adjacent pair:
:func:`derive_pair` (the inner join) and :func:`detect_blocks` (collinear-block
segmentation). They are skipped in normal test runs (``--benchmark-skip`` in the
default addopts); run them explicitly with::

    ./dev.sh pytest tests/bench --benchmark-only

Use ``--benchmark-compare`` / ``--benchmark-save=NAME`` to track a baseline
across changes (e.g. before/after vectorizing ``detect_blocks``).
"""

from __future__ import annotations

import numpy as np
import pytest

from syntrack.derive.block import BlockParams, detect_blocks
from syntrack.derive.pair import PAIRWISE_DTYPE, PairwiseSCM, derive_pair
from syntrack.store.scm import GENOME_POS_DTYPE

N = 1_000_000
UNIVERSE = 1_200_000
N_SEQ = 7
SPAN = 100


def _make_pair(n: int = N, seed: int = 0) -> PairwiseSCM:
    """Synthesize a realistic g1-sorted PairwiseSCM: mostly collinear runs across
    7 chromosomes, with periodic strand flips and g2 dips that break blocks."""
    rng = np.random.default_rng(seed)
    rows = np.empty(n, dtype=PAIRWISE_DTYPE)

    # g1 sorted by (seq, start): sort the sequence assignment, cumulative starts.
    seq = np.sort(rng.integers(0, N_SEQ, size=n)).astype(np.int16)
    gaps = rng.integers(50, 5_000, size=n).astype(np.int64)
    g1_start = np.cumsum(gaps)
    # g2 tracks g1 with mostly-positive noise (order preserved); occasional
    # negative dips create order breaks, large jumps create gap breaks.
    g2_noise = rng.integers(-300, 5_000, size=n).astype(np.int64)
    g2_start = g1_start + g2_noise

    strand = np.ones(n, dtype=np.int8)
    flip = rng.random(n) < 0.01  # ~1% strand flips, in scattered runs
    strand[flip] = -1

    rows["scm_id_idx"] = rng.integers(0, UNIVERSE, size=n).astype(np.int32)
    rows["g1_seq_idx"] = seq
    rows["g2_seq_idx"] = seq
    rows["g1_start"] = g1_start
    rows["g1_end"] = g1_start + SPAN
    rows["g2_start"] = g2_start
    rows["g2_end"] = g2_start + SPAN
    rows["g1_strand"] = 1
    rows["g2_strand"] = strand
    return PairwiseSCM(g1_id="A", g2_id="B", rows=rows)


def _genome_positions(scm_ids: np.ndarray, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = scm_ids.size
    arr = np.empty(n, dtype=GENOME_POS_DTYPE)
    arr["scm_id_idx"] = scm_ids.astype(np.int32)
    arr["seq_idx"] = rng.integers(0, N_SEQ, size=n).astype(np.int16)
    starts = np.sort(rng.integers(0, 500_000_000, size=n)).astype(np.int64)
    arr["start"] = starts
    arr["end"] = starts + SPAN
    arr["strand"] = 1
    arr["offset"] = starts
    return arr


class _StubStore:
    """Minimal stand-in: derive_pair only reads ``genome_positions``."""

    def __init__(self, positions: dict[str, np.ndarray]) -> None:
        self.genome_positions = positions


@pytest.fixture(scope="module")
def big_pair() -> PairwiseSCM:
    return _make_pair()


@pytest.fixture(scope="module")
def big_store() -> _StubStore:
    # Two genomes of ~1M unique SCMs each, overlapping ~80%.
    a_ids = np.random.default_rng(1).choice(UNIVERSE, size=N, replace=False)
    b_ids = np.random.default_rng(2).choice(UNIVERSE, size=N, replace=False)
    return _StubStore(
        {
            "A": _genome_positions(np.unique(a_ids), seed=11),
            "B": _genome_positions(np.unique(b_ids), seed=22),
        }
    )


@pytest.mark.benchmark
def test_bench_detect_blocks(benchmark: object, big_pair: PairwiseSCM) -> None:
    params = BlockParams(max_gap=300_000, min_block_size=3)
    blocks = benchmark(detect_blocks, big_pair, params)  # type: ignore[operator]
    # Sanity: the synthetic data must actually produce a non-trivial block set,
    # otherwise the benchmark is measuring an empty scan.
    assert len(blocks) > 100


@pytest.mark.benchmark
def test_bench_derive_pair(benchmark: object, big_store: _StubStore) -> None:
    pair = benchmark(derive_pair, big_store, "A", "B")  # type: ignore[operator]
    assert pair.n_shared > 100_000
