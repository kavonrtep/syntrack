"""Tests for /api/highlight — cross-genome region highlight.

Fixture recap (see tests/api/conftest.py):
    A: chr1=10000, OG01..OG10 at [100, 1000) forward-strand.
    B: chr1=10000, OG01..OG08 at same positions + OG11, OG12 at [900, 1100).
    C: chr1=10000, OG05..OG14 reverse-strand at C positions [4900, 4000).

0-based half-open coord convention. hits_in_region includes SCMs whose
start is inside [region_start, region_end).
"""

from fastapi.testclient import TestClient


def _target(body: dict, gid: str) -> dict:
    for t in body["targets"]:
        if t["genome_id"] == gid:
            return t
    raise AssertionError(f"no target for {gid!r}: {body!r}")


def test_highlight_finds_shared_scms(client: TestClient) -> None:
    # A.chr1:[400, 700) catches OG05 (start=499), OG06 (599), OG07 (699) — 3 SCMs.
    body = client.get(
        "/api/highlight",
        params={"genome_id": "A", "region": "chr1:400-700"},
    ).json()
    src = body["source"]
    assert src["genome_id"] == "A"
    assert src["seq"] == "chr1"
    assert src["start"] == 400
    assert src["end"] == 700
    assert src["scm_count"] == 3
    assert set(src["scm_ids"]) == {"OG05", "OG06", "OG07"}

    b = _target(body, "B")
    assert b["scm_count"] == 3
    assert {p["scm_id"] for p in b["positions"]} == {"OG05", "OG06", "OG07"}
    for p in b["positions"]:
        assert p["seq"] == "chr1"
        assert p["strand"] == "+"

    c = _target(body, "C")
    assert c["scm_count"] == 3
    # Reverse-strand hits on C
    for p in c["positions"]:
        assert p["seq"] == "chr1"
        assert p["strand"] == "-"


def test_highlight_source_excluded_from_targets(client: TestClient) -> None:
    body = client.get(
        "/api/highlight",
        params={"genome_id": "A", "region": "chr1:400-700"},
    ).json()
    ids = {t["genome_id"] for t in body["targets"]}
    assert "A" not in ids
    assert ids == {"B", "C"}


def test_highlight_empty_region(client: TestClient) -> None:
    # A has no SCMs beyond 1100; this region is empty.
    body = client.get(
        "/api/highlight",
        params={"genome_id": "A", "region": "chr1:5000-6000"},
    ).json()
    assert body["source"]["scm_count"] == 0
    assert body["source"]["scm_ids"] == []
    for t in body["targets"]:
        assert t["scm_count"] == 0
        assert t["positions"] == []


def test_highlight_hits_some_genomes_not_others(client: TestClient) -> None:
    """OG01..OG04 are in B but NOT in C (C starts at OG05)."""
    body = client.get(
        "/api/highlight",
        params={"genome_id": "A", "region": "chr1:0-400"},
    ).json()
    # OG01 (99), OG02 (199), OG03 (299), OG04 (399): 4 SCMs in [0, 400).
    assert body["source"]["scm_count"] == 4
    b = _target(body, "B")
    c = _target(body, "C")
    assert b["scm_count"] == 4
    assert c["scm_count"] == 0


def test_highlight_unknown_genome_404(client: TestClient) -> None:
    r = client.get(
        "/api/highlight",
        params={"genome_id": "NOPE", "region": "chr1:0-100"},
    )
    assert r.status_code == 404


def test_highlight_unknown_seq_404(client: TestClient) -> None:
    r = client.get(
        "/api/highlight",
        params={"genome_id": "A", "region": "ghost:0-100"},
    )
    assert r.status_code == 404


def test_highlight_malformed_region_400(client: TestClient) -> None:
    r = client.get(
        "/api/highlight",
        params={"genome_id": "A", "region": "garbage"},
    )
    assert r.status_code == 400


def test_highlight_truncation_subsamples_uniformly(client: TestClient) -> None:
    """When the per-genome cap is hit, the emitted positions must be sampled
    uniformly across the region, not head-truncated.

    Regression for the perf-cap bug: ``matching[:limit]`` returned the lowest-
    offset matches only, clustering every tick at the start of the chromosome
    and collapsing the cross-genome signal. Uniform sampling keeps the full span.

    A.chr1:[0, 2000) catches OG01..OG10 (10 source SCMs). Target B shares
    OG01..OG08 at increasing positions. With limit=3, a uniform sample must
    include the *last* match (OG08); head truncation would drop it.
    """
    body = client.get(
        "/api/highlight",
        params={"genome_id": "A", "region": "chr1:0-2000", "limit": 3},
    ).json()

    src = body["source"]
    assert src["scm_count"] == 10  # full total, independent of the cap
    assert src["truncated"] is True
    assert len(src["scm_ids"]) <= 3
    # Uniform sample spans the source: highest-numbered source SCM is retained.
    assert "OG10" in src["scm_ids"]

    b = _target(body, "B")
    assert b["scm_count"] == 8  # full match count, not the truncated length
    assert b["truncated"] is True
    assert len(b["positions"]) <= 3
    emitted = {p["scm_id"] for p in b["positions"]}
    # The defining property: the last (highest-offset) match survives.
    assert "OG08" in emitted


def test_highlight_limit_zero_returns_complete_set(client: TestClient) -> None:
    """limit=0 means unlimited — used by the SCM-ID export, where completeness
    is required for designing FISH probe sets. Every source SCM and every target
    position must be present, with truncated=False."""
    body = client.get(
        "/api/highlight",
        params={"genome_id": "A", "region": "chr1:0-2000", "limit": 0},
    ).json()

    src = body["source"]
    assert src["scm_count"] == 10
    assert src["truncated"] is False
    assert set(src["scm_ids"]) == {f"OG{i:02d}" for i in range(1, 11)}

    b = _target(body, "B")
    assert b["scm_count"] == 8
    assert b["truncated"] is False
    assert {p["scm_id"] for p in b["positions"]} == {f"OG{i:02d}" for i in range(1, 9)}
