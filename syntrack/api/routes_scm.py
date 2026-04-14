"""GET /api/scm/{scm_id} — universe lookup, useful for tooltips and debugging."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from syntrack.api.deps import get_state
from syntrack.api.schemas import SCMPositionSchema, SCMResponse
from syntrack.api.state import AppState

router = APIRouter()


def _strand_str(strand: int) -> str:
    return "+" if strand > 0 else "-"


@router.get("/scm/{scm_id}", response_model=SCMResponse)
def get_scm(scm_id: str, state: AppState = Depends(get_state)) -> SCMResponse:
    positions = state.scm_store.positions_of_id(scm_id)
    if positions.size == 0:
        raise HTTPException(404, f"SCM not found: {scm_id!r}")

    out: list[SCMPositionSchema] = []
    for p in positions:
        gid = state.scm_store.genome_ids[int(p["genome_idx"])]
        seq = state.genome_store[gid].sequences[int(p["seq_idx"])]
        out.append(
            SCMPositionSchema(
                genome_id=gid,
                seq=seq.name,
                start=int(p["start"]),
                end=int(p["end"]),
                strand=_strand_str(int(p["strand"])),
            )
        )
    return SCMResponse(scm_id=scm_id, present_in=len(out), positions=out)
