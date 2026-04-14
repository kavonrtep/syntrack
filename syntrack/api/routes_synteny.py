"""Synteny routes: blocks (LOD-low) and individual SCM lines (LOD-high)."""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query

from syntrack.api.deps import get_state
from syntrack.api.regions import parse_region
from syntrack.api.schemas import (
    BlocksResponse,
    PairwiseSCMSchema,
    SCMsResponse,
    SyntenyBlockSchema,
)
from syntrack.api.state import AppState
from syntrack.derive.block import SyntenyBlock
from syntrack.model import Genome

router = APIRouter()


def _strand_str(strand: int) -> str:
    return "+" if strand > 0 else "-"


def _validate_pair(state: AppState, g1: str, g2: str) -> None:
    if g1 == g2:
        raise HTTPException(400, f"g1 and g2 must differ, got both = {g1!r}")
    if g1 not in state.genome_store:
        raise HTTPException(404, f"unknown genome: {g1!r}")
    if g2 not in state.genome_store:
        raise HTTPException(404, f"unknown genome: {g2!r}")


def _resolve_region(genome: Genome, region: str) -> tuple[str, int, int]:
    try:
        seq, start, end = parse_region(region)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if seq not in {s.name for s in genome.sequences}:
        raise HTTPException(404, f"unknown sequence {seq!r} in genome {genome.id!r}")
    return seq, start, end


def _block_intersects_g1(b: SyntenyBlock, target_seq_idx: int, start: int, end: int) -> bool:
    return b.g1_seq_idx == target_seq_idx and not (b.g1_end <= start or b.g1_start >= end)


def _block_intersects_g2(b: SyntenyBlock, target_seq_idx: int, start: int, end: int) -> bool:
    return b.g2_seq_idx == target_seq_idx and not (b.g2_end <= start or b.g2_start >= end)


@router.get("/synteny/blocks", response_model=BlocksResponse)
def get_blocks(
    g1: str = Query(...),
    g2: str = Query(...),
    region_g1: str | None = Query(None),
    region_g2: str | None = Query(None),
    min_scm: int | None = Query(None, ge=1),
    state: AppState = Depends(get_state),
) -> BlocksResponse:
    """Return collinear blocks for (g1, g2). Triggers derivation on cache miss."""
    _validate_pair(state, g1, g2)
    entry = state.pair_cache.get_or_derive(g1, g2)

    g1_obj = state.genome_store[g1]
    g2_obj = state.genome_store[g2]
    g1_seq_names = [s.name for s in g1_obj.sequences]
    g2_seq_names = [s.name for s in g2_obj.sequences]

    blocks: tuple[SyntenyBlock, ...] = entry.blocks

    if region_g1 is not None:
        seq, start, end = _resolve_region(g1_obj, region_g1)
        seq_idx = g1_seq_names.index(seq)
        blocks = tuple(b for b in blocks if _block_intersects_g1(b, seq_idx, start, end))

    if region_g2 is not None:
        seq, start, end = _resolve_region(g2_obj, region_g2)
        seq_idx = g2_seq_names.index(seq)
        blocks = tuple(b for b in blocks if _block_intersects_g2(b, seq_idx, start, end))

    if min_scm is not None:
        blocks = tuple(b for b in blocks if b.scm_count >= min_scm)

    return BlocksResponse(
        pair=(g1, g2),
        shared_scm_count=entry.pair.n_shared,
        block_count=len(blocks),
        blocks=[
            SyntenyBlockSchema(
                block_id=b.block_id,
                g1_seq=g1_seq_names[b.g1_seq_idx],
                g1_start=b.g1_start,
                g1_end=b.g1_end,
                g2_seq=g2_seq_names[b.g2_seq_idx],
                g2_start=b.g2_start,
                g2_end=b.g2_end,
                strand=_strand_str(b.relative_strand),
                scm_count=b.scm_count,
            )
            for b in blocks
        ],
    )


def _downsample(rows: np.ndarray, limit: int) -> tuple[np.ndarray, bool]:
    if rows.size <= limit:
        return rows, False
    step = rows.size / limit
    indices = (np.arange(limit) * step).astype(np.int64)
    return rows[indices], True


@router.get("/synteny/scms", response_model=SCMsResponse)
def get_scms(
    g1: str = Query(...),
    g2: str = Query(...),
    region_g1: str | None = Query(None),
    region_g2: str | None = Query(None),
    limit: int = Query(5000, ge=1, le=100_000),
    state: AppState = Depends(get_state),
) -> SCMsResponse:
    """Return SCM-level pairwise rows. Used for LOD-high (zoomed-in) rendering."""
    _validate_pair(state, g1, g2)
    entry = state.pair_cache.get_or_derive(g1, g2)
    rows = entry.pair.rows

    g1_obj = state.genome_store[g1]
    g2_obj = state.genome_store[g2]
    g1_seq_names = [s.name for s in g1_obj.sequences]
    g2_seq_names = [s.name for s in g2_obj.sequences]

    if region_g1 is not None:
        seq, start, end = _resolve_region(g1_obj, region_g1)
        seq_idx = g1_seq_names.index(seq)
        mask = (rows["g1_seq_idx"] == seq_idx) & (rows["g1_start"] < end) & (rows["g1_end"] > start)
        rows = rows[mask]

    if region_g2 is not None:
        seq, start, end = _resolve_region(g2_obj, region_g2)
        seq_idx = g2_seq_names.index(seq)
        mask = (rows["g2_seq_idx"] == seq_idx) & (rows["g2_start"] < end) & (rows["g2_end"] > start)
        rows = rows[mask]

    total_in_region = int(rows.size)
    rows_out, downsampled = _downsample(rows, limit)

    universe = state.scm_store.universe
    return SCMsResponse(
        pair=(g1, g2),
        total_in_region=total_in_region,
        returned=int(rows_out.size),
        downsampled=downsampled,
        scms=[
            PairwiseSCMSchema(
                scm_id=universe[int(row["scm_id_idx"])],
                g1_seq=g1_seq_names[int(row["g1_seq_idx"])],
                g1_start=int(row["g1_start"]),
                g1_end=int(row["g1_end"]),
                g2_seq=g2_seq_names[int(row["g2_seq_idx"])],
                g2_start=int(row["g2_start"]),
                g2_end=int(row["g2_end"]),
                strand=_strand_str(int(row["g1_strand"]) * int(row["g2_strand"])),
            )
            for row in rows_out
        ],
    )
