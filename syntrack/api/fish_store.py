"""Per-session FISH marker-set store (design: docs/design/FISH_SESSION_SCOPE.md).

One ``syntrack serve`` process is shared by several browsers, so marker sets
are namespaced by an opaque session key rather than living in one global dict.
The store keeps only each set's *metadata* and its ``int32`` index array —
roughly 4 bytes per member SCM. It deliberately does not keep the resolved
per-genome positions: those are ~111 MB for a set spanning 20 genomes at the
5000-positions-per-genome cap, which dwarfs the 0.4 MB index and made the byte
budget meaningless. ``GET /api/fish/{label}`` re-resolves them on demand
instead, so the budget below bounds what it says it bounds.

The store is the only mutable state the API owns, and FastAPI dispatches the
synchronous route handlers to a thread pool, so every public method takes the
lock. Callers never touch the inner dicts.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

logger = logging.getLogger("syntrack.fish")

REMOVAL_HISTORY = 256
"""How many recent removals to remember, so a later miss can say *why* a set
is gone instead of just reporting it absent. Cheap: a label and a reason."""


def _sid(session_key: str) -> str:
    """Short form of a session key for logs — enough to correlate a user's
    requests, short enough to read. The key is opaque, not a secret."""
    return session_key[:8]


MAX_FISH_BYTES = 128 * 1024 * 1024
"""Total ``nbytes`` of all stored index arrays, across all sessions."""

MAX_FISH_SETS = 512
"""Sets per session (secondary guard; bytes are authoritative).

Generous on purpose: a working session can involve uploading many previously
exported sets, and evicting the earliest ones mid-session is exactly the
surprise this cap used to cause when it was 64. At ~4 bytes per member SCM the
byte budget binds first for any realistic set size."""

MAX_FISH_SESSIONS = 32
"""Concurrent sessions (secondary guard)."""

FISH_SESSION_TTL_S = 7 * 24 * 3600
"""Sessions idle longer than this are dropped on the next store operation.

Deliberately long: memory is bounded by ``MAX_FISH_BYTES`` already, so the TTL
only sheds abandoned sessions. A short TTL expires the session under a tab
that is still open — the user returns the next morning, and their sets are
gone — which is a worse failure than holding a few megabytes longer."""


@dataclass(slots=True)
class FishSetMeta:
    """What the store keeps about a set besides its index array.

    Everything here is small and fixed-size per set. The positions that feed
    the overlay are NOT kept; they are re-resolved from the indices on demand.
    """

    label: str
    color: str
    scm_count: int
    genome_coverage: dict[str, int]


@dataclass(slots=True)
class FishUsage:
    """Budget snapshot, for the status bar and for capacity logging."""

    session_sets: int
    max_sets: int
    session_bytes: int
    total_bytes: int
    max_bytes: int
    sessions: int


@dataclass(slots=True)
class FishSession:
    """One session's marker sets, in creation order (the eviction order)."""

    sets: dict[str, FishSetMeta] = field(default_factory=dict)
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

    __slots__ = (
        "_lock",
        "_max_bytes",
        "_max_sessions",
        "_max_sets",
        "_removed",
        "_sessions",
        "_ttl_s",
    )

    def __init__(
        self,
        *,
        max_bytes: int = MAX_FISH_BYTES,
        max_sets: int = MAX_FISH_SETS,
        max_sessions: int = MAX_FISH_SESSIONS,
        ttl_s: float = FISH_SESSION_TTL_S,
    ) -> None:
        self._sessions: dict[str, FishSession] = {}
        # (session_key, label, reason, monotonic_ts) for the most recent
        # removals, newest last. Read by ``miss_reason``.
        self._removed: deque[tuple[str, str, str, float]] = deque(maxlen=REMOVAL_HISTORY)
        self._lock = threading.RLock()
        self._max_bytes = max_bytes
        self._max_sets = max_sets
        self._max_sessions = max_sessions
        self._ttl_s = ttl_s

    # ----------------------------- internals ------------------------------

    def _record_removal(self, session_key: str, label: str, reason: str, now: float) -> None:
        """Remember that a set went away, so a later 404 can explain itself."""
        self._removed.append((session_key, label, reason, now))

    def _drop_set(self, session_key: str, session: FishSession, label: str, reason: str) -> None:
        """Remove one set with bookkeeping and a log line. Caller holds the lock."""
        freed = int(session.indices[label].nbytes) if label in session.indices else 0
        session.sets.pop(label, None)
        session.indices.pop(label, None)
        self._record_removal(session_key, label, reason, time.monotonic())
        logger.info(
            "fish: dropped set sid=%s label=%r reason=%s freed=%dB sets_left=%d",
            _sid(session_key),
            label,
            reason,
            freed,
            len(session.sets),
        )

    def _expire(self, now: float) -> None:
        """Drop sessions idle beyond the TTL. Caller holds the lock."""
        stale = [key for key, s in self._sessions.items() if now - s.last_seen > self._ttl_s]
        for key in stale:
            session = self._sessions[key]
            freed = session.nbytes
            idle_s = now - session.last_seen
            for label in list(session.sets):
                self._record_removal(key, label, "session idle > TTL", now)
            del self._sessions[key]
            logger.info(
                "fish: expired session sid=%s (idle %.0fs > ttl %.0fs, %d sets, freed %dB)",
                _sid(key),
                idle_s,
                self._ttl_s,
                len(session.sets),
                freed,
            )

    def _touch(self, key: str, now: float) -> FishSession:
        """Get or create a session and mark it active. Caller holds the lock."""
        session = self._sessions.get(key)
        if session is None:
            while len(self._sessions) >= self._max_sessions:
                self._evict_oldest(exclude=key, reason="session cap")
            session = FishSession()
            self._sessions[key] = session
            logger.info("fish: new session sid=%s (sessions=%d)", _sid(key), len(self._sessions))
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
        session = self._sessions[victim]
        freed = session.nbytes
        now = time.monotonic()
        for label in list(session.sets):
            self._record_removal(victim, label, f"session evicted ({reason})", now)
        del self._sessions[victim]
        logger.info(
            "fish: evicted session sid=%s (%s, %d sets, freed %dB, sessions=%d)",
            _sid(victim),
            reason,
            len(session.sets),
            freed,
            len(self._sessions),
        )
        return True

    # ------------------------------- API ----------------------------------

    def put(
        self,
        session_key: str,
        label: str,
        meta: FishSetMeta,
        indices: np.ndarray,
        *,
        replace: bool,
    ) -> None:
        """Store a set, evicting as needed to stay inside the byte budget.

        Raises:
            KeyError: the label exists and ``replace`` is False.
            FishSetTooLargeError: the set alone exceeds the byte budget.
        """
        req_replace = replace
        needed = int(indices.nbytes)
        if needed > self._max_bytes:
            logger.warning(
                "fish: refused sid=%s label=%r index=%dB over budget=%dB",
                _sid(session_key),
                label,
                needed,
                self._max_bytes,
            )
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
                self._drop_set(
                    session_key, session, next(iter(session.sets)), f"set cap ({self._max_sets})"
                )
            while self._total_bytes() + needed > self._max_bytes:
                if not self._evict_oldest(exclude=session_key, reason="byte cap"):
                    # Only this session is left; shed its own oldest sets.
                    if not session.sets:
                        raise FishSetTooLargeError(needed, self._max_bytes)
                    self._drop_set(
                        session_key, session, next(iter(session.sets)), "byte cap (own session)"
                    )
            session.sets[label] = meta
            session.indices[label] = indices
            logger.info(
                "fish: stored sid=%s label=%r scms=%d index=%dB replace=%s "
                "sets=%d total=%dB sessions=%d",
                _sid(session_key),
                label,
                meta.scm_count,
                needed,
                req_replace,
                len(session.sets),
                self._total_bytes(),
                len(self._sessions),
            )
            total = self._total_bytes()
            if total > self._max_bytes // 2:
                logger.warning(
                    "fish: budget %d%% used (%dB of %dB across %d session(s)) — "
                    "further uploads will evict older sets",
                    round(100 * total / self._max_bytes),
                    total,
                    self._max_bytes,
                    len(self._sessions),
                )

    def miss_reason(self, session_key: str, label: str) -> str:
        """Why ``label`` is not in ``session_key``, in words, for the 404 detail
        and the log line. Makes a user's bug report self-diagnosing instead of
        leaving "not found" to be reconstructed after the fact."""
        with self._lock:
            session = self._sessions.get(session_key)
            recent = [r for r in self._removed if r[0] == session_key and r[1] == label]
            if recent:
                _, _, reason, when = recent[-1]
                ago = time.monotonic() - when
                detail = f"removed {ago:.0f}s ago: {reason}"
            elif session is None:
                detail = "this session holds no sets on this server"
            else:
                detail = "this session never held that label"
            held = len(session.sets) if session else 0
            return (
                f"{detail}; session holds {held} set(s), "
                f"server holds {len(self._sessions)} session(s), {self._total_bytes()}B of indices"
            )

    def usage(self, session_key: str) -> FishUsage:
        """Budget snapshot for this session (and the shared byte total)."""
        with self._lock:
            session = self._sessions.get(session_key)
            return FishUsage(
                session_sets=len(session.sets) if session else 0,
                max_sets=self._max_sets,
                session_bytes=session.nbytes if session else 0,
                total_bytes=self._total_bytes(),
                max_bytes=self._max_bytes,
                sessions=len(self._sessions),
            )

    def get(self, session_key: str, label: str) -> tuple[FishSetMeta, np.ndarray] | None:
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

    def list_sets(self, session_key: str) -> list[FishSetMeta]:
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
            self._drop_set(session_key, session, label, "deleted by user")
            return True

    # Introspection for tests and DEBUG logging.

    def total_bytes(self) -> int:
        with self._lock:
            return self._total_bytes()

    def session_keys(self) -> list[str]:
        with self._lock:
            return list(self._sessions)
