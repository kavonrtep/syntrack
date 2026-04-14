"""GET /api/config + PUT /api/config (block detection only — design §3.3)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from syntrack.api.deps import get_state
from syntrack.api.schemas import (
    BlastFilteringSchema,
    BlockDetectionSchema,
    ConfigResponse,
    ConfigUpdate,
    RenderingDefaultsSchema,
)
from syntrack.api.state import AppState
from syntrack.derive.block import BlockParams

router = APIRouter()


def _serialize(state: AppState) -> ConfigResponse:
    cfg = state.config
    bp = state.pair_cache.block_params  # may have been updated since startup
    return ConfigResponse(
        block_detection=BlockDetectionSchema(max_gap=bp.max_gap, min_block_size=bp.min_block_size),
        blast_filtering=BlastFilteringSchema(
            min_pident=cfg.blast_filtering.min_pident,
            min_length=cfg.blast_filtering.min_length,
            max_evalue=cfg.blast_filtering.max_evalue,
            uniqueness_ratio=cfg.blast_filtering.uniqueness_ratio,
        ),
        rendering_defaults=RenderingDefaultsSchema(
            block_threshold_bp_per_px=cfg.rendering_defaults.block_threshold_bp_per_px,
            max_visible_scms=cfg.rendering_defaults.max_visible_scms,
            connection_opacity=cfg.rendering_defaults.connection_opacity,
            highlight_opacity=cfg.rendering_defaults.highlight_opacity,
            dimmed_opacity=cfg.rendering_defaults.dimmed_opacity,
        ),
    )


@router.get("/config", response_model=ConfigResponse)
def get_config(state: AppState = Depends(get_state)) -> ConfigResponse:
    return _serialize(state)


@router.put("/config", response_model=ConfigResponse)
def update_config(
    update: ConfigUpdate,
    state: AppState = Depends(get_state),
) -> ConfigResponse:
    new_params = BlockParams(
        max_gap=update.block_detection.max_gap,
        min_block_size=update.block_detection.min_block_size,
    )
    state.pair_cache.update_block_params(new_params)
    return _serialize(state)
