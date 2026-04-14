"""Tests for syntrack.io.blast — every filter branch on hand-crafted fixtures."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from syntrack.io.blast import (
    OUTPUT_SCHEMA,
    BlastFilterParams,
    parse_and_filter_blast,
)
from syntrack.io.fai import read_fai
from syntrack.io.manifest import read_manifest

DEFAULT = BlastFilterParams()  # min_pident=95, min_length=100, max_evalue=1e-10, ratio=1.5
SEQS: dict[str, int] = {"chr1": 1000, "chr2": 2000}


def _row(
    qseqid: str = "OG1",
    sseqid: str = "chr1",
    *,
    pident: float = 99.0,
    length: int = 200,
    mismatch: int = 1,
    gapopen: int = 0,
    qstart: int = 1,
    qend: int = 200,
    sstart: int = 100,
    send: int = 299,
    evalue: float = 1e-50,
    bitscore: float = 400.0,
) -> tuple[object, ...]:
    return (
        qseqid,
        sseqid,
        pident,
        length,
        mismatch,
        gapopen,
        qstart,
        qend,
        sstart,
        send,
        evalue,
        bitscore,
    )


def _write(path: Path, rows: list[tuple[object, ...]]) -> None:
    path.write_text("".join("\t".join(str(x) for x in r) + "\n" for r in rows))


# ------------------------------- Happy paths --------------------------------


def test_unique_single_hit_kept(tmp_path: Path) -> None:
    f = tmp_path / "b.blast"
    _write(f, [_row("OG1", "chr1", sstart=100, send=299, bitscore=400.0)])
    df, stats = parse_and_filter_blast(f, SEQS, DEFAULT)

    assert df.height == 1
    row = df.row(0, named=True)
    assert row["scm_id"] == "OG1"
    assert row["seq_name"] == "chr1"
    assert row["start"] == 99  # 100 (1-based) - 1 -> 0-based incl
    assert row["end"] == 299  # 299 (1-based incl) -> 299 (0-based excl)
    assert row["strand"] == 1
    assert stats == type(stats)(
        raw_hits=1,
        after_quality=1,
        after_uniqueness=1,
        after_validation=1,
        discarded_quality_rows=0,
        discarded_multicopy_scms=0,
        discarded_validation_scms=0,
    )


def test_negative_strand_normalized(tmp_path: Path) -> None:
    f = tmp_path / "b.blast"
    _write(f, [_row(sstart=299, send=100)])  # reverse-strand hit
    df, _ = parse_and_filter_blast(f, SEQS, DEFAULT)
    row = df.row(0, named=True)
    assert row["start"] == 99
    assert row["end"] == 299
    assert row["strand"] == -1


def test_output_schema_types(tmp_path: Path) -> None:
    f = tmp_path / "b.blast"
    _write(f, [_row()])
    df, _ = parse_and_filter_blast(f, SEQS, DEFAULT)
    for col, dtype in OUTPUT_SCHEMA.items():
        assert df.schema[col] == dtype, f"column {col} has wrong dtype"


def test_comment_lines_skipped(tmp_path: Path) -> None:
    f = tmp_path / "b.blast"
    f.write_text("# header comment\n" + "\t".join(str(x) for x in _row("OG1")) + "\n")
    df, stats = parse_and_filter_blast(f, SEQS, DEFAULT)
    assert df.height == 1
    assert stats.raw_hits == 1


# ------------------------------- Quality filter -----------------------------


def test_quality_filter_pident(tmp_path: Path) -> None:
    f = tmp_path / "b.blast"
    _write(f, [_row(pident=90.0)])
    df, stats = parse_and_filter_blast(f, SEQS, DEFAULT)
    assert df.height == 0
    assert stats.discarded_quality_rows == 1
    assert stats.after_quality == 0


def test_quality_filter_length(tmp_path: Path) -> None:
    f = tmp_path / "b.blast"
    _write(f, [_row(length=50)])
    df, stats = parse_and_filter_blast(f, SEQS, DEFAULT)
    assert df.height == 0
    assert stats.discarded_quality_rows == 1


def test_quality_filter_evalue(tmp_path: Path) -> None:
    f = tmp_path / "b.blast"
    _write(f, [_row(evalue=1e-5)])
    df, stats = parse_and_filter_blast(f, SEQS, DEFAULT)
    assert df.height == 0
    assert stats.discarded_quality_rows == 1


# ------------------------------- Uniqueness ---------------------------------


def test_uniqueness_clear_winner(tmp_path: Path) -> None:
    """Two hits, ratio 400/200 = 2.0 >= 1.5 → keep best, drop secondary."""
    f = tmp_path / "b.blast"
    _write(
        f,
        [
            _row("OG1", "chr1", sstart=100, send=299, bitscore=400.0),
            _row("OG1", "chr2", sstart=500, send=699, bitscore=200.0),
        ],
    )
    df, stats = parse_and_filter_blast(f, SEQS, DEFAULT)
    assert df.height == 1
    row = df.row(0, named=True)
    assert row["seq_name"] == "chr1"
    assert row["start"] == 99
    assert stats.after_uniqueness == 1
    assert stats.discarded_multicopy_scms == 0


def test_uniqueness_ambiguous_discarded(tmp_path: Path) -> None:
    """Two hits, ratio 400/380 ≈ 1.05 < 1.5 → discard SCM entirely."""
    f = tmp_path / "b.blast"
    _write(
        f,
        [
            _row("OG1", "chr1", sstart=100, send=299, bitscore=400.0),
            _row("OG1", "chr2", sstart=500, send=699, bitscore=380.0),
        ],
    )
    df, stats = parse_and_filter_blast(f, SEQS, DEFAULT)
    assert df.height == 0
    assert stats.discarded_multicopy_scms == 1


def test_uniqueness_exact_ratio_boundary_kept(tmp_path: Path) -> None:
    """ratio == threshold → kept (>= comparison)."""
    f = tmp_path / "b.blast"
    _write(
        f,
        [
            _row("OG1", "chr1", sstart=100, send=299, bitscore=300.0),
            _row("OG1", "chr2", sstart=500, send=699, bitscore=200.0),  # 300/200 = 1.5
        ],
    )
    df, stats = parse_and_filter_blast(f, SEQS, DEFAULT)
    assert df.height == 1
    assert stats.discarded_multicopy_scms == 0


def test_uniqueness_zero_ratio_discards_all_multihit(tmp_path: Path) -> None:
    """ratio=0 → discard every multi-hit SCM regardless of bitscore."""
    f = tmp_path / "b.blast"
    _write(
        f,
        [
            _row("OG1", "chr1", sstart=100, send=299, bitscore=1000.0),
            _row("OG1", "chr2", sstart=500, send=699, bitscore=10.0),  # would normally pass ratio
            _row("OG2", "chr1", sstart=800, send=999, bitscore=400.0),  # singleton — survives
        ],
    )
    df, stats = parse_and_filter_blast(f, SEQS, BlastFilterParams(uniqueness_ratio=0.0))
    assert df["scm_id"].to_list() == ["OG2"]
    assert stats.discarded_multicopy_scms == 1


# ------------------------------- Validation ---------------------------------


def test_validation_unknown_seq(tmp_path: Path) -> None:
    f = tmp_path / "b.blast"
    _write(f, [_row(sseqid="chr_unknown")])
    df, stats = parse_and_filter_blast(f, SEQS, DEFAULT)
    assert df.height == 0
    assert stats.after_uniqueness == 1
    assert stats.discarded_validation_scms == 1


def test_validation_out_of_bounds(tmp_path: Path) -> None:
    f = tmp_path / "b.blast"
    _write(f, [_row(sseqid="chr1", sstart=900, send=1099)])  # end 1099 > seq_len 1000
    df, stats = parse_and_filter_blast(f, SEQS, DEFAULT)
    assert df.height == 0
    assert stats.discarded_validation_scms == 1


def test_validation_at_boundary_kept(tmp_path: Path) -> None:
    """A hit ending at exactly seq_length is valid (end is exclusive)."""
    f = tmp_path / "b.blast"
    _write(f, [_row(sseqid="chr1", sstart=901, send=1000, length=100)])
    # Resulting interval: start=900, end=1000, seq_len=1000 → end <= length OK
    df, _ = parse_and_filter_blast(f, SEQS, DEFAULT)
    assert df.height == 1


# ------------------------------- Holistic -----------------------------------


def test_holistic_all_filter_branches(tmp_path: Path) -> None:
    f = tmp_path / "b.blast"
    _write(
        f,
        [
            # OG1 — clean single-copy → kept
            _row("OG1", "chr1", sstart=100, send=299, bitscore=400.0),
            # OG2 — low pident → quality drop
            _row("OG2", "chr1", sstart=400, send=599, pident=80.0, bitscore=300.0),
            # OG3 — ambiguous multi-copy → uniqueness drop
            _row("OG3", "chr1", sstart=600, send=799, bitscore=200.0),
            _row("OG3", "chr2", sstart=100, send=299, bitscore=195.0),
            # OG4 — clear winner among multi-copy → kept
            _row("OG4", "chr2", sstart=400, send=599, bitscore=500.0),
            _row("OG4", "chr1", sstart=800, send=999, bitscore=100.0),  # ratio 5
            # OG5 — unknown seq → validation drop
            _row("OG5", "chr_unknown", sstart=100, send=299, bitscore=400.0),
        ],
    )
    df, stats = parse_and_filter_blast(f, SEQS, DEFAULT)

    assert set(df["scm_id"].to_list()) == {"OG1", "OG4"}
    # OG4 best hit lands on chr2 (bitscore 500 > 100)
    og4 = df.filter(pl.col("scm_id") == "OG4").row(0, named=True)
    assert og4["seq_name"] == "chr2"

    assert stats.raw_hits == 7
    assert stats.after_quality == 6  # OG2 dropped
    # Pre-uniqueness unique SCMs: OG1, OG3, OG4, OG5 = 4
    assert stats.after_uniqueness == 3  # OG3 dropped
    assert stats.discarded_multicopy_scms == 1
    assert stats.after_validation == 2  # OG5 dropped
    assert stats.discarded_validation_scms == 1


def test_empty_file_returns_empty_dataframe(tmp_path: Path) -> None:
    f = tmp_path / "empty.blast"
    f.write_text("")
    df, stats = parse_and_filter_blast(f, SEQS, DEFAULT)
    assert df.height == 0
    assert df.schema == OUTPUT_SCHEMA
    assert stats.raw_hits == 0


def test_all_quality_dropped_returns_empty(tmp_path: Path) -> None:
    f = tmp_path / "b.blast"
    _write(f, [_row(pident=50.0), _row("OG2", pident=60.0)])
    df, stats = parse_and_filter_blast(f, SEQS, DEFAULT)
    assert df.height == 0
    assert stats.raw_hits == 2
    assert stats.after_quality == 0
    assert stats.discarded_quality_rows == 2


# ------------------------------- Integration --------------------------------


@pytest.mark.integration
def test_load_real_pea_blast() -> None:
    """Smoke test against one real pea genome.

    The probe oligos in this dataset are ~45 bp, so we override `min_length=30`.
    See example_data/README.md.
    """
    csv = Path("example_data/genomes.csv")
    if not csv.exists():
        pytest.skip("example_data not linked")
    [entry, *_] = read_manifest(csv)
    seqs = dict(read_fai(entry.fai_path))
    params = BlastFilterParams(min_length=30)
    df, stats = parse_and_filter_blast(entry.blast_path, seqs, params)

    assert stats.raw_hits > 100_000
    assert 50_000 < df.height < 1_500_000
    assert stats.after_validation == df.height
