"""Tests for /api/paint — reference-painted regions per genome."""

from fastapi.testclient import TestClient


def test_reference_painting_trivial(client: TestClient) -> None:
    """Painting a reference genome with itself produces regions whose
    reference_seq matches the genome's own sequence names."""
    body = client.get("/api/paint", params={"genome_id": "A", "reference": "A"}).json()
    assert body["genome_id"] == "A"
    assert body["reference"] == "A"
    # A has a single chr1 with 10 SCMs all on chr1 → one run.
    assert len(body["regions"]) == 1
    region = body["regions"][0]
    assert region["seq"] == "chr1"
    assert region["reference_seq"] == "chr1"
    assert region["scm_count"] == 10


def test_painting_non_reference_genome(client: TestClient) -> None:
    """B's SCMs OG01..OG08 land on A's chr1; OG11/OG12 are absent from A (→ null)."""
    body = client.get("/api/paint", params={"genome_id": "B", "reference": "A"}).json()
    regions = body["regions"]
    # B has OG01..OG08 (all on B's chr1, all reference A's chr1) → 1 run
    # then OG11..OG12 (on B's chr1, but absent from A → reference_seq null) → 1 run
    assert len(regions) == 2
    assert regions[0]["seq"] == "chr1"
    assert regions[0]["reference_seq"] == "chr1"
    assert regions[0]["scm_count"] == 8
    assert regions[1]["seq"] == "chr1"
    assert regions[1]["reference_seq"] is None
    assert regions[1]["scm_count"] == 2


def test_painting_unknown_genome_404(client: TestClient) -> None:
    r = client.get("/api/paint", params={"genome_id": "NOPE", "reference": "A"})
    assert r.status_code == 404


def test_painting_unknown_reference_404(client: TestClient) -> None:
    r = client.get("/api/paint", params={"genome_id": "A", "reference": "NOPE"})
    assert r.status_code == 404


def test_painting_regions_sorted_by_position(client: TestClient) -> None:
    body = client.get("/api/paint", params={"genome_id": "B", "reference": "A"}).json()
    regions = body["regions"]
    # Within each seq, regions must be non-overlapping and ascending by start.
    prev_seq = None
    prev_end = -1
    for r in regions:
        if r["seq"] != prev_seq:
            prev_end = -1
            prev_seq = r["seq"]
        assert r["start"] >= prev_end
        assert r["end"] > r["start"]
        prev_end = r["end"]
