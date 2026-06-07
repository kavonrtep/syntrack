"""Tests for /api/fish — custom marker-set (FISH) endpoints.

Fixture recap (see tests/api/conftest.py):
    A: chr1=10000, OG01..OG10 at [100, 1000) forward-strand.
    B: chr1=10000, OG01..OG08 + OG11, OG12 at [900, 1100).
    C: chr1=10000, OG05..OG14 reverse-strand at C positions [4900, 4000).

Universe: OG01..OG14 (14 SCMs).
"""

from fastapi.testclient import TestClient


def test_create_fish_set(client: TestClient) -> None:
    resp = client.post(
        "/api/fish",
        json={"scm_ids": ["OG01", "OG02", "OG03"], "label": "test1", "color": "#FF0000"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["label"] == "test1"
    assert body["color"] == "#FF0000"
    assert body["scm_count"] == 3

    # OG01..OG03 are present in A and B, not in C.
    assert body["genome_coverage"]["A"] == 3
    assert body["genome_coverage"]["B"] == 3
    assert body["genome_coverage"]["C"] == 0

    # Verify positions are returned for genome A.
    a_genome = next(g for g in body["genomes"] if g["genome_id"] == "A")
    assert a_genome["scm_count"] == 3
    a_ids = {p["scm_id"] for p in a_genome["positions"]}
    assert a_ids == {"OG01", "OG02", "OG03"}
    for p in a_genome["positions"]:
        assert p["seq"] == "chr1"
        assert p["strand"] == "+"


def test_create_fish_set_unknown_ids_skipped(client: TestClient) -> None:
    resp = client.post(
        "/api/fish",
        json={"scm_ids": ["OG01", "BOGUS_1", "BOGUS_2"], "label": "partial", "color": "#00FF00"},
    )
    assert resp.status_code == 201
    body = resp.json()
    # Only OG01 is valid.
    assert body["scm_count"] == 1
    a_genome = next(g for g in body["genomes"] if g["genome_id"] == "A")
    assert a_genome["scm_count"] == 1
    assert a_genome["positions"][0]["scm_id"] == "OG01"


def test_create_fish_set_all_unknown(client: TestClient) -> None:
    resp = client.post(
        "/api/fish",
        json={"scm_ids": ["NOPE1", "NOPE2"], "label": "empty", "color": "#0000FF"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["scm_count"] == 0
    assert body["genome_coverage"] == {}
    assert body["genomes"] == []


def test_create_fish_set_shared_across_genomes(client: TestClient) -> None:
    """OG05..OG08 are present in all three genomes."""
    resp = client.post(
        "/api/fish",
        json={"scm_ids": ["OG05", "OG06", "OG07", "OG08"], "label": "shared", "color": "#AABB00"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["scm_count"] == 4
    assert body["genome_coverage"]["A"] == 4
    assert body["genome_coverage"]["B"] == 4
    assert body["genome_coverage"]["C"] == 4

    c_genome = next(g for g in body["genomes"] if g["genome_id"] == "C")
    for p in c_genome["positions"]:
        assert p["strand"] == "-"


def test_duplicate_label_409(client: TestClient) -> None:
    resp1 = client.post(
        "/api/fish",
        json={"scm_ids": ["OG01"], "label": "dup", "color": "#111111"},
    )
    assert resp1.status_code == 201

    resp2 = client.post(
        "/api/fish",
        json={"scm_ids": ["OG02"], "label": "dup", "color": "#222222"},
    )
    assert resp2.status_code == 409


def test_list_fish_sets(client: TestClient) -> None:
    client.post(
        "/api/fish",
        json={"scm_ids": ["OG01"], "label": "set_a", "color": "#AA0000"},
    )
    client.post(
        "/api/fish",
        json={"scm_ids": ["OG02", "OG03"], "label": "set_b", "color": "#BB0000"},
    )
    resp = client.get("/api/fish")
    assert resp.status_code == 200
    body = resp.json()
    labels = {s["label"] for s in body["sets"]}
    assert labels == {"set_a", "set_b"}

    # List returns summaries, not full positions.
    for s in body["sets"]:
        assert "genomes" not in s


def test_delete_fish_set(client: TestClient) -> None:
    client.post(
        "/api/fish",
        json={"scm_ids": ["OG01"], "label": "to_delete", "color": "#CC0000"},
    )
    resp = client.delete("/api/fish/to_delete")
    assert resp.status_code == 204

    # Verify it's gone.
    listing = client.get("/api/fish").json()
    labels = {s["label"] for s in listing["sets"]}
    assert "to_delete" not in labels


def test_delete_nonexistent_404(client: TestClient) -> None:
    resp = client.delete("/api/fish/nonexistent")
    assert resp.status_code == 404


def test_invalid_color_422(client: TestClient) -> None:
    resp = client.post(
        "/api/fish",
        json={"scm_ids": ["OG01"], "label": "bad", "color": "red"},
    )
    assert resp.status_code == 422


def test_list_empty(client: TestClient) -> None:
    resp = client.get("/api/fish")
    assert resp.status_code == 200
    assert resp.json()["sets"] == []
