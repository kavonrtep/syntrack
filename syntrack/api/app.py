"""FastAPI app factory."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from syntrack import __version__
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

    Environment:
        SYNTRACK_FRONTEND_DIR: if set and the directory exists, the built
            frontend is mounted at ``/`` so one process serves both API and UI.
            Leave unset in dev (Vite serves the UI on ``:5173`` instead).
    """
    app = FastAPI(title="SynTrack", version=__version__)
    app.state.app_state = state

    if dev_cors:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # API routers first so /api/* has priority over the static catch-all below.
    app.include_router(genomes_router, prefix="/api")
    app.include_router(pairs_router, prefix="/api")
    app.include_router(synteny_router, prefix="/api")
    app.include_router(scm_router, prefix="/api")
    app.include_router(paint_router, prefix="/api")
    app.include_router(align_router, prefix="/api")
    app.include_router(highlight_router, prefix="/api")
    app.include_router(config_router, prefix="/api")

    # Simple health endpoint — exposed at the root (not under /api) so it's
    # usable by Compose / Kubernetes probes without tying them to the API prefix.
    # The server doesn't start listening until after SCMStore.load returns, so
    # a 200 here implies "loaded and ready to serve".
    @app.get("/healthz")
    def healthz() -> dict[str, object]:
        return {
            "status": "ok",
            "version": __version__,
            "genomes": len(state.genome_store),
            "universe_size": state.scm_store.universe_size,
        }

    # Static frontend — only mounted when explicitly pointed at. In dev the
    # env var is unset and Vite owns the UI; in the container image the env
    # var is set to /app/frontend/dist.
    frontend_dir_env = os.environ.get("SYNTRACK_FRONTEND_DIR")
    if frontend_dir_env:
        frontend_dir = Path(frontend_dir_env)
        if frontend_dir.is_dir():
            app.mount(
                "/",
                StaticFiles(directory=frontend_dir, html=True),
                name="ui",
            )

    return app
