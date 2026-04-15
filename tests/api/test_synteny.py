from fastapi.testclient import TestClient


def test_blocks_basic(client: TestClient) -> None:
    r = client.get("/api/synteny/blocks", params={"g1": "A", "g2": "B"})
    assert r.status_code == 200
    body = r.json()
    assert body["pair"] == ["A", "B"]
    assert body["shared_scm_count"] == 8  # OG01..OG08
    # All 8 SCMs are collinear on chr1 → expect 1 block
    assert body["block_count"] >= 1
    block = body["blocks"][0]
    assert block["g1_seq"] == "chr1"
    assert block["g2_seq"] == "chr1"
    assert block["strand"] == "+"


def test_blocks_negative_strand_for_anti_collinear(client: TestClient) -> None:
    """C is reverse-collinear with A on shared SCMs."""
    r = client.get("/api/synteny/blocks", params={"g1": "A", "g2": "C"})
    body = r.json()
    # Shared SCMs A∩C: OG05..OG10 (6 items)
    assert body["shared_scm_count"] == 6
    # Should produce at least one block; relative strand should be "-"
    assert body["block_count"] >= 1
    assert any(b["strand"] == "-" for b in body["blocks"])


def test_blocks_min_scm_filter(client: TestClient) -> None:
    body = client.get("/api/synteny/blocks", params={"g1": "A", "g2": "B", "min_scm": 100}).json()
    assert body["block_count"] == 0
    assert body["blocks"] == []


def test_blocks_region_filter(client: TestClient) -> None:
    body = client.get(
        "/api/synteny/blocks",
        params={"g1": "A", "g2": "B", "region_g1": "chr1:0-500"},
    ).json()
    # Only blocks whose g1 extent overlaps chr1:0-500
    for b in body["blocks"]:
        assert b["g1_start"] < 500
        assert b["g1_end"] > 0


def test_blocks_unknown_genome_404(client: TestClient) -> None:
    r = client.get("/api/synteny/blocks", params={"g1": "A", "g2": "ZZ"})
    assert r.status_code == 404


def test_blocks_self_pair_400(client: TestClient) -> None:
    r = client.get("/api/synteny/blocks", params={"g1": "A", "g2": "A"})
    assert r.status_code == 400


def test_blocks_bad_region_400(client: TestClient) -> None:
    r = client.get(
        "/api/synteny/blocks",
        params={"g1": "A", "g2": "B", "region_g1": "garbage"},
    )
    assert r.status_code == 400


def test_blocks_unknown_seq_in_region_404(client: TestClient) -> None:
    r = client.get(
        "/api/synteny/blocks",
        params={"g1": "A", "g2": "B", "region_g1": "fake_chr:0-100"},
    )
    assert r.status_code == 404


# ------------------------------ /api/synteny/scms ------------------------


def test_scms_basic(client: TestClient) -> None:
    body = client.get("/api/synteny/scms", params={"g1": "A", "g2": "B"}).json()
    assert body["pair"] == ["A", "B"]
    assert body["total_in_region"] == 8
    assert body["returned"] == 8
    assert body["downsampled"] is False
    scm_ids = {s["scm_id"] for s in body["scms"]}
    assert scm_ids == {f"OG{i:02d}" for i in range(1, 9)}


def test_scms_downsampling(client: TestClient) -> None:
    body = client.get("/api/synteny/scms", params={"g1": "A", "g2": "B", "limit": 3}).json()
    assert body["total_in_region"] == 8
    assert body["returned"] == 3
    assert body["downsampled"] is True


def test_scms_region_filter_g1(client: TestClient) -> None:
    # OGn lands at 0-based [n*100 - 1, n*100 + 99) in A.chr1
    # Region [0, 499) intersects OG01..OG04 (OG04 ends at 499, half-open)
    body = client.get(
        "/api/synteny/scms",
        params={"g1": "A", "g2": "B", "region_g1": "chr1:0-499"},
    ).json()
    scm_ids = {s["scm_id"] for s in body["scms"]}
    assert scm_ids == {"OG01", "OG02", "OG03", "OG04"}


def test_scms_strand_field(client: TestClient) -> None:
    body = client.get("/api/synteny/scms", params={"g1": "A", "g2": "B"}).json()
    for s in body["scms"]:
        assert s["strand"] in ("+", "-")


# ------------------------------ reference= param ------------------------


def test_blocks_reference_none_by_default(client: TestClient) -> None:
    """Without ?reference, blocks report reference_seq = null."""
    body = client.get("/api/synteny/blocks", params={"g1": "A", "g2": "B"}).json()
    assert body["block_count"] >= 1
    assert all(b["reference_seq"] is None for b in body["blocks"])


def test_blocks_reference_populated(client: TestClient) -> None:
    """With ?reference=A, the A/B blocks get a reference_seq name (A's chr1)."""
    body = client.get(
        "/api/synteny/blocks",
        params={"g1": "A", "g2": "B", "reference": "A"},
    ).json()
    assert body["block_count"] >= 1
    for b in body["blocks"]:
        assert b["reference_seq"] == "chr1"  # synthetic fixture has a single chr1


def test_blocks_reference_unknown_404(client: TestClient) -> None:
    r = client.get(
        "/api/synteny/blocks",
        params={"g1": "A", "g2": "B", "reference": "NOPE"},
    )
    assert r.status_code == 404


def test_scms_reference_populated(client: TestClient) -> None:
    body = client.get(
        "/api/synteny/scms",
        params={"g1": "A", "g2": "B", "reference": "A"},
    ).json()
    assert body["returned"] > 0
    for s in body["scms"]:
        # Shared SCMs between A and B are OG01..OG08, all on A's chr1.
        assert s["reference_seq"] == "chr1"


def test_scms_reference_absent_returns_null(client: TestClient) -> None:
    """Using a reference that's missing some shared SCMs produces null fields."""
    # Shared SCMs between B and C are OG05..OG08 plus OG11/OG12.
    # Reference = A has OG05..OG08 but NOT OG11/OG12 → mix of strings and null.
    body = client.get(
        "/api/synteny/scms",
        params={"g1": "B", "g2": "C", "reference": "A"},
    ).json()
    ref_values = {s["reference_seq"] for s in body["scms"]}
    # Expect both "chr1" (from A) and None for SCMs absent from A.
    assert "chr1" in ref_values
    assert None in ref_values
