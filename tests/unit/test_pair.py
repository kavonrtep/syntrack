"""Tests for syntrack.derive.pair — merge-join correctness."""

from __future__ import annotations

from pathlib import Path

import pytest

from syntrack.config import PaletteCfg
from syntrack.derive.pair import PAIRWISE_DTYPE, derive_pair
from syntrack.io.blast import BlastFilterParams
from syntrack.io.manifest import GenomeEntry
from syntrack.store.genome import GenomeStore
from syntrack.store.scm import SCMStore

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
                1e-50,
                bitscore,
            )
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


def _load(tmp_path: Path, entries: list[GenomeEntry]) -> SCMStore:
    gs = GenomeStore.load(entries, PaletteCfg())
    return SCMStore.load(entries, TEST_PARAMS, gs)


def test_disjoint_scms_yield_empty_pair(tmp_path: Path) -> None:
    entries = [
        _make(tmp_path, "A", [("chr1", 1000)], [_blast_row("OG1", "chr1", 100, 199)]),
        _make(tmp_path, "B", [("chr1", 1000)], [_blast_row("OG2", "chr1", 100, 199)]),
    ]
    scm = _load(tmp_path, entries)
    pair = derive_pair(scm, "A", "B")
    assert pair.n_shared == 0
    assert pair.rows.dtype == PAIRWISE_DTYPE


def test_identical_scm_sets_all_shared(tmp_path: Path) -> None:
    entries = [
        _make(
            tmp_path,
            "A",
            [("chr1", 2000)],
            [
                _blast_row("OG1", "chr1", 100, 199),
                _blast_row("OG2", "chr1", 500, 599),
            ],
        ),
        _make(
            tmp_path,
            "B",
            [("chr1", 2000)],
            [
                _blast_row("OG1", "chr1", 800, 899),
                _blast_row("OG2", "chr1", 1500, 1599),
            ],
        ),
    ]
    scm = _load(tmp_path, entries)
    pair = derive_pair(scm, "A", "B")
    assert pair.n_shared == 2
    scm_ids_in_pair = {scm.universe[i] for i in pair.rows["scm_id_idx"]}
    assert scm_ids_in_pair == {"OG1", "OG2"}


def test_partial_overlap(tmp_path: Path) -> None:
    entries = [
        _make(
            tmp_path,
            "A",
            [("chr1", 2000)],
            [
                _blast_row("OG1", "chr1", 100, 199),
                _blast_row("OG2", "chr1", 500, 599),
                _blast_row("OG3", "chr1", 800, 899),
            ],
        ),
        _make(
            tmp_path,
            "B",
            [("chr1", 2000)],
            [
                _blast_row("OG2", "chr1", 200, 299),
                _blast_row("OG3", "chr1", 600, 699),
                _blast_row("OG4", "chr1", 900, 999),
            ],
        ),
    ]
    scm = _load(tmp_path, entries)
    pair = derive_pair(scm, "A", "B")
    assert pair.n_shared == 2  # OG2, OG3


def test_rows_sorted_by_g1_seq_then_start(tmp_path: Path) -> None:
    """After derivation, rows must be sorted for block detection."""
    entries = [
        _make(
            tmp_path,
            "A",
            [("chr1", 1000), ("chr2", 1000)],
            [
                _blast_row("OGz", "chr2", 100, 199),
                _blast_row("OGa", "chr1", 100, 199),
                _blast_row("OGm", "chr1", 500, 599),
            ],
        ),
        _make(
            tmp_path,
            "B",
            [("chr1", 1000)],
            [
                _blast_row("OGa", "chr1", 200, 299),
                _blast_row("OGm", "chr1", 600, 699),
                _blast_row("OGz", "chr1", 800, 899),
            ],
        ),
    ]
    scm = _load(tmp_path, entries)
    pair = derive_pair(scm, "A", "B")
    assert pair.n_shared == 3
    # Sorted by (g1_seq_idx, g1_start): chr1 (idx 0) before chr2 (idx 1)
    g1_seqs = pair.rows["g1_seq_idx"].tolist()
    g1_starts = pair.rows["g1_start"].tolist()
    assert g1_seqs == sorted(g1_seqs)
    # Within chr1, sorted by g1_start
    chr1_starts = [s for seq, s in zip(g1_seqs, g1_starts, strict=True) if seq == 0]
    assert chr1_starts == sorted(chr1_starts)


def test_strand_propagated(tmp_path: Path) -> None:
    """Negative-strand BLAST hits arrive with strand=-1 in the pair."""
    entries = [
        _make(tmp_path, "A", [("chr1", 1000)], [_blast_row("OG1", "chr1", 200, 100)]),  # rev
        _make(tmp_path, "B", [("chr1", 1000)], [_blast_row("OG1", "chr1", 100, 200)]),  # fwd
    ]
    scm = _load(tmp_path, entries)
    pair = derive_pair(scm, "A", "B")
    assert pair.rows[0]["g1_strand"] == -1
    assert pair.rows[0]["g2_strand"] == 1


def test_self_pair_rejected(tmp_path: Path) -> None:
    entries = [
        _make(tmp_path, "A", [("chr1", 1000)], [_blast_row("OG1", "chr1", 100, 199)]),
    ]
    scm = _load(tmp_path, entries)
    with pytest.raises(ValueError, match="distinct genomes"):
        derive_pair(scm, "A", "A")


def test_one_genome_empty_yields_empty_pair(tmp_path: Path) -> None:
    entries = [
        _make(tmp_path, "A", [("chr1", 1000)], []),  # no SCMs
        _make(tmp_path, "B", [("chr1", 1000)], [_blast_row("OG1", "chr1", 100, 199)]),
    ]
    scm = _load(tmp_path, entries)
    pair = derive_pair(scm, "A", "B")
    assert pair.n_shared == 0
