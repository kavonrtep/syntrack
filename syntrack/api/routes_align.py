"""GET /api/align — map a clicked basepair on one genome to syntenic positions
on every other genome, for vertical-alignment double-click.

Algorithm (per target genome Y):
    1. Take blocks of pair (anchor, Y) filtered to the clicked chromosome.
    2. If any block contains the clicked position, interpolate within it
       (confidence 1.0).
    3. Otherwise pick the K nearest blocks (by g1-distance), weight each by
       ``scm_count / (1 + distance / 1 Mb)``, vote on the target sequence,
       then weighted-average the interpolated position within the winning
       sequence. Handles cases where the clicked region sits between blocks
       that happen to point at different Y chromosomes.
    4. If the clicked chromosome has no blocks at all in the pair, return
       ``seq=null, pos=null``.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Query

from syntrack.api.deps import get_state
from syntrack.api.schemas import (
    AlignmentMappingSchema,
    AlignmentResponse,
    AlignmentSourceSchema,
)
from syntrack.api.state import AppState

if TYPE_CHECKING:
    from syntrack.derive.block import SyntenyBlock

router = APIRouter()


def _block_distance(block: SyntenyBlock, pos: int) -> int:
    if pos < block.g1_start:
        return block.g1_start - pos
    if pos >= block.g1_end:
        return pos - block.g1_end + 1
    return 0


def _interpolate(block: SyntenyBlock, pos: int) -> float:
    """Map ``pos`` to its g2 coordinate inside (or clipped to) ``block``."""
    span = max(1, block.g1_end - block.g1_start)
    if pos <= block.g1_start:
        f = 0.0
    elif pos >= block.g1_end:
        f = 1.0
    else:
        f = (pos - block.g1_start) / span
    g2_span = block.g2_end - block.g2_start
    if block.relative_strand >= 0:
        return block.g2_start + f * g2_span
    return block.g2_end - f * g2_span


def _align_pos(
    blocks: list[SyntenyBlock],
    pos: int,
    k: int,
) -> tuple[int, int, float] | None:
    """Return ``(g2_seq_idx, g2_pos, confidence)`` for the best alignment, or
    ``None`` if ``blocks`` is empty."""
    if not blocks:
        return None

    for b in blocks:
        if b.g1_start <= pos < b.g1_end:
            return (b.g2_seq_idx, round(_interpolate(b, pos)), 1.0)

    by_dist = sorted(blocks, key=lambda b: _block_distance(b, pos))
    top_k = by_dist[:k]

    seq_weights: dict[int, float] = defaultdict(float)
    for b in top_k:
        d = _block_distance(b, pos)
        seq_weights[b.g2_seq_idx] += b.scm_count / (1.0 + d / 1_000_000.0)
    best_seq_idx = max(seq_weights, key=lambda s: seq_weights[s])

    relevant = [b for b in top_k if b.g2_seq_idx == best_seq_idx]
    total_w = 0.0
    total_pos = 0.0
    for b in relevant:
        d = _block_distance(b, pos)
        w = b.scm_count / (1.0 + d / 1_000_000.0)
        total_w += w
        total_pos += w * _interpolate(b, pos)
    final_pos = round(total_pos / total_w)

    # relevant is drawn from by_dist (sorted ascending); its first element is
    # nearest to pos.
    min_dist = _block_distance(relevant[0], pos)
    confidence = 1.0 / (1.0 + min_dist / 1_000_000.0)
    return (best_seq_idx, final_pos, confidence)


@router.get("/align", response_model=AlignmentResponse)
def align(
    genome_id: str = Query(..., description="Anchor genome (the one that stays fixed)."),
    seq: str = Query(..., description="Clicked sequence name on the anchor."),
    pos: int = Query(..., ge=0, description="0-based click position on that sequence."),
    k: int = Query(3, ge=1, le=20, description="Number of nearest blocks to consider."),
    state: AppState = Depends(get_state),
) -> AlignmentResponse:
    if genome_id not in state.genome_store:
        raise HTTPException(404, f"unknown genome: {genome_id!r}")
    source_genome = state.genome_store[genome_id]
    source_seq_names = [s.name for s in source_genome.sequences]
    if seq not in source_seq_names:
        raise HTTPException(404, f"unknown sequence {seq!r} in genome {genome_id!r}")
    source_seq_idx = source_seq_names.index(seq)

    mappings: list[AlignmentMappingSchema] = []
    for target_id in state.scm_store.genome_ids:
        if target_id == genome_id:
            continue
        entry = state.pair_cache.get_or_derive(genome_id, target_id)
        blocks_on_seq = [b for b in entry.blocks if b.g1_seq_idx == source_seq_idx]
        result = _align_pos(blocks_on_seq, pos, k=k)
        if result is None:
            mappings.append(
                AlignmentMappingSchema(genome_id=target_id, seq=None, pos=None, confidence=0.0)
            )
            continue
        seq_idx, target_pos, conf = result
        target_seq_name = state.genome_store[target_id].sequences[seq_idx].name
        mappings.append(
            AlignmentMappingSchema(
                genome_id=target_id,
                seq=target_seq_name,
                pos=target_pos,
                confidence=round(conf, 4),
            )
        )

    return AlignmentResponse(
        source=AlignmentSourceSchema(genome_id=genome_id, seq=seq, pos=pos),
        mappings=mappings,
    )
