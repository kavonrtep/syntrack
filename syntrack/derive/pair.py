"""PairwiseSCM derivation — inner-join two genomes' SCM tables on scm_id_idx."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from syntrack.store.scm import SCMStore

PAIRWISE_DTYPE = np.dtype(
    [
        ("scm_id_idx", np.int32),
        ("g1_seq_idx", np.int16),
        ("g2_seq_idx", np.int16),
        ("g1_start", np.int64),
        ("g1_end", np.int64),
        ("g2_start", np.int64),
        ("g2_end", np.int64),
        ("g1_strand", np.int8),
        ("g2_strand", np.int8),
    ]
)


@dataclass(frozen=True, slots=True)
class PairwiseSCM:
    """All SCMs shared between two genomes, with positions in both.

    ``rows`` is a structured numpy array sorted by ``(g1_seq_idx, g1_start)`` so that
    block-detection can scan in genome-1 spatial order without any further sorting.
    """

    g1_id: str
    g2_id: str
    rows: np.ndarray

    @property
    def n_shared(self) -> int:
        return int(self.rows.size)


def derive_pair(scm: SCMStore, g1_id: str, g2_id: str) -> PairwiseSCM:
    """Inner-join two genomes' SCM tables on ``scm_id_idx`` (design §3.2.2)."""
    if g1_id == g2_id:
        raise ValueError(f"derive_pair requires distinct genomes; got both = {g1_id!r}")

    a = scm.genome_positions[g1_id]
    b = scm.genome_positions[g2_id]

    if a.size == 0 or b.size == 0:
        return PairwiseSCM(g1_id=g1_id, g2_id=g2_id, rows=np.empty(0, dtype=PAIRWISE_DTYPE))

    common, ia, ib = np.intersect1d(
        a["scm_id_idx"],
        b["scm_id_idx"],
        assume_unique=True,
        return_indices=True,
    )

    n = int(common.size)
    rows = np.empty(n, dtype=PAIRWISE_DTYPE)
    if n == 0:
        return PairwiseSCM(g1_id=g1_id, g2_id=g2_id, rows=rows)

    rows["scm_id_idx"] = common
    rows["g1_seq_idx"] = a["seq_idx"][ia]
    rows["g1_start"] = a["start"][ia]
    rows["g1_end"] = a["end"][ia]
    rows["g1_strand"] = a["strand"][ia]
    rows["g2_seq_idx"] = b["seq_idx"][ib]
    rows["g2_start"] = b["start"][ib]
    rows["g2_end"] = b["end"][ib]
    rows["g2_strand"] = b["strand"][ib]

    # Lexsort: primary key = g1_seq_idx, secondary = g1_start (last key is primary).
    order = np.lexsort((rows["g1_start"], rows["g1_seq_idx"]))
    rows = rows[order]

    return PairwiseSCM(g1_id=g1_id, g2_id=g2_id, rows=rows)
