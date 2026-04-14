"""FastAPI dependency: pull AppState off the application instance."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request

if TYPE_CHECKING:
    from syntrack.api.state import AppState


def get_state(request: Request) -> AppState:
    state: AppState = request.app.state.app_state
    return state
