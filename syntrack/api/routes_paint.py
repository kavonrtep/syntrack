"""GET /api/paint — reference-painted regions for a genome.

For every genome, given a reference, walk the genome's SCMs in positional order
and emit runs where every SCM lands on the same reference sequence (or all are
absent from the reference). This is what makes a non-reference chromosome
visually "composed of multiple colors" (design §5.7): translocations produce
multiple runs per chromosome.

Reference genomes paint trivially (each chromosome is one run that matches
itself); no special-casing required.
"""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query

from syntrack.api.deps import get_state
from syntrack.api.schemas import PaintRegionSchema, PaintResponse
from syntrack.api.state import AppState

router = APIRouter()


@router.get("/paint", response_model=PaintResponse)
def get_paint(
    genome_id: str = Query(..., description="Genome to paint."),
    reference: str = Query(..., description="Reference genome whose palette paints the regions."),
    state: AppState = Depends(get_state),
) -> PaintResponse:
    if genome_id not in state.genome_store:
        raise HTTPException(404, f"unknown genome: {genome_id!r}")
    if reference not in state.genome_store:
        raise HTTPException(404, f"unknown reference: {reference!r}")

    positions = state.scm_store.genome_positions[genome_id]
    ref_seq_map = state.scm_store.reference_seq_map(reference)
    ref_seq_names = [s.name for s in state.genome_store[reference].sequences]
    genome_seq_names = [s.name for s in state.genome_store[genome_id].sequences]

    regions: list[PaintRegionSchema] = []
    n = int(positions.size)
    if n == 0:
        return PaintResponse(genome_id=genome_id, reference=reference, regions=regions)

    # positions is already sorted by global offset. Within one sequence, that
    # means sorted by start. Run-length encode (seq_idx, ref_seq_idx).
    seq_idx = positions["seq_idx"]
    start = positions["start"]
    end = positions["end"]
    scm_idx = positions["scm_id_idx"]
    ref_seq = ref_seq_map[scm_idx]  # -1 where SCM absent from reference

    # boundaries[i] is True iff row i starts a new run (differs from row i-1).
    boundaries = np.ones(n, dtype=bool)
    if n > 1:
        boundaries[1:] = (seq_idx[1:] != seq_idx[:-1]) | (ref_seq[1:] != ref_seq[:-1])
    run_starts = np.flatnonzero(boundaries)
    run_ends = np.append(run_starts[1:], n)

    for rs, re in zip(run_starts.tolist(), run_ends.tolist(), strict=True):
        run_ref = int(ref_seq[rs])
        ref_name: str | None = ref_seq_names[run_ref] if run_ref >= 0 else None
        regions.append(
            PaintRegionSchema(
                seq=genome_seq_names[int(seq_idx[rs])],
                start=int(start[rs]),
                end=int(end[re - 1]),
                reference_seq=ref_name,
                scm_count=re - rs,
            )
        )

    return PaintResponse(genome_id=genome_id, reference=reference, regions=regions)
