"""LRU cache of derived ``(PairwiseSCM, blocks)`` keyed by ``(g1_id, g2_id)``.

v0.1 is in-memory only (D16). On-disk ``.npz`` persistence and self-invalidating
manifest hashing (D12) land in v0.2 along with the precompute CLI.

Block re-parameterization preserves the underlying ``PairwiseSCM`` and only
re-runs :func:`detect_blocks` (design §3.3).
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from syntrack.derive.block import BlockParams, SyntenyBlock, detect_blocks
from syntrack.derive.pair import PairwiseSCM, derive_pair

if TYPE_CHECKING:
    from collections.abc import Iterator

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

    __slots__ = ("_block_params", "_cache", "_cap", "_scm")

    def __init__(
        self,
        scm_store: SCMStore,
        block_params: BlockParams,
        max_pairs: int = 30,
    ) -> None:
        if max_pairs <= 0:
            raise ValueError(f"max_pairs must be positive, got {max_pairs}")
        self._scm = scm_store
        self._cap = max_pairs
        self._block_params = block_params
        self._cache: OrderedDict[tuple[str, str], CacheEntry] = OrderedDict()

    # ------------------------------ Properties ------------------------------

    @property
    def block_params(self) -> BlockParams:
        return self._block_params

    @property
    def capacity(self) -> int:
        return self._cap

    def __len__(self) -> int:
        return len(self._cache)

    def __contains__(self, key: tuple[str, str]) -> bool:
        return key in self._cache

    def __iter__(self) -> Iterator[tuple[str, str]]:
        return iter(self._cache)

    # ------------------------------ Access ----------------------------------

    def get_or_derive(self, g1_id: str, g2_id: str) -> CacheEntry:
        """Return the cached entry for ``(g1_id, g2_id)``, deriving on miss."""
        key = (g1_id, g2_id)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached

        pair = derive_pair(self._scm, g1_id, g2_id)
        blocks = tuple(detect_blocks(pair, self._block_params))
        entry = CacheEntry(pair=pair, blocks=blocks)
        self._cache[key] = entry
        self._evict_if_full()
        return entry

    def peek(self, g1_id: str, g2_id: str) -> CacheEntry | None:
        """Return the cached entry without recording an access (no LRU bump, no derive)."""
        return self._cache.get((g1_id, g2_id))

    # ------------------------------ Mutation --------------------------------

    def update_block_params(self, new_params: BlockParams) -> int:
        """Replace block_params and re-detect blocks for every cached pair.

        Returns the number of cached entries whose blocks were recomputed.
        Underlying ``PairwiseSCM`` data is retained — only the block list changes.
        """
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
        self._cache.clear()

    # ------------------------------ Internals -------------------------------

    def _evict_if_full(self) -> None:
        while len(self._cache) > self._cap:
            self._cache.popitem(last=False)
