"""Per-session FISH marker-set store (design: docs/design/FISH_SESSION_SCOPE.md).

One ``syntrack serve`` process is shared by several browsers, so marker sets
are namespaced by an opaque session key rather than living in one global dict.
The store is bounded by *bytes* — an index array is ``int32`` per member SCM,
so set counts understate memory by an order of magnitude — and evicts whole
idle sessions when it does not fit.

The store is the only mutable state the API owns, and FastAPI dispatches the
synchronous route handlers to a thread pool, so every public method takes the
lock. Callers never touch the inner dicts.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

    from syntrack.api.schemas import FishSetResponse

logger = logging.getLogger(__name__)

MAX_FISH_BYTES = 128 * 1024 * 1024
"""Total ``nbytes`` of all stored index arrays, across all sessions."""

MAX_FISH_SETS = 64
"""Sets per session (secondary guard; bytes are authoritative)."""

MAX_FISH_SESSIONS = 32
"""Concurrent sessions (secondary guard)."""

FISH_SESSION_TTL_S = 7 * 24 * 3600
"""Sessions idle longer than this are dropped on the next store operation.

Deliberately long: memory is bounded by ``MAX_FISH_BYTES`` already, so the TTL
only sheds abandoned sessions. A short TTL expires the session under a tab
that is still open — the user returns the next morning, and their sets are
gone — which is a worse failure than holding a few megabytes longer."""


@dataclass(slots=True)
class FishSession:
    """One session's marker sets, in creation order (the eviction order)."""

    sets: dict[str, FishSetResponse] = field(default_factory=dict)
    indices: dict[str, np.ndarray] = field(default_factory=dict)
    last_seen: float = 0.0

    @property
    def nbytes(self) -> int:
        return sum(int(a.nbytes) for a in self.indices.values())


class FishSetTooLargeError(Exception):
    """A single set exceeds the whole byte budget, so no eviction can fit it."""

    def __init__(self, nbytes: int, limit: int) -> None:
        super().__init__(f"marker set needs {nbytes} bytes, limit is {limit}")
        self.nbytes = nbytes
        self.limit = limit


class FishStore:
    """Session-namespaced marker sets with byte-bounded eviction."""

    __slots__ = ("_lock", "_max_bytes", "_max_sessions", "_max_sets", "_sessions", "_ttl_s")

    def __init__(
        self,
        *,
        max_bytes: int = MAX_FISH_BYTES,
        max_sets: int = MAX_FISH_SETS,
        max_sessions: int = MAX_FISH_SESSIONS,
        ttl_s: float = FISH_SESSION_TTL_S,
    ) -> None:
        self._sessions: dict[str, FishSession] = {}
        self._lock = threading.RLock()
        self._max_bytes = max_bytes
        self._max_sets = max_sets
        self._max_sessions = max_sessions
        self._ttl_s = ttl_s

    # ----------------------------- internals ------------------------------

    def _expire(self, now: float) -> None:
        """Drop sessions idle beyond the TTL. Caller holds the lock."""
        stale = [key for key, s in self._sessions.items() if now - s.last_seen > self._ttl_s]
        for key in stale:
            freed = self._sessions[key].nbytes
            del self._sessions[key]
            logger.debug("fish: expired session %s (idle, freed %d bytes)", key, freed)

    def _touch(self, key: str, now: float) -> FishSession:
        """Get or create a session and mark it active. Caller holds the lock."""
        session = self._sessions.get(key)
        if session is None:
            while len(self._sessions) >= self._max_sessions:
                self._evict_oldest(exclude=key, reason="session cap")
            session = FishSession()
            self._sessions[key] = session
            logger.debug("fish: new session %s", key)
        session.last_seen = now
        return session

    def _total_bytes(self) -> int:
        return sum(s.nbytes for s in self._sessions.values())

    def _evict_oldest(self, *, exclude: str, reason: str) -> bool:
        """Drop the least recently active session other than ``exclude``."""
        candidates = [k for k in self._sessions if k != exclude]
        if not candidates:
            return False
        victim = min(candidates, key=lambda k: self._sessions[k].last_seen)
        freed = self._sessions[victim].nbytes
        del self._sessions[victim]
        logger.debug("fish: evicted session %s (%s, freed %d bytes)", victim, reason, freed)
        return True

    # ------------------------------- API ----------------------------------

    def put(
        self,
        session_key: str,
        label: str,
        result: FishSetResponse,
        indices: np.ndarray,
        *,
        replace: bool,
    ) -> None:
        """Store a set, evicting as needed to stay inside the byte budget.

        Raises:
            KeyError: the label exists and ``replace`` is False.
            FishSetTooLargeError: the set alone exceeds the byte budget.
        """
        needed = int(indices.nbytes)
        if needed > self._max_bytes:
            raise FishSetTooLargeError(needed, self._max_bytes)
        now = time.monotonic()
        with self._lock:
            self._expire(now)
            session = self._touch(session_key, now)
            if label in session.sets and not replace:
                raise KeyError(label)
            # Replacing frees the old array first, so re-asserting a set never
            # counts twice against the budget.
            session.sets.pop(label, None)
            session.indices.pop(label, None)
            while len(session.sets) >= self._max_sets:
                oldest = next(iter(session.sets))
                del session.sets[oldest]
                session.indices.pop(oldest, None)
                logger.debug("fish: dropped %s/%s (set cap)", session_key, oldest)
            while self._total_bytes() + needed > self._max_bytes:
                if not self._evict_oldest(exclude=session_key, reason="byte cap"):
                    # Only this session is left; shed its own oldest sets.
                    if not session.sets:
                        raise FishSetTooLargeError(needed, self._max_bytes)
                    oldest = next(iter(session.sets))
                    del session.sets[oldest]
                    session.indices.pop(oldest, None)
                    logger.debug("fish: dropped %s/%s (byte cap)", session_key, oldest)
            session.sets[label] = result
            session.indices[label] = indices

    def get(self, session_key: str, label: str) -> tuple[FishSetResponse, np.ndarray] | None:
        """The set and its index array, read as a pair so they cannot disagree."""
        now = time.monotonic()
        with self._lock:
            self._expire(now)
            session = self._sessions.get(session_key)
            if session is None:
                return None
            session.last_seen = now
            result = session.sets.get(label)
            indices = session.indices.get(label)
            if result is None or indices is None:
                return None
            return result, indices

    def labels(self, session_key: str) -> list[str]:
        now = time.monotonic()
        with self._lock:
            self._expire(now)
            session = self._sessions.get(session_key)
            if session is None:
                return []
            session.last_seen = now
            return list(session.sets)

    def list_sets(self, session_key: str) -> list[FishSetResponse]:
        now = time.monotonic()
        with self._lock:
            self._expire(now)
            session = self._sessions.get(session_key)
            if session is None:
                return []
            session.last_seen = now
            return list(session.sets.values())

    def delete(self, session_key: str, label: str) -> bool:
        """Remove one set. False when this session does not hold that label."""
        now = time.monotonic()
        with self._lock:
            self._expire(now)
            session = self._sessions.get(session_key)
            if session is None or label not in session.sets:
                return False
            session.last_seen = now
            del session.sets[label]
            session.indices.pop(label, None)
            return True

    # Introspection for tests and DEBUG logging.

    def total_bytes(self) -> int:
        with self._lock:
            return self._total_bytes()

    def session_keys(self) -> list[str]:
        with self._lock:
            return list(self._sessions)
