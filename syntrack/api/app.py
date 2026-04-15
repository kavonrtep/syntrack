"""FastAPI app factory."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from syntrack.api.routes_align import router as align_router
from syntrack.api.routes_config import router as config_router
from syntrack.api.routes_genomes import router as genomes_router
from syntrack.api.routes_highlight import router as highlight_router
from syntrack.api.routes_paint import router as paint_router
from syntrack.api.routes_pairs import router as pairs_router
from syntrack.api.routes_scm import router as scm_router
from syntrack.api.routes_synteny import router as synteny_router

if TYPE_CHECKING:
    from syntrack.api.state import AppState


def create_app(state: AppState, *, dev_cors: bool = False) -> FastAPI:
    """Build a FastAPI app bound to a preloaded AppState.

    Args:
        state: loaded GenomeStore + SCMStore + PairCache + Config.
        dev_cors: when True, allow the Vite dev origin (``http://localhost:5173``).
            Off in production (frontend is served as static by FastAPI).
    """
    app = FastAPI(title="SynTrack", version="0.1.0.dev0")
    app.state.app_state = state

    if dev_cors:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(genomes_router, prefix="/api")
    app.include_router(pairs_router, prefix="/api")
    app.include_router(synteny_router, prefix="/api")
    app.include_router(scm_router, prefix="/api")
    app.include_router(paint_router, prefix="/api")
    app.include_router(align_router, prefix="/api")
    app.include_router(highlight_router, prefix="/api")
    app.include_router(config_router, prefix="/api")

    return app
