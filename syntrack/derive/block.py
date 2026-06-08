"""Strict-order collinear block detection (design §3.3).

Blocks are a *rendering data-reduction* primitive (D10): they exist so the canvas
can draw a single ribbon at low zoom instead of N individual SCM lines. They are
not biological synteny calls, so the algorithm is intentionally strict — any
break in strand, sequence, distance, or order closes the current block.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from syntrack.derive.pair import PairwiseSCM


@dataclass(frozen=True, slots=True)
class BlockParams:
    """Block-detection knobs. Defaults per IMPLEMENTATION_PLAN D10."""

    max_gap: int = 300_000
    min_block_size: int = 3


@dataclass(frozen=True, slots=True)
class SyntenyBlock:
    """One collinear run of SCMs between two sequences (one per genome).

    Coordinates are 0-based half-open and local to their respective sequences.
    ``relative_strand`` is +1 for parallel ribbons, -1 for crossed ribbons.
    ``scm_row_start``/``scm_row_end`` index into the parent :class:`PairwiseSCM`'s
    ``rows`` (half-open) so downstream code can look the block's SCMs up — used
    e.g. by the reference-color API layer.
    """

    block_id: int
    g1_seq_idx: int
    g1_start: int
    g1_end: int
    g2_seq_idx: int
    g2_start: int
    g2_end: int
    relative_strand: int
    scm_count: int
    scm_row_start: int
    scm_row_end: int


def detect_blocks(pair: PairwiseSCM, params: BlockParams) -> list[SyntenyBlock]:
    """Scan a sorted PairwiseSCM and emit strict-order collinear blocks.

    Continuity rules (all must hold to extend a block):
        * **Strand:** ``g1_strand * g2_strand`` matches the block's relative_strand.
        * **Sequence:** same ``g1_seq_idx`` and ``g2_seq_idx`` as the block.
        * **Distance:** g1-gap <= ``max_gap`` AND |g2-gap| <= ``max_gap``.
        * **Order:** g2-position is monotonic (increasing for +strand, decreasing for -).

    Blocks with fewer than ``min_block_size`` SCMs are dropped.

    Vectorized: every continuity rule is a property of two *adjacent* rows (within
    a block, strand and sequence are constant, so "matches the block anchor" and
    "matches the previous row" coincide). We compute a per-adjacency break mask,
    derive segment boundaries from it, reduce each segment's bounds with numpy
    ufunc ``reduceat``, and only materialize Python objects for blocks that pass
    the ``min_block_size`` filter. O(n) work, but in C rather than per-row Python.
    """
    rows = pair.rows
    n = int(rows.size)
    if n == 0:
        return []

    g1_seq = rows["g1_seq_idx"]
    g2_seq = rows["g2_seq_idx"]
    g1_start = rows["g1_start"]
    g1_end = rows["g1_end"]
    g2_start = rows["g2_start"]
    g2_end = rows["g2_end"]
    # int16 product avoids int8 overflow and keeps the comparison cheap.
    strand = rows["g1_strand"].astype(np.int16) * rows["g2_strand"].astype(np.int16)

    if n == 1:
        seg_start = np.array([0], dtype=np.intp)
    else:
        left_strand = strand[:-1]
        g2_prev = g2_start[:-1]
        g2_next = g2_start[1:]
        same_strand = strand[1:] == left_strand
        same_seq = (g1_seq[1:] == g1_seq[:-1]) & (g2_seq[1:] == g2_seq[:-1])
        within_gap = ((g1_start[1:] - g1_start[:-1]) <= params.max_gap) & (
            np.abs(g2_next - g2_prev) <= params.max_gap
        )
        # Order direction follows the left row's strand (constant within a block).
        order_ok = ((left_strand == 1) & (g2_next > g2_prev)) | (
            (left_strand == -1) & (g2_next < g2_prev)
        )
        breaks = ~(same_strand & same_seq & within_gap & order_ok)
        # A break between rows j and j+1 opens a new segment at j+1.
        seg_start = np.empty(int(np.count_nonzero(breaks)) + 1, dtype=np.intp)
        seg_start[0] = 0
        seg_start[1:] = np.flatnonzero(breaks) + 1

    seg_end = np.empty_like(seg_start)
    seg_end[:-1] = seg_start[1:]
    seg_end[-1] = n
    seg_count = seg_end - seg_start

    keep = seg_count >= params.min_block_size
    if not keep.any():
        return []

    # Per-segment bound reductions over the full segmentation (cheap; one C pass
    # each). Anchors (g1_start, seq, strand) come from each segment's first row,
    # which is the minimum within the block because rows are g1-sorted.
    g1_end_max = np.maximum.reduceat(g1_end, seg_start)
    g2_start_min = np.minimum.reduceat(g2_start, seg_start)
    g2_end_max = np.maximum.reduceat(g2_end, seg_start)

    blocks: list[SyntenyBlock] = []
    for block_id, seg in enumerate(np.flatnonzero(keep), start=1):
        s = int(seg_start[seg])
        blocks.append(
            SyntenyBlock(
                block_id=block_id,
                g1_seq_idx=int(g1_seq[s]),
                g1_start=int(g1_start[s]),
                g1_end=int(g1_end_max[seg]),
                g2_seq_idx=int(g2_seq[s]),
                g2_start=int(g2_start_min[seg]),
                g2_end=int(g2_end_max[seg]),
                relative_strand=int(strand[s]),
                scm_count=int(seg_count[seg]),
                scm_row_start=s,
                scm_row_end=int(seg_end[seg]),
            )
        )
    return blocks
