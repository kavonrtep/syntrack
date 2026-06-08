"""FISH marker-set endpoints — load, list, and delete custom SCM-ID sets
(design §F4, Phase 3).

A FISH set is a user-supplied list of SCM IDs resolved to positions across
every loaded genome.  Sets are stored in-memory on ``AppState`` and persist
until the server restarts or the user explicitly deletes them.
"""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, Depends, HTTPException

from syntrack.api.deps import get_state
from syntrack.api.schemas import (
    FishGenomeCoverage,
    FishListResponse,
    FishPositionSchema,
    FishSetRequest,
    FishSetResponse,
    FishSetSchema,
)
from syntrack.api.state import AppState

router = APIRouter()


def _strand_str(strand: int) -> str:
    return "+" if strand > 0 else "-"


def _resolve_fish_set(
    req: FishSetRequest,
    state: AppState,
    limit: int = 500,
) -> FishSetResponse:
    """Resolve SCM IDs to positions across all genomes."""
    # Map requested SCM IDs to universe indices, silently skipping unknowns.
    scm_idxs: list[int] = []
    for sid in req.scm_ids:
        idx = state.scm_store.universe_index.get(sid)
        if idx is not None:
            scm_idxs.append(idx)

    if not scm_idxs:
        return FishSetResponse(
            label=req.label,
            color=req.color,
            scm_count=0,
            genome_coverage={},
            genomes=[],
        )

    scm_arr = np.array(scm_idxs, dtype=np.int32)
    universe = state.scm_store.universe
    genome_coverage: dict[str, int] = {}
    genomes: list[FishGenomeCoverage] = []

    for genome_id in state.scm_store.genome_ids:
        gpos = state.scm_store.genome_positions[genome_id]
        if gpos.size == 0:
            genome_coverage[genome_id] = 0
            genomes.append(FishGenomeCoverage(genome_id=genome_id, scm_count=0, positions=[]))
            continue

        mask = np.isin(gpos["scm_id_idx"], scm_arr, assume_unique=True)
        matching = gpos[mask]
        if matching.size == 0:
            genome_coverage[genome_id] = 0
            genomes.append(FishGenomeCoverage(genome_id=genome_id, scm_count=0, positions=[]))
            continue

        genome = state.genome_store[genome_id]
        total_count = int(matching.size)
        truncated = limit > 0 and total_count > limit
        to_emit = matching[:limit] if truncated else matching
        positions = [
            FishPositionSchema(
                scm_id=universe[int(row["scm_id_idx"])],
                seq=genome.sequences[int(row["seq_idx"])].name,
                start=int(row["start"]),
                end=int(row["end"]),
                strand=_strand_str(int(row["strand"])),
            )
            for row in to_emit
        ]
        genome_coverage[genome_id] = total_count
        genomes.append(
            FishGenomeCoverage(
                genome_id=genome_id,
                scm_count=total_count,
                positions=positions,
                truncated=truncated,
            )
        )

    return FishSetResponse(
        label=req.label,
        color=req.color,
        scm_count=int(scm_arr.size),
        genome_coverage=genome_coverage,
        genomes=genomes,
    )


@router.post("/fish", response_model=FishSetResponse, status_code=201)
def create_fish_set(
    req: FishSetRequest,
    state: AppState = Depends(get_state),
) -> FishSetResponse:
    if req.label in state.fish_sets:
        raise HTTPException(409, f"FISH set with label {req.label!r} already exists")
    result = _resolve_fish_set(req, state)
    state.fish_sets[req.label] = result
    return result


@router.get("/fish", response_model=FishListResponse)
def list_fish_sets(
    state: AppState = Depends(get_state),
) -> FishListResponse:
    sets = [
        FishSetSchema(
            label=fs.label,
            color=fs.color,
            scm_count=fs.scm_count,
            genome_coverage=fs.genome_coverage,
        )
        for fs in state.fish_sets.values()
    ]
    return FishListResponse(sets=sets)


@router.delete("/fish/{label}", status_code=204)
def delete_fish_set(
    label: str,
    state: AppState = Depends(get_state),
) -> None:
    if label not in state.fish_sets:
        raise HTTPException(404, f"FISH set {label!r} not found")
    del state.fish_sets[label]
