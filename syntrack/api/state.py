"""Application state shared across all routes (one process, several browsers).

The process was designed for a single local user but is deployed shared, so the
mutable parts — the FISH marker-set store — are guarded by ``fish_lock``.
FastAPI dispatches the synchronous route handlers to a thread pool, so
concurrent requests genuinely run in parallel threads.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

    from syntrack.api.schemas import FishSetResponse
    from syntrack.cache import PairCache
    from syntrack.config import Config
    from syntrack.store.genome import GenomeStore
    from syntrack.store.scm import SCMStore


@dataclass(slots=True)
class AppState:
    """Loaded data + caches owned by the FastAPI app for the duration of a process."""

    config: Config
    genome_store: GenomeStore
    scm_store: SCMStore
    pair_cache: PairCache
    paint_cache: PairCache
    fish_sets: dict[str, FishSetResponse] = field(default_factory=dict)
    # Resolved universe indices per FISH set label — the full membership (the
    # FishSetResponse only carries capped positions). Used by /api/fish/density.
    fish_set_indices: dict[str, np.ndarray] = field(default_factory=dict)
    # Guards the two dicts above. They are read-modify-written (create evicts
    # before inserting) and read in pairs, so both must be held together to
    # keep them consistent under concurrent requests. Same discipline as
    # ``PairCache._lock``.
    fish_lock: threading.RLock = field(default_factory=threading.RLock)
