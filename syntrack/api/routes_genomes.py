"""GET /api/genomes — genome metadata + per-genome filtering stats."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from syntrack.api.deps import get_state
from syntrack.api.schemas import (
    FilteringStatsSchema,
    GenomeSchema,
    GenomesResponse,
    SequenceSchema,
)
from syntrack.api.state import AppState

router = APIRouter()


@router.get("/genomes", response_model=GenomesResponse)
def list_genomes(state: AppState = Depends(get_state)) -> GenomesResponse:
    out: list[GenomeSchema] = []
    for genome in state.genome_store:
        stats = state.scm_store.filtering_stats[genome.id]
        out.append(
            GenomeSchema(
                id=genome.id,
                label=genome.label,
                total_length=genome.total_length,
                scm_count=state.scm_store.scm_count(genome.id),
                sequences=[
                    SequenceSchema(name=s.name, length=s.length, offset=s.offset, color=s.color)
                    for s in genome.sequences
                ],
                filtering=FilteringStatsSchema(
                    raw_hits=stats.raw_hits,
                    after_quality=stats.after_quality,
                    after_uniqueness=stats.after_uniqueness,
                    after_validation=stats.after_validation,
                    discarded_quality_rows=stats.discarded_quality_rows,
                    discarded_multicopy_scms=stats.discarded_multicopy_scms,
                    discarded_validation_scms=stats.discarded_validation_scms,
                ),
            )
        )
    return GenomesResponse(genomes=out, scm_universe_size=state.scm_store.universe_size)
