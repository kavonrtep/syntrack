"""Strict-order collinear block detection (design §3.3).

Blocks are a *rendering data-reduction* primitive (D10): they exist so the canvas
can draw a single ribbon at low zoom instead of N individual SCM lines. They are
not biological synteny calls, so the algorithm is intentionally strict — any
break in strand, sequence, distance, or order closes the current block.
"""

from __future__ import annotations

from dataclasses import dataclass

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


def detect_blocks(pair: PairwiseSCM, params: BlockParams) -> list[SyntenyBlock]:  # noqa: PLR0915
    """Scan a sorted PairwiseSCM and emit strict-order collinear blocks.

    Continuity rules (all must hold to extend a block):
        * **Strand:** ``g1_strand * g2_strand`` matches the block's relative_strand.
        * **Sequence:** same ``g1_seq_idx`` and ``g2_seq_idx`` as the block.
        * **Distance:** g1-gap <= ``max_gap`` AND |g2-gap| <= ``max_gap``.
        * **Order:** g2-position is monotonic (increasing for +strand, decreasing for -).

    Blocks with fewer than ``min_block_size`` SCMs are dropped.

    Complexity: O(n) over the sorted rows.
    """
    rows = pair.rows
    n = int(rows.size)
    if n == 0:
        return []

    blocks: list[SyntenyBlock] = []
    block_id_counter = 0

    # State of the current block.
    cur_first_idx = 0
    cur_g1_seq = int(rows[0]["g1_seq_idx"])
    cur_g2_seq = int(rows[0]["g2_seq_idx"])
    cur_strand = int(rows[0]["g1_strand"]) * int(rows[0]["g2_strand"])
    cur_g1_start = int(rows[0]["g1_start"])
    cur_g1_end = int(rows[0]["g1_end"])
    cur_g2_start = int(rows[0]["g2_start"])
    cur_g2_end = int(rows[0]["g2_end"])
    prev_g1_start = int(rows[0]["g1_start"])
    prev_g2_start = int(rows[0]["g2_start"])

    def _close_block(end_idx_exclusive: int) -> None:
        nonlocal block_id_counter
        size = end_idx_exclusive - cur_first_idx
        if size >= params.min_block_size:
            block_id_counter += 1
            blocks.append(
                SyntenyBlock(
                    block_id=block_id_counter,
                    g1_seq_idx=cur_g1_seq,
                    g1_start=cur_g1_start,
                    g1_end=cur_g1_end,
                    g2_seq_idx=cur_g2_seq,
                    g2_start=cur_g2_start,
                    g2_end=cur_g2_end,
                    relative_strand=cur_strand,
                    scm_count=size,
                )
            )

    for i in range(1, n):
        row = rows[i]
        g1_seq = int(row["g1_seq_idx"])
        g2_seq = int(row["g2_seq_idx"])
        strand = int(row["g1_strand"]) * int(row["g2_strand"])
        g1_start = int(row["g1_start"])
        g1_end = int(row["g1_end"])
        g2_start = int(row["g2_start"])
        g2_end = int(row["g2_end"])

        same_strand = strand == cur_strand
        same_seqs = g1_seq == cur_g1_seq and g2_seq == cur_g2_seq
        within_gap = (g1_start - prev_g1_start) <= params.max_gap and abs(
            g2_start - prev_g2_start
        ) <= params.max_gap
        order_preserved = (cur_strand == 1 and g2_start > prev_g2_start) or (
            cur_strand == -1 and g2_start < prev_g2_start
        )

        if same_strand and same_seqs and within_gap and order_preserved:
            # Extend current block.
            cur_g1_end = max(cur_g1_end, g1_end)
            cur_g2_start = min(cur_g2_start, g2_start)
            cur_g2_end = max(cur_g2_end, g2_end)
        else:
            _close_block(i)
            cur_first_idx = i
            cur_g1_seq = g1_seq
            cur_g2_seq = g2_seq
            cur_strand = strand
            cur_g1_start = g1_start
            cur_g1_end = g1_end
            cur_g2_start = g2_start
            cur_g2_end = g2_end

        prev_g1_start = g1_start
        prev_g2_start = g2_start

    _close_block(n)
    return blocks
