"""Tests for syntrack.api.sampling.subsample_indices — the shared cap helper."""

from __future__ import annotations

import numpy as np

from syntrack.api.sampling import subsample_indices


def test_returns_all_when_under_limit() -> None:
    assert np.array_equal(subsample_indices(5, 10), np.arange(5))
    assert np.array_equal(subsample_indices(10, 10), np.arange(10))


def test_limit_zero_is_unlimited() -> None:
    assert np.array_equal(subsample_indices(1000, 0), np.arange(1000))


def test_empty() -> None:
    assert subsample_indices(0, 5).size == 0


def test_subsample_spans_full_range_including_endpoints() -> None:
    # The defining property vs head truncation: first AND last survive.
    idx = subsample_indices(1000, 10)
    assert idx.size <= 10
    assert idx[0] == 0
    assert idx[-1] == 999
    # Strictly increasing and unique.
    assert np.all(np.diff(idx) > 0)


def test_not_head_truncation() -> None:
    # arr[:limit] would be [0,1,2]; uniform sampling must differ and reach the end.
    idx = subsample_indices(100, 3)
    assert not np.array_equal(idx, np.array([0, 1, 2]))
    assert idx[-1] == 99
