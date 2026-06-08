"""GET /api/highlight — map a source region on one genome to the positions
of its SCMs across every other genome (design §4.2 / F3).

Complements double-click alignment: alignment *moves* the other genomes'
viewports so the region ends up as a vertical column, while /highlight
returns raw SCM positions so the frontend can draw per-SCM tick marks on
every track without touching viewports. The two cooperate — you can align
first and then highlight, or highlight while keeping scopes intact.
"""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query

from syntrack.api.deps import get_state
from syntrack.api.regions import parse_region
from syntrack.api.schemas import (
    HighlightPositionSchema,
    HighlightResponse,
    HighlightSourceSchema,
    HighlightTargetSchema,
)
from syntrack.api.state import AppState

router = APIRouter()


def _strand_str(strand: int) -> str:
    return "+" if strand > 0 else "-"


def _subsample_indices(n: int, limit: int) -> np.ndarray:
    """Return up to ``limit`` evenly-spaced indices into ``[0, n)``, in order.

    The caller's arrays are sorted by genome-global offset, so an even sample of
    indices is an even sample in *space*. This is what keeps a capped highlight
    faithful: head truncation (``arr[:limit]``) would cluster every surviving
    tick at the lowest offsets, collapsing the cross-genome signal into a sliver
    at the start of each chromosome. Uniform sampling instead preserves the full
    span of the corresponding region.
    """
    if limit <= 0 or n <= limit:
        return np.arange(n)
    return np.unique(np.linspace(0, n - 1, limit).round().astype(np.int64))


@router.get("/highlight", response_model=HighlightResponse)
def get_highlight(
    genome_id: str = Query(..., description="Source genome that defines the region."),
    region: str = Query(
        ..., description="Region on the source genome as 'seq:start-end' (0-based half-open)."
    ),
    limit: int = Query(
        5000,
        ge=0,
        description="Max positions per target genome (uniformly subsampled across "
        "the region when exceeded, so ticks still span the full span). 0 = unlimited.",
    ),
    state: AppState = Depends(get_state),
) -> HighlightResponse:
    if genome_id not in state.genome_store:
        raise HTTPException(404, f"unknown genome: {genome_id!r}")
    try:
        seq, start, end = parse_region(region)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    source = state.genome_store[genome_id]
    if seq not in {s.name for s in source.sequences}:
        raise HTTPException(404, f"unknown sequence {seq!r} in genome {genome_id!r}")

    hits = state.scm_store.hits_in_region(genome_id, seq, start, end)
    scm_idxs = hits["scm_id_idx"]

    universe = state.scm_store.universe
    source_total = int(scm_idxs.size)
    source_truncated = limit > 0 and source_total > limit
    source_ids_to_emit = scm_idxs[_subsample_indices(source_total, limit)]
    source_scm_ids = [universe[int(i)] for i in source_ids_to_emit]
    source_schema = HighlightSourceSchema(
        genome_id=genome_id,
        seq=seq,
        start=start,
        end=end,
        scm_count=source_total,
        scm_ids=source_scm_ids,
        truncated=source_truncated,
    )

    targets: list[HighlightTargetSchema] = []
    for target_id in state.scm_store.genome_ids:
        if target_id == genome_id:
            continue
        target_positions = state.scm_store.genome_positions[target_id]
        if scm_idxs.size == 0 or target_positions.size == 0:
            targets.append(HighlightTargetSchema(genome_id=target_id, scm_count=0, positions=[]))
            continue
        # Both arrays are already unique per genome (uniqueness filter).
        mask = np.isin(target_positions["scm_id_idx"], scm_idxs, assume_unique=True)
        matching = target_positions[mask]
        if matching.size == 0:
            targets.append(HighlightTargetSchema(genome_id=target_id, scm_count=0, positions=[]))
            continue
        target_genome = state.genome_store[target_id]
        total_count = int(matching.size)
        truncated = limit > 0 and total_count > limit
        to_emit = matching[_subsample_indices(total_count, limit)]
        positions = [
            HighlightPositionSchema(
                scm_id=universe[int(row["scm_id_idx"])],
                seq=target_genome.sequences[int(row["seq_idx"])].name,
                start=int(row["start"]),
                end=int(row["end"]),
                strand=_strand_str(int(row["strand"])),
            )
            for row in to_emit
        ]
        targets.append(
            HighlightTargetSchema(
                genome_id=target_id,
                scm_count=total_count,
                positions=positions,
                truncated=truncated,
            )
        )

    return HighlightResponse(source=source_schema, targets=targets)
