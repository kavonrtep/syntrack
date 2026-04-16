"""GET /api/paint — reference-painted regions for a genome.

Paint regions are the same collinear blocks that ``/api/synteny/blocks``
returns for the pair ``(genome_id, reference)`` — just projected onto
``genome_id``'s coordinate space. Using detect_blocks() here means painting
and the adjacent-pair ribbons use one aggregation rule (the block-detection
params from config), so changing ``max_gap`` / ``min_block_size`` live via
``PUT /api/config`` re-draws bars and ribbons in lockstep.

The reference-vs-reference case is trivial: one region per sequence
spanning its full length, with that sequence itself as ``reference_seq``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from syntrack.api.deps import get_state
from syntrack.api.schemas import PaintRegionSchema, PaintResponse
from syntrack.api.state import AppState

router = APIRouter()


def _trivial_self_paint(state: AppState, genome_id: str) -> list[PaintRegionSchema]:
    genome = state.genome_store[genome_id]
    scm_store = state.scm_store
    regions: list[PaintRegionSchema] = []
    # Count SCMs per sequence so the frontend can still show density info.
    per_seq_count = [0] * len(genome.sequences)
    for row in scm_store.genome_positions[genome_id]:
        per_seq_count[int(row["seq_idx"])] += 1
    for seq_idx, seq in enumerate(genome.sequences):
        regions.append(
            PaintRegionSchema(
                seq=seq.name,
                start=0,
                end=seq.length,
                reference_seq=seq.name,
                scm_count=per_seq_count[seq_idx],
            )
        )
    return regions


@router.get("/paint", response_model=PaintResponse)
def get_paint(
    genome_id: str = Query(..., description="Genome to paint."),
    reference: str = Query(..., description="Reference genome whose palette drives the colours."),
    state: AppState = Depends(get_state),
) -> PaintResponse:
    if genome_id not in state.genome_store:
        raise HTTPException(404, f"unknown genome: {genome_id!r}")
    if reference not in state.genome_store:
        raise HTTPException(404, f"unknown reference: {reference!r}")

    if genome_id == reference:
        return PaintResponse(
            genome_id=genome_id,
            reference=reference,
            regions=_trivial_self_paint(state, genome_id),
        )

    # Paint = blocks of pair (genome_id, reference), projected onto genome_id.
    # The pair cache reuses the same BlockParams as adjacent-pair ribbons, so
    # updating block_detection via PUT /api/config updates both in lockstep.
    entry = state.pair_cache.get_or_derive(genome_id, reference)

    ref_seq_names = [s.name for s in state.genome_store[reference].sequences]
    genome_seq_names = [s.name for s in state.genome_store[genome_id].sequences]

    regions = [
        PaintRegionSchema(
            seq=genome_seq_names[b.g1_seq_idx],
            start=b.g1_start,
            end=b.g1_end,
            reference_seq=ref_seq_names[b.g2_seq_idx],
            scm_count=b.scm_count,
        )
        for b in entry.blocks
    ]
    return PaintResponse(genome_id=genome_id, reference=reference, regions=regions)
