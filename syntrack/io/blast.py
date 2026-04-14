"""BLAST -outfmt 6 parser with quality, uniqueness, and validation filters (design §3.2.1).

Coordinate convention: BLAST sstart/send are 1-based, inclusive. The output uses 0-based
half-open intervals (``start``, ``end``); strand is inferred from sstart/send ordering and
coordinates are normalized so ``start < end``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import polars as pl

# Standard BLAST -outfmt 6 column names (in order).
BLAST_COLUMNS: tuple[str, ...] = (
    "qseqid",
    "sseqid",
    "pident",
    "length",
    "mismatch",
    "gapopen",
    "qstart",
    "qend",
    "sstart",
    "send",
    "evalue",
    "bitscore",
)

_BLAST_DTYPES: dict[str, type[pl.DataType]] = {
    "qseqid": pl.String,
    "sseqid": pl.String,
    "pident": pl.Float64,
    "length": pl.Int64,
    "mismatch": pl.Int64,
    "gapopen": pl.Int64,
    "qstart": pl.Int64,
    "qend": pl.Int64,
    "sstart": pl.Int64,
    "send": pl.Int64,
    "evalue": pl.Float64,
    "bitscore": pl.Float64,
}

OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "scm_id": pl.String,
    "seq_name": pl.String,
    "start": pl.Int64,
    "end": pl.Int64,
    "strand": pl.Int8,
}


@dataclass(frozen=True, slots=True)
class BlastFilterParams:
    """Filter knobs applied at load time. Mirrors :class:`syntrack.config.BlastFiltering`."""

    min_pident: float = 95.0
    min_length: int = 100
    max_evalue: float = 1.0e-10
    uniqueness_ratio: float = 1.5
    """Best-vs-second-best bitscore ratio required to retain a multi-hit SCM.
    A value of ``0`` means: discard every SCM that has more than one passing hit."""


@dataclass(frozen=True, slots=True)
class FilteringStats:
    """Per-genome filtering report (design §3.2.1)."""

    raw_hits: int
    """Raw row count in the BLAST file."""
    after_quality: int
    """Row count after pident/length/evalue filter."""
    after_uniqueness: int
    """Distinct SCM (qseqid) count after the uniqueness filter — one row per SCM."""
    after_validation: int
    """SCM count after coord/seq-name validation against the FAI."""
    discarded_quality_rows: int
    """Rows dropped by the quality filter."""
    discarded_multicopy_scms: int
    """SCMs dropped because best/second-best bitscore ratio was below threshold."""
    discarded_validation_scms: int
    """SCMs dropped because their seq_name was unknown or coords out of bounds."""


def _empty_output() -> pl.DataFrame:
    return pl.DataFrame(schema=OUTPUT_SCHEMA)


def parse_and_filter_blast(
    path: Path,
    seq_lengths: dict[str, int],
    params: BlastFilterParams,
) -> tuple[pl.DataFrame, FilteringStats]:
    """Read a BLAST -outfmt 6 file and apply quality + uniqueness + validation filters.

    Args:
        path: BLAST hits file (one hit per row, tab-separated, no header).
        seq_lengths: mapping of valid sequence names to their lengths (from FAI).
        params: filter thresholds.

    Returns:
        Tuple of:
            * polars DataFrame with one row per kept SCM. Columns:
              ``scm_id`` (str), ``seq_name`` (str), ``start`` (i64, 0-based inclusive),
              ``end`` (i64, 0-based exclusive), ``strand`` (i8, ±1).
            * :class:`FilteringStats` with per-stage counts.
    """
    if path.stat().st_size == 0:
        zero_stats = FilteringStats(0, 0, 0, 0, 0, 0, 0)
        return _empty_output(), zero_stats

    df = pl.read_csv(
        path,
        separator="\t",
        has_header=False,
        new_columns=list(BLAST_COLUMNS),
        schema_overrides=_BLAST_DTYPES,
        comment_prefix="#",
    )
    raw_hits = df.height

    # Quality filter
    q = df.filter(
        (pl.col("pident") >= params.min_pident)
        & (pl.col("length") >= params.min_length)
        & (pl.col("evalue") <= params.max_evalue)
    )
    after_quality = q.height
    discarded_quality_rows = raw_hits - after_quality

    if after_quality == 0:
        return _empty_output(), FilteringStats(
            raw_hits=raw_hits,
            after_quality=0,
            after_uniqueness=0,
            after_validation=0,
            discarded_quality_rows=discarded_quality_rows,
            discarded_multicopy_scms=0,
            discarded_validation_scms=0,
        )

    # Strand inference + canonical 0-based half-open interval.
    q = q.with_columns(
        pl.when(pl.col("sstart") < pl.col("send"))
        .then(pl.lit(1, dtype=pl.Int8))
        .otherwise(pl.lit(-1, dtype=pl.Int8))
        .alias("strand"),
        (pl.min_horizontal("sstart", "send") - 1).alias("start"),
        pl.max_horizontal("sstart", "send").alias("end"),
    )

    # Uniqueness: rank within qseqid by bitscore desc; pull best and second-best.
    rank_best = 1
    rank_second = 2
    q = q.with_columns(
        pl.col("bitscore").rank(method="ordinal", descending=True).over("qseqid").alias("_rk"),
        pl.len().over("qseqid").alias("_n_hits"),
    )
    best = q.filter(pl.col("_rk") == rank_best)
    second_bs = q.filter(pl.col("_rk") == rank_second).select(
        pl.col("qseqid"),
        pl.col("bitscore").alias("_second_bs"),
    )
    best = best.join(second_bs, on="qseqid", how="left").with_columns(
        pl.col("_second_bs").fill_null(0.0)
    )

    pre_uniqueness_scms = best.height
    if params.uniqueness_ratio <= 0:
        kept = best.filter(pl.col("_n_hits") == 1)
    else:
        kept = best.filter(
            (pl.col("_n_hits") == 1)
            | (pl.col("bitscore") >= pl.col("_second_bs") * params.uniqueness_ratio)
        )
    after_uniqueness = kept.height
    discarded_multicopy_scms = pre_uniqueness_scms - after_uniqueness

    if after_uniqueness == 0:
        return _empty_output(), FilteringStats(
            raw_hits=raw_hits,
            after_quality=after_quality,
            after_uniqueness=0,
            after_validation=0,
            discarded_quality_rows=discarded_quality_rows,
            discarded_multicopy_scms=discarded_multicopy_scms,
            discarded_validation_scms=0,
        )

    # Validation against FAI: known seq_name + start/end within bounds.
    seq_lengths_df = pl.DataFrame(
        {
            "sseqid": list(seq_lengths.keys()),
            "_seq_len": list(seq_lengths.values()),
        },
        schema={"sseqid": pl.String, "_seq_len": pl.Int64},
    )
    valid = (
        kept.join(seq_lengths_df, on="sseqid", how="inner")
        .filter((pl.col("start") >= 0) & (pl.col("end") <= pl.col("_seq_len")))
        .drop("_seq_len")
    )
    after_validation = valid.height
    discarded_validation_scms = after_uniqueness - after_validation

    output = valid.select(
        pl.col("qseqid").alias("scm_id"),
        pl.col("sseqid").alias("seq_name"),
        pl.col("start"),
        pl.col("end"),
        pl.col("strand"),
    )

    stats = FilteringStats(
        raw_hits=raw_hits,
        after_quality=after_quality,
        after_uniqueness=after_uniqueness,
        after_validation=after_validation,
        discarded_quality_rows=discarded_quality_rows,
        discarded_multicopy_scms=discarded_multicopy_scms,
        discarded_validation_scms=discarded_validation_scms,
    )
    return output, stats
