"""Uniform subsampling for capped API responses.

Invariant: a cap on returned positions must SUBSAMPLE across the (offset-sorted)
region, never head-truncate (``arr[:limit]``). Head truncation clusters every
surviving item at the lowest offsets — the left edge of each chromosome —
collapsing the cross-genome signal. Used by both /highlight and the FISH
marker-set overlay so the two render equivalent positions.
"""

from __future__ import annotations

import numpy as np


def subsample_indices(n: int, limit: int) -> np.ndarray:
    """Return up to ``limit`` evenly-spaced indices into ``[0, n)``, in order.

    Because the caller's arrays are sorted by genome-global offset, an even
    sample of indices is an even sample in *space* (it preserves the full span,
    including the first and last item). ``limit <= 0`` means unlimited.
    """
    if limit <= 0 or n <= limit:
        return np.arange(n)
    return np.unique(np.linspace(0, n - 1, limit).round().astype(np.int64))
