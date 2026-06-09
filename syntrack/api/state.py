"""Application state shared across all routes (single-user, single-process)."""

from __future__ import annotations

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
