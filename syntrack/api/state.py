"""Application state shared across all routes (single-user, single-process)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
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
