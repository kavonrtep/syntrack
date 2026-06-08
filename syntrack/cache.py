"""LRU cache of derived ``(PairwiseSCM, blocks)`` keyed by ``(g1_id, g2_id)``.

v0.1 is in-memory only (D16). On-disk ``.npz`` persistence and self-invalidating
manifest hashing (D12) land in v0.2 along with the precompute CLI.

Block re-parameterization preserves the underlying ``PairwiseSCM`` and only
re-runs :func:`detect_blocks` (design §3.3).
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from syntrack.derive.block import BlockParams, SyntenyBlock, detect_blocks
from syntrack.derive.pair import PairwiseSCM, derive_pair
from syntrack.perf import timed

if TYPE_CHECKING:
    from collections.abc import Iterator

    from syntrack.diskcache import DiskPairStore
    from syntrack.store.scm import SCMStore


@dataclass(frozen=True, slots=True)
class CacheEntry:
    pair: PairwiseSCM
    blocks: tuple[SyntenyBlock, ...]


class PairCache:
    """LRU cache of derived pairs.

    Cache keys are ordered ``(g1_id, g2_id)`` tuples — ``("A", "B")`` and
    ``("B", "A")`` are distinct entries (the rows are sorted by g1, so the same
    underlying data with swapped roles needs a separate derivation).
    """

    __slots__ = ("_block_params", "_cache", "_cap", "_derive_locks", "_disk", "_lock", "_scm")

    def __init__(
        self,
        scm_store: SCMStore,
        block_params: BlockParams,
        max_pairs: int = 30,
        disk_store: DiskPairStore | None = None,
    ) -> None:
        if max_pairs <= 0:
            raise ValueError(f"max_pairs must be positive, got {max_pairs}")
        self._scm = scm_store
        self._cap = max_pairs
        self._block_params = block_params
        # Optional on-disk backing populated by `syntrack precompute`; consulted
        # on an in-memory miss before deriving.
        self._disk = disk_store
        self._cache: OrderedDict[tuple[str, str], CacheEntry] = OrderedDict()
        # Global lock protects _cache, _block_params, and _derive_locks.
        self._lock = threading.RLock()
        # Per-key locks for single-flight derivation (managed under _lock).
        self._derive_locks: dict[tuple[str, str], threading.Lock] = {}

    # ------------------------------ Properties ------------------------------

    @property
    def block_params(self) -> BlockParams:
        with self._lock:
            return self._block_params

    @property
    def capacity(self) -> int:
        return self._cap

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)

    def __contains__(self, key: tuple[str, str]) -> bool:
        with self._lock:
            return key in self._cache

    def __iter__(self) -> Iterator[tuple[str, str]]:
        with self._lock:
            return iter(list(self._cache))

    # ------------------------------ Access ----------------------------------

    def get_or_derive(self, g1_id: str, g2_id: str) -> CacheEntry:
        """Return the cached entry for ``(g1_id, g2_id)``, deriving on miss.

        Thread-safe: concurrent requests for the same key share a single
        in-progress derivation. The expensive derivation runs outside the
        cache lock; the result is inserted under the lock with a re-check.
        """
        key = (g1_id, g2_id)
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                return cached
            derive_lock = self._derive_locks.setdefault(key, threading.Lock())

        # Derivation runs outside _lock so other keys can proceed.
        with derive_lock:
            # Re-check under derive_lock: another thread may have finished.
            with self._lock:
                cached = self._cache.get(key)
                if cached is not None:
                    self._cache.move_to_end(key)
                    return cached
                bp = self._block_params

            entry = self._load_or_derive(g1_id, g2_id, bp)

            with self._lock:
                self._cache[key] = entry
                self._evict_if_full()
            return entry

    def _load_or_derive(self, g1_id: str, g2_id: str, bp: BlockParams) -> CacheEntry:
        """Load the pair from the on-disk cache if present, else derive it."""
        if self._disk is not None:
            with timed("disk_load_pair", pair=f"{g1_id}->{g2_id}"):
                loaded = self._disk.load(g1_id, g2_id, bp)
            if loaded is not None:
                return CacheEntry(pair=loaded.pair, blocks=loaded.blocks)

        with timed("derive_pair", pair=f"{g1_id}->{g2_id}"):
            pair = derive_pair(self._scm, g1_id, g2_id)
        with timed("detect_blocks", pair=f"{g1_id}->{g2_id}", n=pair.n_shared):
            blocks = tuple(detect_blocks(pair, bp))
        return CacheEntry(pair=pair, blocks=blocks)

    def peek(self, g1_id: str, g2_id: str) -> CacheEntry | None:
        """Return the cached entry without recording an access (no LRU bump, no derive)."""
        with self._lock:
            return self._cache.get((g1_id, g2_id))

    # ------------------------------ Mutation --------------------------------

    def update_block_params(self, new_params: BlockParams) -> int:
        """Replace block_params and re-detect blocks for every cached pair.

        Returns the number of cached entries whose blocks were recomputed.
        Underlying ``PairwiseSCM`` data is retained — only the block list changes.
        """
        with self._lock:
            if new_params == self._block_params:
                return 0
            self._block_params = new_params
            recomputed = 0
            for key, entry in list(self._cache.items()):
                self._cache[key] = CacheEntry(
                    pair=entry.pair,
                    blocks=tuple(detect_blocks(entry.pair, new_params)),
                )
                recomputed += 1
            return recomputed

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    # ------------------------------ Internals -------------------------------

    def _evict_if_full(self) -> None:
        # Caller must hold _lock.
        while len(self._cache) > self._cap:
            self._cache.popitem(last=False)
