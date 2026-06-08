"""On-disk ``.npz`` backing store for derived pairs (D12 / design §3.5).

A precompute step (``syntrack precompute``) derives pairs once and writes them
to a cache directory; ``serve`` then loads a pair from disk on an in-memory LRU
miss instead of re-deriving it (~100 ms load vs ~540 ms derive at 1M SCMs).

Layout (``cache_dir``)::

    pair_manifest.json        # dataset hash, params, dtypes, pair index
    pair_00000.npz            # one per ordered (g1, g2): arrays "scms" + "blocks"
    pair_00001.npz
    ...

Validity is two-level so block-param tuning never throws away the expensive
join:

* **dataset hash** — input file (size, mtime), blast-filtering params, code
  version, and the pair dtype. Gates the ``scms`` (PairwiseSCM) array. A
  mismatch disables the whole disk store (it predates the current inputs/code).
* **block params + block dtype** — gate the ``blocks`` array. If these differ
  but the dataset hash still matches, the pair is loaded from disk and blocks
  are recomputed with the current params (cheap, vectorized).
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from syntrack import __version__
from syntrack.derive.block import BlockParams, SyntenyBlock, detect_blocks
from syntrack.derive.pair import PAIRWISE_DTYPE, PairwiseSCM, derive_pair

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence
    from pathlib import Path

    from syntrack.io.blast import BlastFilterParams
    from syntrack.io.manifest import GenomeEntry
    from syntrack.store.scm import SCMStore

logger = logging.getLogger("syntrack.diskcache")

MANIFEST_NAME = "pair_manifest.json"

# Structured array form of SyntenyBlock for .npz persistence. All-int fields;
# row-range indices fit int32 (n_shared per pair is ~1M << 2^31).
BLOCK_DTYPE = np.dtype(
    [
        ("block_id", np.int32),
        ("g1_seq_idx", np.int16),
        ("g1_start", np.int32),
        ("g1_end", np.int32),
        ("g2_seq_idx", np.int16),
        ("g2_start", np.int32),
        ("g2_end", np.int32),
        ("relative_strand", np.int8),
        ("scm_count", np.int32),
        ("scm_row_start", np.int32),
        ("scm_row_end", np.int32),
    ]
)


# ------------------------------ Block (de)serialization --------------------


def blocks_to_array(blocks: Sequence[SyntenyBlock]) -> np.ndarray:
    arr = np.empty(len(blocks), dtype=BLOCK_DTYPE)
    for i, b in enumerate(blocks):
        arr[i] = (
            b.block_id,
            b.g1_seq_idx,
            b.g1_start,
            b.g1_end,
            b.g2_seq_idx,
            b.g2_start,
            b.g2_end,
            b.relative_strand,
            b.scm_count,
            b.scm_row_start,
            b.scm_row_end,
        )
    return arr


def array_to_blocks(arr: np.ndarray) -> tuple[SyntenyBlock, ...]:
    return tuple(
        SyntenyBlock(
            block_id=int(r["block_id"]),
            g1_seq_idx=int(r["g1_seq_idx"]),
            g1_start=int(r["g1_start"]),
            g1_end=int(r["g1_end"]),
            g2_seq_idx=int(r["g2_seq_idx"]),
            g2_start=int(r["g2_start"]),
            g2_end=int(r["g2_end"]),
            relative_strand=int(r["relative_strand"]),
            scm_count=int(r["scm_count"]),
            scm_row_start=int(r["scm_row_start"]),
            scm_row_end=int(r["scm_row_end"]),
        )
        for r in arr
    )


# ------------------------------ Hashing / metadata -------------------------


def _dtype_descr(dt: np.dtype) -> str:
    return json.dumps(dt.descr, sort_keys=True)


def _blast_params_dict(p: BlastFilterParams) -> dict[str, float]:
    return {
        "min_pident": p.min_pident,
        "min_length": p.min_length,
        "max_evalue": p.max_evalue,
        "uniqueness_ratio": p.uniqueness_ratio,
    }


def _block_params_dict(p: BlockParams) -> dict[str, int]:
    return {"max_gap": p.max_gap, "min_block_size": p.min_block_size}


def dataset_hash(manifest: Iterable[GenomeEntry], blast_params: BlastFilterParams) -> str:
    """Hash the inputs that make a derived ``scms`` array valid.

    Covers each genome's fai/blast file (size + mtime_ns), the blast-filtering
    params, the code version, and the pair dtype — so swapping inputs, retuning
    filters, upgrading the code, or narrowing the dtype all invalidate the cache.
    """
    h = hashlib.sha256()
    h.update(__version__.encode())
    h.update(_dtype_descr(PAIRWISE_DTYPE).encode())
    h.update(json.dumps(_blast_params_dict(blast_params), sort_keys=True).encode())
    for entry in sorted(manifest, key=lambda e: e.genome_id):
        h.update(entry.genome_id.encode())
        for path in (entry.fai_path, entry.blast_path):
            st = path.stat()
            h.update(f"{path.name}:{st.st_size}:{st.st_mtime_ns}".encode())
    return h.hexdigest()


# ------------------------------ Read side ----------------------------------


@dataclass(frozen=True, slots=True)
class LoadedPair:
    """A pair reconstituted from disk: the PairwiseSCM plus its blocks."""

    pair: PairwiseSCM
    blocks: tuple[SyntenyBlock, ...]


class DiskPairStore:
    """Read-only view over a validated cache directory.

    Construct via :meth:`open`, which validates the manifest's dataset hash and
    returns ``None`` when the cache is absent or stale (so the caller silently
    falls back to deriving).
    """

    __slots__ = ("_blocks_valid", "_dir", "_index")

    def __init__(
        self, cache_dir: Path, index: dict[tuple[str, str], str], blocks_valid: bool
    ) -> None:
        self._dir = cache_dir
        self._index = index
        self._blocks_valid = blocks_valid

    @classmethod
    def open(
        cls,
        cache_dir: Path,
        *,
        manifest: Iterable[GenomeEntry],
        blast_params: BlastFilterParams,
        block_params: BlockParams,
    ) -> DiskPairStore | None:
        manifest_path = cache_dir / MANIFEST_NAME
        if not manifest_path.is_file():
            return None
        try:
            data = json.loads(manifest_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("disk pair cache: unreadable manifest (%s); ignoring", exc)
            return None

        current = dataset_hash(manifest, blast_params)
        if data.get("dataset_hash") != current:
            logger.warning(
                "disk pair cache at %s is stale (inputs/params/code changed); ignoring. "
                "Re-run `syntrack precompute` to refresh it.",
                cache_dir,
            )
            return None

        blocks_valid = data.get("block_params") == _block_params_dict(block_params) and data.get(
            "block_dtype"
        ) == _dtype_descr(BLOCK_DTYPE)
        if not blocks_valid:
            logger.info(
                "disk pair cache: block params differ from precompute; pairs will load "
                "from disk but blocks are recomputed."
            )
        index = {(p["g1"], p["g2"]): p["file"] for p in data.get("pairs", [])}
        logger.info("disk pair cache: %d pairs available at %s", len(index), cache_dir)
        return cls(cache_dir, index, blocks_valid)

    def __contains__(self, key: tuple[str, str]) -> bool:
        return key in self._index

    def __len__(self) -> int:
        return len(self._index)

    def load(self, g1_id: str, g2_id: str, block_params: BlockParams) -> LoadedPair | None:
        """Load a pair from disk, or ``None`` if it isn't in the cache.

        Blocks come from disk when the precompute's block params match; otherwise
        they're recomputed from the loaded PairwiseSCM with the current params.
        """
        file = self._index.get((g1_id, g2_id))
        if file is None:
            return None
        path = self._dir / file
        try:
            with np.load(path) as npz:
                scms = np.ascontiguousarray(npz["scms"])
                block_arr = npz["blocks"] if self._blocks_valid and "blocks" in npz else None
                block_arr = None if block_arr is None else np.ascontiguousarray(block_arr)
        except (OSError, KeyError, ValueError) as exc:
            logger.warning("disk pair cache: failed to load %s (%s); deriving instead", file, exc)
            return None

        pair = PairwiseSCM(g1_id=g1_id, g2_id=g2_id, rows=scms)
        if block_arr is not None:
            blocks = array_to_blocks(block_arr)
        else:
            blocks = tuple(detect_blocks(pair, block_params))
        return LoadedPair(pair=pair, blocks=blocks)


# ------------------------------ Write side ---------------------------------


def write_cache(
    cache_dir: Path,
    scm_store: SCMStore,
    pairs: Sequence[tuple[str, str]],
    *,
    blast_params: BlastFilterParams,
    block_params: BlockParams,
    manifest: Iterable[GenomeEntry],
    progress: Callable[[int, int, str, str, int], None] | None = None,
) -> dict[str, object]:
    """Derive each ordered pair and write ``scms`` + ``blocks`` arrays plus a manifest.

    Returns the written manifest dict. ``progress`` is an optional
    ``callable(i, total, g1, g2, n_shared)`` invoked after each pair.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    total = len(pairs)
    records: list[dict[str, object]] = []
    for i, (g1, g2) in enumerate(pairs):
        pair = derive_pair(scm_store, g1, g2)
        blocks = detect_blocks(pair, block_params)
        file = f"pair_{i:05d}.npz"
        np.savez(cache_dir / file, scms=pair.rows, blocks=blocks_to_array(blocks))
        records.append(
            {
                "g1": g1,
                "g2": g2,
                "file": file,
                "n_shared": pair.n_shared,
                "n_blocks": len(blocks),
            }
        )
        if progress is not None:
            progress(i, total, g1, g2, pair.n_shared)

    manifest_dict: dict[str, object] = {
        "version": __version__,
        "dataset_hash": dataset_hash(manifest, blast_params),
        "blast_filtering": _blast_params_dict(blast_params),
        "block_params": _block_params_dict(block_params),
        "block_dtype": _dtype_descr(BLOCK_DTYPE),
        "pair_dtype": _dtype_descr(PAIRWISE_DTYPE),
        "pairs": records,
    }
    (cache_dir / MANIFEST_NAME).write_text(json.dumps(manifest_dict, indent=2))
    return manifest_dict
