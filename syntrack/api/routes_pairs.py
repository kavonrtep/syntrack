"""GET /api/pairs — every unordered genome pair with shared-SCM count + cache status."""

from __future__ import annotations

from itertools import combinations

from fastapi import APIRouter, Depends

from syntrack.api.deps import get_state
from syntrack.api.schemas import PairsResponse, PairSummary
from syntrack.api.state import AppState

router = APIRouter()


@router.get("/pairs", response_model=PairsResponse)
def list_pairs(state: AppState = Depends(get_state)) -> PairsResponse:
    pairs: list[PairSummary] = []
    for g1, g2 in combinations(state.genome_store.ids, 2):
        cached = state.pair_cache.peek(g1, g2)
        pairs.append(
            PairSummary(
                genome1_id=g1,
                genome2_id=g2,
                shared_scm_count=state.scm_store.shared_count(g1, g2),
                derived=cached is not None,
                block_count=len(cached.blocks) if cached is not None else None,
            )
        )
    return PairsResponse(pairs=pairs)
