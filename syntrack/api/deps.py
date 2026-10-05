"""FastAPI dependencies: AppState, and the caller's FISH session key."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Header, Request

if TYPE_CHECKING:
    from syntrack.api.state import AppState

SESSION_HEADER = "X-SynTrack-Session"

DEFAULT_SESSION = "default"
"""Namespace for callers that send no session header — an older frontend, the
CLI, or curl. They share one namespace, which is exactly the pre-session
behaviour, so nothing breaks on upgrade."""

MAX_SESSION_ID_LEN = 128


def get_state(request: Request) -> AppState:
    state: AppState = request.app.state.app_state
    return state


def get_session(
    x_syntrack_session: Annotated[str | None, Header()] = None,
) -> str:
    """Session key for per-session state (design: docs/design/FISH_SESSION_SCOPE.md).

    The value is opaque — a namespace, not a credential: it is never parsed and
    grants nothing beyond seeing that namespace's marker sets. Overlong or
    empty values fall back to the shared default rather than being rejected, so
    a malformed client degrades to the old behaviour instead of failing.
    """
    if x_syntrack_session is None:
        return DEFAULT_SESSION
    candidate = x_syntrack_session.strip()
    if not candidate or len(candidate) > MAX_SESSION_ID_LEN:
        return DEFAULT_SESSION
    return candidate
