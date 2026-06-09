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
from syntrack.api.sampling import subsample_indices
from syntrack.api.schemas import (
    FishDensityRequest,
    FishDensityResponse,
    FishDensitySet,
    FishGenomeCoverage,
    FishListResponse,
    FishPositionSchema,
    FishSetRequest,
    FishSetResponse,
    FishSetSchema,
    FishSetScmsResponse,
)
from syntrack.api.state import AppState

router = APIRouter()


def _strand_str(strand: int) -> str:
    return "+" if strand > 0 else "-"


def _resolve_indices(scm_ids: list[str], state: AppState) -> np.ndarray:
    """Map SCM-ID strings to a sorted, unique ``int32`` array of universe indices.

    Unknown IDs are silently skipped. Uniqueness is required by the
    ``assume_unique=True`` membership tests downstream.
    """
    idxs = [idx for sid in scm_ids if (idx := state.scm_store.universe_index.get(sid)) is not None]
    if not idxs:
        return np.empty(0, dtype=np.int32)
    return np.unique(np.array(idxs, dtype=np.int32))


def _resolve_fish_set(
    req: FishSetRequest,
    scm_arr: np.ndarray,
    state: AppState,
    limit: int = 5000,
) -> FishSetResponse:
    """Resolve a FISH set (given its universe-index array) to positions across genomes.

    The per-genome ``positions`` feed the on-screen FISH overlay (tick marks).
    They're capped at ``limit`` but **uniformly subsampled** across each genome's
    offset-sorted matches — the same as /highlight — so the overlay spans the
    full karyotype rather than clustering at the left edge, and a saved set
    renders equivalently to the live region highlight it came from.
    """
    if scm_arr.size == 0:
        return FishSetResponse(
            label=req.label,
            color=req.color,
            scm_count=0,
            genome_coverage={},
            genomes=[],
        )

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
        to_emit = matching[subsample_indices(total_count, limit)]
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
    scm_arr = _resolve_indices(req.scm_ids, state)
    result = _resolve_fish_set(req, scm_arr, state)
    state.fish_sets[req.label] = result
    state.fish_set_indices[req.label] = scm_arr
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
    state.fish_set_indices.pop(label, None)


@router.post("/fish/density", response_model=FishDensityResponse)
def fish_density(
    req: FishDensityRequest,
    state: AppState = Depends(get_state),
) -> FishDensityResponse:
    """Per-genome whole-genome density histograms for FISH sets (exact — every
    SCM counted), for the multi-colour density preview / FISH-like render.

    For each set and genome, the genome's own SCMs that belong to the set are
    histogrammed by genome-global offset into ``bins`` bins over
    ``[0, total_length)``. Nothing is subsampled, so the result is the ground
    truth the on-screen capped view can be checked against.
    """
    labels = req.labels if req.labels is not None else list(state.fish_sets.keys())
    sets_out: list[FishDensitySet] = []
    for label in labels:
        fs = state.fish_sets.get(label)
        if fs is None:
            raise HTTPException(404, f"FISH set {label!r} not found")
        idxs = state.fish_set_indices.get(label)
        genomes_out: dict[str, list[int]] = {}
        max_count = 0
        for genome_id in state.scm_store.genome_ids:
            gpos = state.scm_store.genome_positions[genome_id]
            total_len = state.genome_store[genome_id].total_length
            if idxs is None or idxs.size == 0 or gpos.size == 0 or total_len <= 0:
                genomes_out[genome_id] = [0] * req.bins
                continue
            mask = np.isin(gpos["scm_id_idx"], idxs, assume_unique=True)
            offsets = gpos["offset"][mask]
            counts, _ = np.histogram(offsets, bins=req.bins, range=(0, total_len))
            max_count = max(max_count, int(counts.max(initial=0)))
            genomes_out[genome_id] = counts.astype(np.int64).tolist()
        sets_out.append(
            FishDensitySet(
                label=label,
                color=fs.color,
                scm_count=fs.scm_count,
                max_count=max_count,
                genomes=genomes_out,
            )
        )
    return FishDensityResponse(bins=req.bins, sets=sets_out)


@router.get("/fish/{label}/scms", response_model=FishSetScmsResponse)
def fish_set_scms(
    label: str,
    state: AppState = Depends(get_state),
) -> FishSetScmsResponse:
    """Return the FISH set's COMPLETE SCM membership + per-genome presence, for
    saving the set to file. Uses the full stored index set (not the capped
    overlay positions), so the export is complete regardless of set size."""
    if label not in state.fish_sets:
        raise HTTPException(404, f"FISH set {label!r} not found")
    idxs = state.fish_set_indices.get(label)
    universe = state.scm_store.universe
    if idxs is None or idxs.size == 0:
        return FishSetScmsResponse(label=label, scm_ids=[], presence={})

    scm_ids = [universe[int(i)] for i in idxs]
    presence: dict[str, str] = {}
    for genome_id in state.scm_store.genome_ids:
        gpos = state.scm_store.genome_positions[genome_id]
        if gpos.size == 0:
            presence[genome_id] = "0" * int(idxs.size)
            continue
        mask = np.isin(idxs, gpos["scm_id_idx"], assume_unique=True)
        presence[genome_id] = "".join(np.where(mask, "1", "0"))
    return FishSetScmsResponse(label=label, scm_ids=scm_ids, presence=presence)
