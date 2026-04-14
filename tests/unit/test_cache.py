"""Tests for syntrack.cache.PairCache (in-memory LRU)."""

from __future__ import annotations

from pathlib import Path

import pytest

from syntrack.cache import PairCache
from syntrack.config import PaletteCfg
from syntrack.derive.block import BlockParams
from syntrack.io.blast import BlastFilterParams
from syntrack.io.manifest import GenomeEntry
from syntrack.store.genome import GenomeStore
from syntrack.store.scm import SCMStore

TEST_PARAMS = BlastFilterParams(min_pident=80.0, min_length=10, max_evalue=1.0)


def _blast(qseqid: str, sseqid: str, sstart: int, send: int, *, bitscore: float = 400.0) -> str:
    return (
        "\t".join(
            str(x) for x in (qseqid, sseqid, 99.0, 100, 0, 0, 1, 100, sstart, send, 1e-50, bitscore)
        )
        + "\n"
    )


def _make(
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
def four_genome_store(tmp_path: Path) -> SCMStore:
    """4 genomes, each with the same SCMs (so every pair has shared content)."""
    entries = []
    for gid in ("A", "B", "C", "D"):
        rows = [_blast(f"OG{i}", "chr1", i * 100, i * 100 + 99) for i in range(1, 11)]
        entries.append(_make(tmp_path, gid, [("chr1", 5000)], rows))
    gs = GenomeStore.load(entries, PaletteCfg())
    return SCMStore.load(entries, TEST_PARAMS, gs)


# ------------------------------ Basic behaviour -----------------------------


def test_first_call_derives_second_call_hits_cache(four_genome_store: SCMStore) -> None:
    cache = PairCache(four_genome_store, BlockParams(), max_pairs=10)
    assert len(cache) == 0
    e1 = cache.get_or_derive("A", "B")
    assert len(cache) == 1
    e2 = cache.get_or_derive("A", "B")
    assert e2 is e1  # same object — not re-derived


def test_directional_keys_are_distinct(four_genome_store: SCMStore) -> None:
    """get_or_derive(A,B) and (B,A) are separate cache entries."""
    cache = PairCache(four_genome_store, BlockParams(), max_pairs=10)
    cache.get_or_derive("A", "B")
    cache.get_or_derive("B", "A")
    assert len(cache) == 2
    assert ("A", "B") in cache
    assert ("B", "A") in cache


def test_contains_membership(four_genome_store: SCMStore) -> None:
    cache = PairCache(four_genome_store, BlockParams(), max_pairs=10)
    assert ("A", "B") not in cache
    cache.get_or_derive("A", "B")
    assert ("A", "B") in cache


def test_peek_does_not_derive(four_genome_store: SCMStore) -> None:
    cache = PairCache(four_genome_store, BlockParams(), max_pairs=10)
    assert cache.peek("A", "B") is None
    assert len(cache) == 0  # peek did not insert


def test_peek_does_not_bump_lru(four_genome_store: SCMStore) -> None:
    cache = PairCache(four_genome_store, BlockParams(), max_pairs=2)
    cache.get_or_derive("A", "B")  # oldest
    cache.get_or_derive("A", "C")
    cache.peek("A", "B")  # should NOT move A,B to MRU
    cache.get_or_derive("A", "D")  # should evict A,B
    assert ("A", "B") not in cache


# ------------------------------ LRU eviction --------------------------------


def test_eviction_at_capacity(four_genome_store: SCMStore) -> None:
    cache = PairCache(four_genome_store, BlockParams(), max_pairs=2)
    cache.get_or_derive("A", "B")  # oldest
    cache.get_or_derive("A", "C")
    cache.get_or_derive("A", "D")  # forces eviction of (A,B)
    assert len(cache) == 2
    assert ("A", "B") not in cache
    assert ("A", "C") in cache
    assert ("A", "D") in cache


def test_access_promotes_lru(four_genome_store: SCMStore) -> None:
    cache = PairCache(four_genome_store, BlockParams(), max_pairs=2)
    cache.get_or_derive("A", "B")  # oldest
    cache.get_or_derive("A", "C")
    cache.get_or_derive("A", "B")  # bump (A,B) to MRU; (A,C) now oldest
    cache.get_or_derive("A", "D")  # should evict (A,C)
    assert ("A", "B") in cache
    assert ("A", "C") not in cache
    assert ("A", "D") in cache


def test_invalid_capacity_rejected(four_genome_store: SCMStore) -> None:
    with pytest.raises(ValueError, match="max_pairs must be positive"):
        PairCache(four_genome_store, BlockParams(), max_pairs=0)


# ------------------------------ Block re-parameterization -------------------


def test_update_block_params_recomputes_blocks_keeps_pairs(
    four_genome_store: SCMStore,
) -> None:
    cache = PairCache(
        four_genome_store, BlockParams(max_gap=300_000, min_block_size=3), max_pairs=10
    )
    e_before = cache.get_or_derive("A", "B")
    pair_before = e_before.pair  # identity of the underlying PairwiseSCM
    blocks_before = e_before.blocks

    # Tighter min_block_size — should reduce blocks (the synthetic data has 1 block of 10).
    n = cache.update_block_params(BlockParams(max_gap=300_000, min_block_size=20))
    assert n == 1  # one cached entry recomputed

    e_after = cache.get_or_derive("A", "B")
    assert e_after.pair is pair_before  # same PairwiseSCM object retained
    # Tighter min_block_size kills the only block (size 10 < 20).
    assert e_after.blocks == ()
    assert blocks_before  # ensure original had at least one


def test_update_block_params_noop_when_unchanged(four_genome_store: SCMStore) -> None:
    params = BlockParams()
    cache = PairCache(four_genome_store, params, max_pairs=10)
    cache.get_or_derive("A", "B")
    n = cache.update_block_params(BlockParams())  # equal but distinct instance
    assert n == 0


def test_block_params_property_reflects_update(four_genome_store: SCMStore) -> None:
    cache = PairCache(four_genome_store, BlockParams(max_gap=100_000), max_pairs=10)
    assert cache.block_params.max_gap == 100_000
    cache.update_block_params(BlockParams(max_gap=500_000))
    assert cache.block_params.max_gap == 500_000


# ------------------------------ Clear ---------------------------------------


def test_clear_empties_cache(four_genome_store: SCMStore) -> None:
    cache = PairCache(four_genome_store, BlockParams(), max_pairs=10)
    cache.get_or_derive("A", "B")
    cache.get_or_derive("C", "D")
    cache.clear()
    assert len(cache) == 0


def test_iter_returns_keys_in_lru_order(four_genome_store: SCMStore) -> None:
    cache = PairCache(four_genome_store, BlockParams(), max_pairs=10)
    cache.get_or_derive("A", "B")
    cache.get_or_derive("A", "C")
    cache.get_or_derive("A", "B")  # bump to MRU
    keys = list(cache)
    # OrderedDict order: ("A","C") oldest, then ("A","B") most-recent
    assert keys == [("A", "C"), ("A", "B")]
