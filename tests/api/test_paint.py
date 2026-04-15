"""Tests for /api/paint — reference-painted regions per genome.

Paint regions are the blocks of pair (genome_id, reference) projected onto
genome_id's coordinate space (same aggregation as /synteny/blocks ribbons).
"""

from fastapi.testclient import TestClient


def test_reference_painting_trivial(client: TestClient) -> None:
    """Painting a reference genome with itself: one region per sequence covering
    the full length, with that sequence as reference_seq."""
    body = client.get("/api/paint", params={"genome_id": "A", "reference": "A"}).json()
    assert body["genome_id"] == "A"
    assert body["reference"] == "A"
    assert len(body["regions"]) == 1
    region = body["regions"][0]
    assert region["seq"] == "chr1"
    assert region["reference_seq"] == "chr1"
    assert region["start"] == 0
    assert region["end"] == 10_000  # full sequence length from the fixture
    assert region["scm_count"] == 10  # SCMs present in A on chr1


def test_painting_non_reference_genome(client: TestClient) -> None:
    """B's SCMs OG01..OG08 land on A's chr1 collinearly → one block.
    OG11/OG12 are absent from A so they don't appear in the pair intersection
    (and therefore don't produce a paint region)."""
    body = client.get("/api/paint", params={"genome_id": "B", "reference": "A"}).json()
    regions = body["regions"]
    assert len(regions) == 1  # single block covering the 8 shared SCMs
    region = regions[0]
    assert region["seq"] == "chr1"
    assert region["reference_seq"] == "chr1"
    assert region["scm_count"] == 8
    # Block bounds track the first and last shared SCM on B.chr1 (OG01..OG08,
    # positions 100..800 in 1-based BLAST → 99..899 in 0-based half-open).
    assert region["start"] == 99
    assert region["end"] == 899


def test_painting_follows_block_detection_params(client: TestClient) -> None:
    """Bumping min_block_size via PUT /api/config drops small paint regions,
    matching how it drops ribbons. This is the main win from block-based paint."""
    # Fixture uses min_block_size=2; the B→A painting produces one 8-SCM block.
    # Push min_block_size=20 and the block is filtered out entirely.
    r = client.put(
        "/api/config",
        json={"block_detection": {"max_gap": 300_000, "min_block_size": 20}},
    )
    assert r.status_code == 200
    body = client.get("/api/paint", params={"genome_id": "B", "reference": "A"}).json()
    assert body["regions"] == []


def test_painting_unknown_genome_404(client: TestClient) -> None:
    r = client.get("/api/paint", params={"genome_id": "NOPE", "reference": "A"})
    assert r.status_code == 404


def test_painting_unknown_reference_404(client: TestClient) -> None:
    r = client.get("/api/paint", params={"genome_id": "A", "reference": "NOPE"})
    assert r.status_code == 404


def test_painting_regions_non_overlapping(client: TestClient) -> None:
    """Regions within one seq must not overlap (blocks come out sorted by g1)."""
    body = client.get("/api/paint", params={"genome_id": "B", "reference": "A"}).json()
    regions = body["regions"]
    prev_seq = None
    prev_end = -1
    for r in regions:
        if r["seq"] != prev_seq:
            prev_end = -1
            prev_seq = r["seq"]
        assert r["start"] >= prev_end
        assert r["end"] > r["start"]
        prev_end = r["end"]
