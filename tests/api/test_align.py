"""Tests for /api/align — double-click alignment endpoint.

Fixture recap (see tests/api/conftest.py):
    A: chr1=10000, OG01..OG10 at positions 100..1000 (forward strand)
    B: chr1=10000, OG01..OG08 at 100..800 + OG11, OG12 at 900..1100
    C: chr1=10000, OG05..OG14 at 4900..4000 (reverse strand — inversion)

Blocks derived under the fixture's min_block_size=2:
    (A, B): one block on (chr1, chr1), + strand, g1=[99,899], g2=[99,899] (OG01..OG08).
    (A, C): one block on (chr1, chr1), - strand, g1=[499,1099], g2=[4399,4999] (OG05..OG10).
"""

from fastapi.testclient import TestClient


def _mapping(body: dict, gid: str) -> dict:
    for m in body["mappings"]:
        if m["genome_id"] == gid:
            return m
    raise AssertionError(f"no mapping for {gid!r}: {body!r}")


def test_align_inside_block_both_targets(client: TestClient) -> None:
    body = client.get("/api/align", params={"genome_id": "A", "seq": "chr1", "pos": 500}).json()
    assert body["source"] == {"genome_id": "A", "seq": "chr1", "pos": 500}

    m_b = _mapping(body, "B")
    # A-B block g1=[99,899], +strand, g2=[99,899]. pos=500 → f≈0.50, target≈500.
    assert m_b["seq"] == "chr1"
    assert abs(m_b["pos"] - 500) <= 2
    assert m_b["confidence"] == 1.0

    m_c = _mapping(body, "C")
    # A-C block g1=[499,1099], -strand, g2=[4399,4999]. pos=500 → f≈0.00167,
    # target = 4999 - 0.00167*(4999-4399) ≈ 4998.
    assert m_c["seq"] == "chr1"
    assert 4990 <= m_c["pos"] <= 4999
    assert m_c["confidence"] == 1.0


def test_align_before_all_blocks(client: TestClient) -> None:
    """pos=50 is left of every block — snap to each block's g1_start endpoint.
    The synthetic blocks are tiny (kb-scale) so the distance-based confidence
    decay (1 Mb reference scale) still reports ≈1.0 — just assert a valid
    mapping exists and points at the correct endpoint."""
    body = client.get("/api/align", params={"genome_id": "A", "seq": "chr1", "pos": 50}).json()
    m_b = _mapping(body, "B")
    # A-B block g2_start=99 (+ strand)
    assert abs(m_b["pos"] - 99) <= 2
    m_c = _mapping(body, "C")
    # A-C - strand, f=0 → g2_end = 4999
    assert abs(m_c["pos"] - 4999) <= 2


def test_align_after_all_blocks(client: TestClient) -> None:
    """pos=1500 is right of every block — snap to each block's g1_end endpoint."""
    body = client.get("/api/align", params={"genome_id": "A", "seq": "chr1", "pos": 1500}).json()
    m_b = _mapping(body, "B")
    # A-B block g2_end=899 (+ strand)
    assert abs(m_b["pos"] - 899) <= 2
    m_c = _mapping(body, "C")
    # A-C block, - strand, f=1 → g2_start = 4399
    assert abs(m_c["pos"] - 4399) <= 2


def test_align_self_not_in_mappings(client: TestClient) -> None:
    body = client.get("/api/align", params={"genome_id": "A", "seq": "chr1", "pos": 500}).json()
    ids = {m["genome_id"] for m in body["mappings"]}
    assert "A" not in ids
    assert ids == {"B", "C"}


def test_align_unknown_genome_404(client: TestClient) -> None:
    r = client.get("/api/align", params={"genome_id": "NOPE", "seq": "chr1", "pos": 100})
    assert r.status_code == 404


def test_align_unknown_seq_404(client: TestClient) -> None:
    r = client.get("/api/align", params={"genome_id": "A", "seq": "ghost", "pos": 100})
    assert r.status_code == 404


def test_align_bp_to_pixel_roundtrip(client: TestClient) -> None:
    """For a bp inside a block, mapping then inverse-mapping (click at the
    same pixel on target) should land at the same target bp. Verified by
    double-query: align A:500 → B:500ish; align B:500 → A:500ish."""
    r1 = client.get("/api/align", params={"genome_id": "A", "seq": "chr1", "pos": 500}).json()
    pos_on_b = _mapping(r1, "B")["pos"]
    r2 = client.get("/api/align", params={"genome_id": "B", "seq": "chr1", "pos": pos_on_b}).json()
    pos_back_on_a = _mapping(r2, "A")["pos"]
    assert abs(pos_back_on_a - 500) <= 3
