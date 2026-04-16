"""Tests for syntrack.store.scm — SCMStore loading, queries, and global lookup."""

from __future__ import annotations

from pathlib import Path

import pytest

from syntrack.config import PaletteCfg, load_config
from syntrack.io.blast import BlastFilterParams
from syntrack.io.manifest import GenomeEntry, read_manifest
from syntrack.store.genome import GenomeStore
from syntrack.store.scm import SCMStore

# Lower thresholds so synthetic fixtures pass easily.
TEST_PARAMS = BlastFilterParams(min_pident=80.0, min_length=10, max_evalue=1.0)


def _blast_row(
    qseqid: str,
    sseqid: str,
    sstart: int,
    send: int,
    *,
    pident: float = 99.0,
    length: int = 100,
    bitscore: float = 400.0,
    evalue: float = 1e-50,
) -> str:
    return (
        "\t".join(
            str(x)
            for x in (
                qseqid,
                sseqid,
                pident,
                length,
                0,
                0,
                1,
                length,
                sstart,
                send,
                evalue,
                bitscore,
            )
        )
        + "\n"
    )


def _make_genome(
    tmp_path: Path,
    gid: str,
    sequences: list[tuple[str, int]],
    blast_rows: list[str],
) -> GenomeEntry:
    fai = tmp_path / f"{gid}.fai"
    fai.write_text("".join(f"{n}\t{length}\n" for n, length in sequences))
    blast = tmp_path / f"{gid}.blast"
    blast.write_text("".join(blast_rows))
    return GenomeEntry(genome_id=gid, fai_path=fai, blast_path=blast, label=None)


@pytest.fixture
def two_genome_setup(tmp_path: Path) -> tuple[list[GenomeEntry], GenomeStore]:
    """Genome A and B each with chr1=2000bp, sharing some SCMs.

    A: OG1@100, OG2@500, OG3@800
    B: OG2@200, OG3@1500, OG4@1700
    Universe: {OG1, OG2, OG3, OG4} = 4 SCMs
    Shared A∩B: {OG2, OG3}
    """
    entries = [
        _make_genome(
            tmp_path,
            "A",
            [("chr1", 2000)],
            [
                _blast_row("OG1", "chr1", 100, 199),
                _blast_row("OG2", "chr1", 500, 599),
                _blast_row("OG3", "chr1", 800, 899),
            ],
        ),
        _make_genome(
            tmp_path,
            "B",
            [("chr1", 2000)],
            [
                _blast_row("OG2", "chr1", 200, 299),
                _blast_row("OG3", "chr1", 1500, 1599),
                _blast_row("OG4", "chr1", 1700, 1799),
            ],
        ),
    ]
    gs = GenomeStore.load(entries, PaletteCfg())
    return entries, gs


def test_universe_is_sorted_union(two_genome_setup: tuple[list[GenomeEntry], GenomeStore]) -> None:
    entries, gs = two_genome_setup
    store = SCMStore.load(entries, TEST_PARAMS, gs)
    assert store.universe == ["OG1", "OG2", "OG3", "OG4"]
    assert store.universe_size == 4


def test_genome_positions_sorted_by_offset(
    two_genome_setup: tuple[list[GenomeEntry], GenomeStore],
) -> None:
    entries, gs = two_genome_setup
    store = SCMStore.load(entries, TEST_PARAMS, gs)
    arr = store.genome_positions["A"]
    offsets = arr["offset"].tolist()
    assert offsets == sorted(offsets)


def test_scm_count_per_genome(two_genome_setup: tuple[list[GenomeEntry], GenomeStore]) -> None:
    entries, gs = two_genome_setup
    store = SCMStore.load(entries, TEST_PARAMS, gs)
    assert store.scm_count("A") == 3
    assert store.scm_count("B") == 3


def test_shared_count(two_genome_setup: tuple[list[GenomeEntry], GenomeStore]) -> None:
    entries, gs = two_genome_setup
    store = SCMStore.load(entries, TEST_PARAMS, gs)
    assert store.shared_count("A", "B") == 2  # OG2, OG3
    assert store.shared_count("B", "A") == 2  # symmetry


def test_hits_in_region(two_genome_setup: tuple[list[GenomeEntry], GenomeStore]) -> None:
    entries, gs = two_genome_setup
    store = SCMStore.load(entries, TEST_PARAMS, gs)

    # On A's chr1, region [400, 700) should include OG2@500
    hits = store.hits_in_region("A", "chr1", 400, 700)
    assert hits.size == 1
    og2_idx = store.universe_index["OG2"]
    assert hits[0]["scm_id_idx"] == og2_idx

    # Region covering all of chr1 → all 3 SCMs
    hits = store.hits_in_region("A", "chr1", 0, 2000)
    assert hits.size == 3


def test_hits_in_region_invalid_args(
    two_genome_setup: tuple[list[GenomeEntry], GenomeStore],
) -> None:
    entries, gs = two_genome_setup
    store = SCMStore.load(entries, TEST_PARAMS, gs)
    with pytest.raises(ValueError, match="invalid region"):
        store.hits_in_region("A", "chr1", -1, 100)
    with pytest.raises(ValueError, match="invalid region"):
        store.hits_in_region("A", "chr1", 200, 100)


def test_positions_of_id_returns_all_genomes(
    two_genome_setup: tuple[list[GenomeEntry], GenomeStore],
) -> None:
    entries, gs = two_genome_setup
    store = SCMStore.load(entries, TEST_PARAMS, gs)
    # OG2 is in both A and B
    pos = store.positions_of_id("OG2")
    assert pos.size == 2
    genome_indices = {int(p["genome_idx"]) for p in pos}
    assert genome_indices == {store.genome_id_to_idx["A"], store.genome_id_to_idx["B"]}

    # OG1 is only in A
    pos = store.positions_of_id("OG1")
    assert pos.size == 1
    assert int(pos[0]["genome_idx"]) == store.genome_id_to_idx["A"]


def test_positions_of_unknown_returns_empty(
    two_genome_setup: tuple[list[GenomeEntry], GenomeStore],
) -> None:
    entries, gs = two_genome_setup
    store = SCMStore.load(entries, TEST_PARAMS, gs)
    assert store.positions_of_id("NEVER_SEEN").size == 0
    assert store.positions_of(99999).size == 0


def test_csr_offsets_consistent(two_genome_setup: tuple[list[GenomeEntry], GenomeStore]) -> None:
    """Sum of slice sizes equals total hit count."""
    entries, gs = two_genome_setup
    store = SCMStore.load(entries, TEST_PARAMS, gs)
    total = sum(store.positions_of(i).size for i in range(store.universe_size))
    expected = sum(store.scm_count(g) for g in store.genome_ids)
    assert total == expected


def test_global_offset_is_seq_offset_plus_local_start(tmp_path: Path) -> None:
    """A genome with two sequences — verify global offset uses cumulative seq.offset."""
    entries = [
        _make_genome(
            tmp_path,
            "A",
            [("chr1", 1000), ("chr2", 1000)],
            [
                _blast_row("OG1", "chr1", 100, 199),  # global offset 99
                _blast_row("OG2", "chr2", 200, 299),  # global offset 1000 + 199 = 1199
            ],
        ),
    ]
    gs = GenomeStore.load(entries, PaletteCfg())
    store = SCMStore.load(entries, TEST_PARAMS, gs)
    arr = store.genome_positions["A"]
    # Sorted by offset; OG1 first (99), OG2 second (1199)
    assert int(arr[0]["offset"]) == 99
    assert int(arr[1]["offset"]) == 1199


def test_filtering_stats_recorded(two_genome_setup: tuple[list[GenomeEntry], GenomeStore]) -> None:
    entries, gs = two_genome_setup
    store = SCMStore.load(entries, TEST_PARAMS, gs)
    assert set(store.filtering_stats) == {"A", "B"}
    assert store.filtering_stats["A"].after_validation == 3


def test_reference_seq_map_present_and_absent(
    two_genome_setup: tuple[list[GenomeEntry], GenomeStore],
) -> None:
    entries, gs = two_genome_setup
    store = SCMStore.load(entries, TEST_PARAMS, gs)

    ref_map = store.reference_seq_map("A")
    # A has OG1, OG2, OG3 — all on seq idx 0 (chr1). OG4 is absent from A → -1.
    og1_idx = store.universe_index["OG1"]
    og4_idx = store.universe_index["OG4"]
    assert int(ref_map[og1_idx]) == 0
    assert int(ref_map[og4_idx]) == -1


def test_reference_seq_map_is_cached(
    two_genome_setup: tuple[list[GenomeEntry], GenomeStore],
) -> None:
    entries, gs = two_genome_setup
    store = SCMStore.load(entries, TEST_PARAMS, gs)
    first = store.reference_seq_map("A")
    second = store.reference_seq_map("A")
    assert first is second  # same object returned on second call


def test_reference_seq_map_unknown_genome_raises(
    two_genome_setup: tuple[list[GenomeEntry], GenomeStore],
) -> None:
    entries, gs = two_genome_setup
    store = SCMStore.load(entries, TEST_PARAMS, gs)
    with pytest.raises(KeyError):
        store.reference_seq_map("ghost")


def test_reference_seq_map_respects_multi_sequence_genome(tmp_path: Path) -> None:
    """An SCM landing on chr2 in the reference should return seq_idx=1."""
    entries = [
        _make_genome(
            tmp_path,
            "A",
            [("chr1", 1000), ("chr2", 1000)],
            [
                _blast_row("OG1", "chr1", 100, 199),
                _blast_row("OG2", "chr2", 100, 199),
            ],
        ),
        _make_genome(
            tmp_path,
            "B",
            [("chr1", 1000)],
            [_blast_row("OG1", "chr1", 100, 199), _blast_row("OG2", "chr1", 500, 599)],
        ),
    ]
    gs = GenomeStore.load(entries, PaletteCfg())
    store = SCMStore.load(entries, TEST_PARAMS, gs)
    ref_map = store.reference_seq_map("A")
    assert int(ref_map[store.universe_index["OG1"]]) == 0  # chr1
    assert int(ref_map[store.universe_index["OG2"]]) == 1  # chr2


def test_genome_with_no_kept_scms(tmp_path: Path) -> None:
    """A genome whose BLAST is filtered to zero rows should still load cleanly."""
    entries = [
        _make_genome(tmp_path, "A", [("chr1", 1000)], []),  # empty blast
        _make_genome(
            tmp_path,
            "B",
            [("chr1", 1000)],
            [_blast_row("OG1", "chr1", 100, 199)],
        ),
    ]
    gs = GenomeStore.load(entries, PaletteCfg())
    store = SCMStore.load(entries, TEST_PARAMS, gs)
    assert store.scm_count("A") == 0
    assert store.scm_count("B") == 1
    assert store.universe == ["OG1"]
    assert store.shared_count("A", "B") == 0


@pytest.mark.integration
def test_load_real_pea_dataset() -> None:
    """End-to-end: load all 8 pea genomes from example_data/."""
    cfg_path = Path("example_data/syntrack_config.yaml")
    if not cfg_path.exists():
        pytest.skip("example_data not linked")

    cfg = load_config(cfg_path)
    manifest = read_manifest(cfg.data.genomes_csv)
    gs = GenomeStore.load(manifest, cfg.palette, cfg.genome_labels)
    params = BlastFilterParams(
        min_pident=cfg.blast_filtering.min_pident,
        min_length=cfg.blast_filtering.min_length,
        max_evalue=cfg.blast_filtering.max_evalue,
        uniqueness_ratio=cfg.blast_filtering.uniqueness_ratio,
    )
    store = SCMStore.load(manifest, params, gs)

    assert len(store.genome_ids) == 8
    # Every genome should have a healthy SCM count.
    for gid in store.genome_ids:
        assert store.scm_count(gid) > 50_000, f"{gid}: too few SCMs"
    # Universe should be in the expected range (200K-1.5M per design §1.4).
    assert 100_000 < store.universe_size < 2_000_000
