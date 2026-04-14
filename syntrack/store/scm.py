"""SCMStore — per-genome SCM positions plus a global SCM-to-genomes lookup.

Layout:
    * ``universe`` — string table of every distinct SCM ID seen across all genomes.
      Per-row references use ``int32`` indices into this list (D9: SCM IDs are opaque).
    * ``genome_positions[genome_id]`` — numpy structured array, one row per kept SCM
      in that genome, sorted by global ``offset`` for binary-search range queries.
    * Global SCM-to-genomes lookup in CSR layout (`_hits_offsets` + `_hits_flat`):
      :meth:`positions_of` returns the slice of all hits for a given ``scm_id_idx``
      across every genome that contains it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import polars as pl

from syntrack.io.blast import (
    BlastFilterParams,
    FilteringStats,
    parse_and_filter_blast,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from syntrack.io.manifest import GenomeEntry
    from syntrack.store.genome import GenomeStore

GENOME_POS_DTYPE = np.dtype(
    [
        ("scm_id_idx", np.int32),
        ("seq_idx", np.int16),
        ("start", np.int64),
        ("end", np.int64),
        ("strand", np.int8),
        ("offset", np.int64),  # genome-global linear coord (= seq.offset + start)
    ]
)

HITS_DTYPE = np.dtype(
    [
        ("scm_id_idx", np.int32),
        ("genome_idx", np.int16),
        ("seq_idx", np.int16),
        ("start", np.int64),
        ("end", np.int64),
        ("strand", np.int8),
        ("offset", np.int64),
    ]
)


class SCMStore:
    """In-memory SCM index built once at startup."""

    __slots__ = (
        "_genome_store",
        "_hits_flat",
        "_hits_offsets",
        "filtering_stats",
        "genome_id_to_idx",
        "genome_ids",
        "genome_positions",
        "universe",
        "universe_index",
    )

    universe: list[str]
    universe_index: dict[str, int]
    genome_ids: list[str]
    genome_id_to_idx: dict[str, int]
    genome_positions: dict[str, np.ndarray]
    filtering_stats: dict[str, FilteringStats]
    _hits_offsets: np.ndarray
    _hits_flat: np.ndarray
    _genome_store: GenomeStore

    def __init__(
        self,
        *,
        universe: list[str],
        genome_ids: list[str],
        genome_positions: dict[str, np.ndarray],
        filtering_stats: dict[str, FilteringStats],
        hits_offsets: np.ndarray,
        hits_flat: np.ndarray,
        genome_store: GenomeStore,
    ) -> None:
        self.universe = universe
        self.universe_index = {sid: i for i, sid in enumerate(universe)}
        self.genome_ids = genome_ids
        self.genome_id_to_idx = {gid: i for i, gid in enumerate(genome_ids)}
        self.genome_positions = genome_positions
        self.filtering_stats = filtering_stats
        self._hits_offsets = hits_offsets
        self._hits_flat = hits_flat
        self._genome_store = genome_store

    # ------------------------------ Properties ------------------------------

    @property
    def universe_size(self) -> int:
        return len(self.universe)

    def scm_count(self, genome_id: str) -> int:
        """Kept SCM count for ``genome_id`` (after all filters)."""
        return int(self.genome_positions[genome_id].size)

    # ------------------------------ Queries ---------------------------------

    def hits_in_region(
        self,
        genome_id: str,
        seq_name: str,
        start: int,
        end: int,
    ) -> np.ndarray:
        """Return SCMs whose start falls in ``[start, end)`` on ``(genome_id, seq_name)``.

        Coordinates are 0-based half-open and local to the sequence. The returned slice
        is a view into ``genome_positions[genome_id]`` — do not mutate it.
        """
        if start < 0 or end < start:
            raise ValueError(f"invalid region: start={start}, end={end}")
        seq = self._genome_store.get_sequence(genome_id, seq_name)
        arr = self.genome_positions[genome_id]
        global_start = seq.offset + start
        global_end = seq.offset + end
        # Clamp to sequence bounds so we don't bleed into the next sequence.
        global_end = min(global_end, seq.offset + seq.length)
        i0 = int(np.searchsorted(arr["offset"], global_start, side="left"))
        i1 = int(np.searchsorted(arr["offset"], global_end, side="left"))
        return arr[i0:i1]

    def positions_of(self, scm_id_idx: int) -> np.ndarray:
        """Return the CSR slice of all hits across all genomes for the given SCM.

        Rows are :data:`HITS_DTYPE`. Empty array if the SCM is unknown.
        """
        n_scms = self.universe_size
        if not 0 <= scm_id_idx < n_scms:
            return self._hits_flat[0:0]
        return self._hits_flat[self._hits_offsets[scm_id_idx] : self._hits_offsets[scm_id_idx + 1]]

    def positions_of_id(self, scm_id: str) -> np.ndarray:
        """Look up positions by SCM-ID string. Empty array if the SCM is unknown."""
        idx = self.universe_index.get(scm_id)
        if idx is None:
            return self._hits_flat[0:0]
        return self.positions_of(idx)

    def shared_count(self, g1_id: str, g2_id: str) -> int:
        """Number of SCMs present in both genomes (cheap; no pairwise materialization)."""
        a = self.genome_positions[g1_id]["scm_id_idx"]
        b = self.genome_positions[g2_id]["scm_id_idx"]
        return int(np.intersect1d(a, b, assume_unique=True).size)

    def iter_genomes(self) -> Iterator[str]:
        return iter(self.genome_ids)

    # ------------------------------ Loading ---------------------------------

    @classmethod
    def load(
        cls,
        manifest: list[GenomeEntry],
        params: BlastFilterParams,
        genome_store: GenomeStore,
    ) -> SCMStore:
        """Load an SCMStore: parse + filter all BLAST tables, build universe, build CSR lookup."""
        # Step 1 — parse + filter every genome.
        per_genome_dfs: dict[str, pl.DataFrame] = {}
        filtering_stats: dict[str, FilteringStats] = {}
        for entry in manifest:
            genome = genome_store[entry.genome_id]
            seq_lengths = {s.name: s.length for s in genome.sequences}
            df, stats = parse_and_filter_blast(entry.blast_path, seq_lengths, params)
            per_genome_dfs[entry.genome_id] = df
            filtering_stats[entry.genome_id] = stats

        # Step 2 — build the global SCM universe.
        if any(df.height > 0 for df in per_genome_dfs.values()):
            universe_series = (
                pl.concat([df.select("scm_id") for df in per_genome_dfs.values()])
                .unique()
                .sort("scm_id")
            )
            universe: list[str] = universe_series["scm_id"].to_list()
        else:
            universe = []
        universe_index = {sid: i for i, sid in enumerate(universe)}

        genome_ids = [e.genome_id for e in manifest]

        # Step 3 — convert each per-genome DataFrame to a structured numpy array.
        genome_positions: dict[str, np.ndarray] = {}
        for entry in manifest:
            df = per_genome_dfs[entry.genome_id]
            arr = _df_to_genome_positions(
                df,
                universe_index=universe_index,
                genome=genome_store[entry.genome_id],
            )
            genome_positions[entry.genome_id] = arr

        # Step 4 — build CSR-layout global SCM-to-genomes lookup.
        hits_offsets, hits_flat = _build_global_lookup(
            universe_size=len(universe),
            genome_ids=genome_ids,
            genome_positions=genome_positions,
        )

        return cls(
            universe=universe,
            genome_ids=genome_ids,
            genome_positions=genome_positions,
            filtering_stats=filtering_stats,
            hits_offsets=hits_offsets,
            hits_flat=hits_flat,
            genome_store=genome_store,
        )


# ------------------------------ Helpers ------------------------------------


def _df_to_genome_positions(
    df: pl.DataFrame,
    *,
    universe_index: dict[str, int],
    genome: object,  # syntrack.model.Genome — annotated as object to avoid TYPE_CHECKING dance
) -> np.ndarray:
    """Convert a filtered BLAST DataFrame to a structured array sorted by global offset."""
    if df.height == 0:
        return np.empty(0, dtype=GENOME_POS_DTYPE)

    # Build polars-side lookup tables for vectorized index/offset assignment.
    universe_lookup = pl.DataFrame(
        {
            "scm_id": list(universe_index.keys()),
            "scm_id_idx": list(universe_index.values()),
        },
        schema={"scm_id": pl.String, "scm_id_idx": pl.Int32},
    )
    seq_names = [s.name for s in genome.sequences]  # type: ignore[attr-defined]
    seq_lookup = pl.DataFrame(
        {
            "seq_name": seq_names,
            "seq_idx": list(range(len(seq_names))),
            "seq_offset": [s.offset for s in genome.sequences],  # type: ignore[attr-defined]
        },
        schema={"seq_name": pl.String, "seq_idx": pl.Int16, "seq_offset": pl.Int64},
    )

    indexed = (
        df.join(universe_lookup, on="scm_id", how="inner")
        .join(seq_lookup, on="seq_name", how="inner")
        .with_columns((pl.col("seq_offset") + pl.col("start")).alias("global_offset"))
    )

    n = indexed.height
    arr = np.empty(n, dtype=GENOME_POS_DTYPE)
    arr["scm_id_idx"] = indexed["scm_id_idx"].to_numpy()
    arr["seq_idx"] = indexed["seq_idx"].to_numpy()
    arr["start"] = indexed["start"].to_numpy()
    arr["end"] = indexed["end"].to_numpy()
    arr["strand"] = indexed["strand"].to_numpy()
    arr["offset"] = indexed["global_offset"].to_numpy()
    arr.sort(order="offset")
    return arr


def _build_global_lookup(
    *,
    universe_size: int,
    genome_ids: list[str],
    genome_positions: dict[str, np.ndarray],
) -> tuple[np.ndarray, np.ndarray]:
    """Concatenate per-genome arrays and produce the CSR-layout lookup."""
    n_total = sum(int(arr.size) for arr in genome_positions.values())
    hits_flat = np.empty(n_total, dtype=HITS_DTYPE)

    cursor = 0
    for g_idx, gid in enumerate(genome_ids):
        arr = genome_positions[gid]
        n = int(arr.size)
        if n == 0:
            continue
        hits_flat["scm_id_idx"][cursor : cursor + n] = arr["scm_id_idx"]
        hits_flat["genome_idx"][cursor : cursor + n] = g_idx
        hits_flat["seq_idx"][cursor : cursor + n] = arr["seq_idx"]
        hits_flat["start"][cursor : cursor + n] = arr["start"]
        hits_flat["end"][cursor : cursor + n] = arr["end"]
        hits_flat["strand"][cursor : cursor + n] = arr["strand"]
        hits_flat["offset"][cursor : cursor + n] = arr["offset"]
        cursor += n

    # Stable sort so order within an SCM follows genome_ids order — useful for tests.
    hits_flat.sort(order=["scm_id_idx", "genome_idx"], kind="stable")

    # CSR offsets: hits_offsets[i] = first row where scm_id_idx >= i.
    hits_offsets = np.searchsorted(
        hits_flat["scm_id_idx"], np.arange(universe_size + 1, dtype=np.int32)
    ).astype(np.int64)

    return hits_offsets, hits_flat
