"""Application state shared across all routes (one process, several browsers).

The process was designed for a single local user but is deployed shared, so
the only mutable part — the FISH marker-set store — is namespaced per browser
session and guards itself (see ``syntrack.api.fish_store``). FastAPI
dispatches the synchronous route handlers to a thread pool, so concurrent
requests genuinely run in parallel threads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from syntrack.api.fish_store import FishStore

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
    paint_cache: PairCache
    # Marker sets, namespaced per browser session. Holds both the response
    # (capped positions, for the overlay) and the full index array (complete
    # membership, for density and export), and bounds itself by bytes.
    fish: FishStore = field(default_factory=FishStore)
