"""FISH marker-set endpoints — load, list, and delete custom SCM-ID sets
(design §F4, Phase 3).

A FISH set is a user-supplied list of SCM IDs resolved to positions across
every loaded genome.  Sets are stored in-memory and persist until the server
restarts, the owning session goes idle, or the user deletes them.

Sets are namespaced per browser session (``X-SynTrack-Session``), because one
process serves several users — see ``docs/design/FISH_SESSION_SCOPE.md``. The
store remains a *cache*, not the owner: the browser keeps the SCM IDs of every
set it created and re-asserts them (``replace``) when the server has forgotten
them. Endpoints here consequently report a missing label where they can,
instead of failing a whole request.
"""

from __future__ import annotations

import logging

import numpy as np
from fastapi import APIRouter, Depends, HTTPException

from syntrack.api.deps import get_session, get_state
from syntrack.api.fish_store import (
    FishSetMeta,
    FishSetTooLargeError,
    FishUsage,
    short_sid,
)
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
    FishUsageSchema,
)
from syntrack.api.state import AppState

router = APIRouter()

logger = logging.getLogger("syntrack.fish")


def _not_found(state: AppState, session: str, label: str, op: str) -> HTTPException:
    """404 for a set this session does not hold, carrying *why* — the store
    remembers recent removals, so the message names the cause (eviction, TTL,
    never existed) instead of leaving the next bug report to guess."""
    reason = state.fish.miss_reason(session, label)
    # The requesting session is logged because a miss is often a *mismatch*:
    # the set exists under another key. Without the sid, a store line and a
    # miss line cannot be told apart from a genuine eviction.
    logger.warning("fish: miss op=%s sid=%s label=%r (%s)", op, short_sid(session), label, reason)
    return HTTPException(404, f"FISH set {label!r} not found — {reason}")


def _usage_schema(usage: FishUsage) -> FishUsageSchema:
    return FishUsageSchema(
        session_sets=usage.session_sets,
        max_sets=usage.max_sets,
        session_bytes=usage.session_bytes,
        total_bytes=usage.total_bytes,
        max_bytes=usage.max_bytes,
        sessions=usage.sessions,
    )


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


def _resolve_positions(
    scm_arr: np.ndarray,
    state: AppState,
    limit: int = 5000,
) -> tuple[dict[str, int], list[FishGenomeCoverage]]:
    """Resolve a FISH set (given its universe-index array) to positions across genomes.

    The per-genome ``positions`` feed the on-screen FISH overlay (tick marks).
    They're capped at ``limit`` but **uniformly subsampled** across each genome's
    offset-sorted matches — the same as /highlight — so the overlay spans the
    full karyotype rather than clustering at the left edge, and a saved set
    renders equivalently to the live region highlight it came from.
    """
    if scm_arr.size == 0:
        return {}, []

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

    return genome_coverage, genomes


def _resolve_fish_set(
    req: FishSetRequest,
    scm_arr: np.ndarray,
    state: AppState,
    limit: int = 5000,
) -> FishSetResponse:
    """Build the full response (metadata + capped, subsampled positions).

    Only the metadata half is stored; the positions are rebuilt on demand, so
    the byte budget reflects real occupancy (see ``fish_store``).
    """
    genome_coverage, genomes = _resolve_positions(scm_arr, state, limit)
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
    session: str = Depends(get_session),
) -> FishSetResponse:
    scm_arr = _resolve_indices(req.scm_ids, state)
    result = _resolve_fish_set(req, scm_arr, state)
    meta = FishSetMeta(
        label=req.label,
        color=req.color,
        scm_count=result.scm_count,
        genome_coverage=result.genome_coverage,
    )
    try:
        state.fish.put(session, req.label, meta, scm_arr, replace=req.replace)
    except KeyError as exc:
        raise HTTPException(409, f"FISH set with label {req.label!r} already exists") from exc
    except FishSetTooLargeError as exc:
        raise HTTPException(
            413,
            f"marker set {req.label!r} needs {exc.nbytes} bytes of index, "
            f"over the {exc.limit}-byte budget",
        ) from exc
    result.usage = _usage_schema(state.fish.usage(session))
    return result


@router.get("/fish", response_model=FishListResponse)
def list_fish_sets(
    state: AppState = Depends(get_state),
    session: str = Depends(get_session),
) -> FishListResponse:
    """This session's sets. Another session's sets are not listed — the client
    hydrates its sidebar from here on load, so it must see only its own."""
    sets = [
        FishSetSchema(
            label=fs.label,
            color=fs.color,
            scm_count=fs.scm_count,
            genome_coverage=fs.genome_coverage,
        )
        for fs in state.fish.list_sets(session)
    ]
    return FishListResponse(sets=sets, usage=_usage_schema(state.fish.usage(session)))


@router.delete("/fish/{label}", status_code=204)
def delete_fish_set(
    label: str,
    state: AppState = Depends(get_state),
    session: str = Depends(get_session),
) -> None:
    if not state.fish.delete(session, label):
        raise _not_found(state, session, label, "delete")


@router.post("/fish/density", response_model=FishDensityResponse)
def fish_density(
    req: FishDensityRequest,
    state: AppState = Depends(get_state),
    session: str = Depends(get_session),
) -> FishDensityResponse:
    """Per-genome whole-genome density histograms for FISH sets (exact — every
    SCM counted), for the multi-colour density preview / FISH-like render.

    For each set and genome, the genome's own SCMs that belong to the set are
    histogrammed by genome-global offset into ``bins`` bins over
    ``[0, total_length)``. Nothing is subsampled, so the result is the ground
    truth the on-screen capped view can be checked against.

    Labels this session does not hold come back in ``missing`` rather than
    raising, so one stale label cannot fail the whole preview.
    """
    labels = req.labels if req.labels is not None else state.fish.labels(session)
    sets_out: list[FishDensitySet] = []
    missing: list[str] = []
    for label in labels:
        stored = state.fish.get(session, label)
        if stored is None:
            # A set this session never had, or that a restart / idle eviction
            # removed. The client re-creates it from the SCM IDs it kept.
            missing.append(label)
            continue
        meta, idxs = stored
        genomes_out: dict[str, list[int]] = {}
        max_count = 0
        for genome_id in state.scm_store.genome_ids:
            gpos = state.scm_store.genome_positions[genome_id]
            total_len = state.genome_store[genome_id].total_length
            if idxs.size == 0 or gpos.size == 0 or total_len <= 0:
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
                color=meta.color,
                scm_count=meta.scm_count,
                max_count=max_count,
                genomes=genomes_out,
            )
        )
    if missing:
        logger.warning(
            "fish: density sid=%s missing=%s (%s)",
            short_sid(session),
            missing,
            "; ".join(f"{m}: {state.fish.miss_reason(session, m)}" for m in missing),
        )
    return FishDensityResponse(bins=req.bins, sets=sets_out, missing=missing)


@router.get("/fish/{label}", response_model=FishSetResponse)
def get_fish_set(
    label: str,
    state: AppState = Depends(get_state),
    session: str = Depends(get_session),
) -> FishSetResponse:
    """One stored set, positions included, so a reloaded page can rebuild its
    sidebar and overlay without re-posting the SCM IDs."""
    stored = state.fish.get(session, label)
    if stored is None:
        raise _not_found(state, session, label, "get")
    meta, idxs = stored
    # Positions are not stored (they dwarf the index array), so rebuild them.
    genome_coverage, genomes = _resolve_positions(idxs, state)
    return FishSetResponse(
        label=meta.label,
        color=meta.color,
        scm_count=meta.scm_count,
        genome_coverage=genome_coverage or meta.genome_coverage,
        genomes=genomes,
        usage=_usage_schema(state.fish.usage(session)),
    )


@router.get("/fish/{label}/scms", response_model=FishSetScmsResponse)
def fish_set_scms(
    label: str,
    state: AppState = Depends(get_state),
    session: str = Depends(get_session),
) -> FishSetScmsResponse:
    """Return the FISH set's COMPLETE SCM membership + per-genome presence, for
    saving the set to file. Uses the full stored index set (not the capped
    overlay positions), so the export is complete regardless of set size."""
    stored = state.fish.get(session, label)
    if stored is None:
        raise _not_found(state, session, label, "export")
    _, idxs = stored
    universe = state.scm_store.universe
    if idxs.size == 0:
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
