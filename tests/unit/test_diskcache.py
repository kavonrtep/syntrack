"""Tests for the on-disk .npz pair cache (syntrack.diskcache + PairCache wiring)."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from syntrack.cache import PairCache
from syntrack.config import PaletteCfg
from syntrack.derive.block import BlockParams, detect_blocks
from syntrack.derive.pair import derive_pair
from syntrack.diskcache import (
    DiskPairStore,
    array_to_blocks,
    blocks_to_array,
    dataset_hash,
    write_cache,
)
from syntrack.io.blast import BlastFilterParams
from syntrack.io.manifest import GenomeEntry
from syntrack.store.genome import GenomeStore
from syntrack.store.scm import SCMStore

FILTER = BlastFilterParams(min_pident=80.0, min_length=10, max_evalue=1.0)
BLOCKS = BlockParams(max_gap=300_000, min_block_size=3)


def _blast(qseqid: str, sseqid: str, sstart: int, send: int) -> str:
    return (
        "\t".join(
            str(x) for x in (qseqid, sseqid, 99.0, 100, 0, 0, 1, 100, sstart, send, 1e-50, 400.0)
        )
        + "\n"
    )


def _entry(tmp_path: Path, gid: str) -> GenomeEntry:
    fai = tmp_path / f"{gid}.fai"
    fai.write_text("chr1\t5000\n")
    blast = tmp_path / f"{gid}.blast"
    blast.write_text("".join(_blast(f"OG{i}", "chr1", i * 100, i * 100 + 99) for i in range(1, 11)))
    return GenomeEntry(genome_id=gid, fai_path=fai, blast_path=blast, label=None)


@pytest.fixture
def store_and_manifest(tmp_path: Path) -> tuple[SCMStore, list[GenomeEntry]]:
    entries = [_entry(tmp_path, gid) for gid in ("A", "B", "C")]
    gs = GenomeStore.load(entries, PaletteCfg())
    return SCMStore.load(entries, FILTER, gs), entries


# ------------------------------ Block (de)serialization --------------------


def test_block_array_roundtrip(store_and_manifest: tuple[SCMStore, list[GenomeEntry]]) -> None:
    scm, _ = store_and_manifest
    blocks = detect_blocks(derive_pair(scm, "A", "B"), BLOCKS)
    assert len(blocks) >= 1
    assert array_to_blocks(blocks_to_array(blocks)) == tuple(blocks)


# ------------------------------ write + load round-trip --------------------


def test_write_and_load_matches_direct_derive(
    tmp_path: Path, store_and_manifest: tuple[SCMStore, list[GenomeEntry]]
) -> None:
    scm, manifest = store_and_manifest
    cache_dir = tmp_path / "cache"
    write_cache(
        cache_dir,
        scm,
        [("A", "B"), ("B", "A")],
        blast_params=FILTER,
        block_params=BLOCKS,
        manifest=manifest,
    )

    store = DiskPairStore.open(
        cache_dir, manifest=manifest, blast_params=FILTER, block_params=BLOCKS
    )
    assert store is not None
    assert ("A", "B") in store

    loaded = store.load("A", "B", BLOCKS)
    assert loaded is not None
    direct = derive_pair(scm, "A", "B")
    assert np.array_equal(loaded.pair.rows, direct.rows)
    assert loaded.blocks == tuple(detect_blocks(direct, BLOCKS))


def test_load_unknown_pair_returns_none(
    tmp_path: Path, store_and_manifest: tuple[SCMStore, list[GenomeEntry]]
) -> None:
    scm, manifest = store_and_manifest
    cache_dir = tmp_path / "cache"
    write_cache(
        cache_dir, scm, [("A", "B")], blast_params=FILTER, block_params=BLOCKS, manifest=manifest
    )
    store = DiskPairStore.open(
        cache_dir, manifest=manifest, blast_params=FILTER, block_params=BLOCKS
    )
    assert store is not None
    assert store.load("A", "C", BLOCKS) is None  # not precomputed


# ------------------------------ invalidation -------------------------------


def test_open_none_when_no_manifest(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    assert (
        DiskPairStore.open(
            tmp_path / "empty", manifest=[], blast_params=FILTER, block_params=BLOCKS
        )
        is None
    )


def test_stale_on_filter_param_change(
    tmp_path: Path, store_and_manifest: tuple[SCMStore, list[GenomeEntry]]
) -> None:
    scm, manifest = store_and_manifest
    cache_dir = tmp_path / "cache"
    write_cache(
        cache_dir, scm, [("A", "B")], blast_params=FILTER, block_params=BLOCKS, manifest=manifest
    )
    other = BlastFilterParams(min_pident=95.0, min_length=10, max_evalue=1.0)
    assert (
        DiskPairStore.open(cache_dir, manifest=manifest, blast_params=other, block_params=BLOCKS)
        is None
    )


def test_stale_on_input_mtime_change(
    tmp_path: Path, store_and_manifest: tuple[SCMStore, list[GenomeEntry]]
) -> None:
    scm, manifest = store_and_manifest
    cache_dir = tmp_path / "cache"
    write_cache(
        cache_dir, scm, [("A", "B")], blast_params=FILTER, block_params=BLOCKS, manifest=manifest
    )
    # Bump one input's mtime far into the future -> hash changes -> stale.
    future = 2_000_000_000_000_000_000
    os.utime(manifest[0].blast_path, ns=(future, future))
    assert (
        DiskPairStore.open(cache_dir, manifest=manifest, blast_params=FILTER, block_params=BLOCKS)
        is None
    )


def test_dataset_hash_sensitive_to_filter_and_inputs(
    store_and_manifest: tuple[SCMStore, list[GenomeEntry]],
) -> None:
    _, manifest = store_and_manifest
    base = dataset_hash(manifest, FILTER)
    assert base == dataset_hash(manifest, FILTER)  # stable
    other = BlastFilterParams(min_pident=95.0, min_length=10, max_evalue=1.0)
    assert dataset_hash(manifest, other) != base


def test_block_param_mismatch_loads_pair_recomputes_blocks(
    tmp_path: Path, store_and_manifest: tuple[SCMStore, list[GenomeEntry]]
) -> None:
    scm, manifest = store_and_manifest
    cache_dir = tmp_path / "cache"
    # Precompute with min_block_size=3 -> the 10-SCM run is one block.
    write_cache(
        cache_dir, scm, [("A", "B")], blast_params=FILTER, block_params=BLOCKS, manifest=manifest
    )

    # Open with min_block_size=11 -> blocks invalid; pair still loads, blocks
    # recomputed under the new params (the 10-SCM run is now filtered out).
    strict = BlockParams(max_gap=300_000, min_block_size=11)
    store = DiskPairStore.open(
        cache_dir, manifest=manifest, blast_params=FILTER, block_params=strict
    )
    assert store is not None
    loaded = store.load("A", "B", strict)
    assert loaded is not None
    assert loaded.pair.n_shared == 10  # PairwiseSCM came from disk
    assert loaded.blocks == ()  # recomputed under the stricter param


# ------------------------------ PairCache integration ----------------------


def test_paircache_serves_from_disk_without_deriving(
    tmp_path: Path, store_and_manifest: tuple[SCMStore, list[GenomeEntry]]
) -> None:
    scm, manifest = store_and_manifest
    cache_dir = tmp_path / "cache"
    write_cache(
        cache_dir, scm, [("A", "B")], blast_params=FILTER, block_params=BLOCKS, manifest=manifest
    )
    store = DiskPairStore.open(
        cache_dir, manifest=manifest, blast_params=FILTER, block_params=BLOCKS
    )
    cache = PairCache(scm, BLOCKS, max_pairs=10, disk_store=store)

    with patch("syntrack.cache.derive_pair") as mock_derive:
        entry = cache.get_or_derive("A", "B")
        mock_derive.assert_not_called()  # served from disk, not derived

    direct = derive_pair(scm, "A", "B")
    assert np.array_equal(entry.pair.rows, direct.rows)
    assert entry.blocks == tuple(detect_blocks(direct, BLOCKS))


def test_paircache_derives_when_pair_absent_from_disk(
    tmp_path: Path, store_and_manifest: tuple[SCMStore, list[GenomeEntry]]
) -> None:
    scm, manifest = store_and_manifest
    cache_dir = tmp_path / "cache"
    write_cache(
        cache_dir, scm, [("A", "B")], blast_params=FILTER, block_params=BLOCKS, manifest=manifest
    )
    store = DiskPairStore.open(
        cache_dir, manifest=manifest, blast_params=FILTER, block_params=BLOCKS
    )
    cache = PairCache(scm, BLOCKS, max_pairs=10, disk_store=store)

    # (A, C) wasn't precomputed -> falls through to derivation.
    entry = cache.get_or_derive("A", "C")
    assert entry.pair.n_shared == derive_pair(scm, "A", "C").n_shared
