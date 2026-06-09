"""Tests for /api/fish — custom marker-set (FISH) endpoints.

Fixture recap (see tests/api/conftest.py):
    A: chr1=10000, OG01..OG10 at [100, 1000) forward-strand.
    B: chr1=10000, OG01..OG08 + OG11, OG12 at [900, 1100).
    C: chr1=10000, OG05..OG14 reverse-strand at C positions [4900, 4000).

Universe: OG01..OG14 (14 SCMs).
"""

from fastapi.testclient import TestClient

from syntrack.api.routes_fish import _resolve_fish_set, _resolve_indices
from syntrack.api.schemas import FishSetRequest


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


# ------------------------------ /api/fish/density --------------------------


def test_fish_density_basic(client: TestClient) -> None:
    client.post(
        "/api/fish",
        json={"scm_ids": ["OG01", "OG02", "OG03"], "label": "red", "color": "#FF0000"},
    )
    resp = client.post("/api/fish/density", json={"bins": 10})
    assert resp.status_code == 200
    body = resp.json()
    assert body["bins"] == 10
    assert len(body["sets"]) == 1
    s = body["sets"][0]
    assert s["label"] == "red"
    assert s["color"] == "#FF0000"
    assert s["scm_count"] == 3
    assert s["max_count"] == 3

    # A & B: OG01..OG03 at offsets 100/200/300; total_length 10000; bin width
    # 1000 -> all three fall in bin 0. C has none of them.
    for gid in ("A", "B"):
        col = s["genomes"][gid]
        assert len(col) == 10
        assert col[0] == 3
        assert sum(col) == 3
    assert sum(s["genomes"]["C"]) == 0


def test_fish_density_specific_labels_and_presence(client: TestClient) -> None:
    client.post("/api/fish", json={"scm_ids": ["OG01"], "label": "red", "color": "#FF0000"})
    # OG05 is present in all three genomes (A: OG01..10, B: OG01..08, C: OG05..14).
    client.post("/api/fish", json={"scm_ids": ["OG05"], "label": "green", "color": "#00FF00"})
    resp = client.post("/api/fish/density", json={"bins": 5, "labels": ["green"]})
    assert resp.status_code == 200
    body = resp.json()
    assert [s["label"] for s in body["sets"]] == ["green"]
    g = body["sets"][0]
    for gid in ("A", "B", "C"):
        assert sum(g["genomes"][gid]) == 1  # OG05 present once in each


def test_fish_density_unknown_label_404(client: TestClient) -> None:
    resp = client.post("/api/fish/density", json={"bins": 5, "labels": ["nope"]})
    assert resp.status_code == 404


def test_fish_density_no_sets_returns_empty(client: TestClient) -> None:
    resp = client.post("/api/fish/density", json={"bins": 5})
    assert resp.status_code == 200
    assert resp.json()["sets"] == []


def test_fish_density_bins_validation(client: TestClient) -> None:
    assert client.post("/api/fish/density", json={"bins": 0}).status_code == 422
    assert client.post("/api/fish/density", json={"bins": 999_999}).status_code == 422


def test_fish_density_dropped_after_delete(client: TestClient) -> None:
    client.post("/api/fish", json={"scm_ids": ["OG01"], "label": "tmp", "color": "#FF0000"})
    assert client.delete("/api/fish/tmp").status_code == 204
    # Indices were removed too -> density no longer knows the label.
    assert client.post("/api/fish/density", json={"bins": 5, "labels": ["tmp"]}).status_code == 404


def test_fish_overlay_positions_subsample_not_head_truncate(app_state) -> None:  # type: ignore[no-untyped-def]
    """The per-genome overlay positions must be uniformly subsampled across the
    karyotype, not head-truncated to the leftmost (lowest-offset) SCMs — so a
    saved set renders like the live region highlight it came from."""
    # A has OG01..OG10 at increasing offsets 100..1000.
    req = FishSetRequest(scm_ids=[f"OG{i:02d}" for i in range(1, 11)], label="big", color="#FF0000")
    scm_arr = _resolve_indices(req.scm_ids, app_state)
    resp = _resolve_fish_set(req, scm_arr, app_state, limit=3)

    a = next(g for g in resp.genomes if g.genome_id == "A")
    assert a.scm_count == 10  # full count reported
    assert a.truncated is True
    assert len(a.positions) <= 3
    ids = {p.scm_id for p in a.positions}
    # Head truncation would yield OG01..OG03; subsampling keeps the last (OG10).
    assert "OG10" in ids


# ------------------------------ /api/fish/{label}/scms ---------------------


def test_fish_set_scms_export(client: TestClient) -> None:
    # OG01 is in A,B (not C); OG05 is in A,B,C.
    client.post("/api/fish", json={"scm_ids": ["OG01", "OG05"], "label": "x", "color": "#FF0000"})
    body = client.get("/api/fish/x/scms").json()
    assert body["label"] == "x"
    ids = body["scm_ids"]
    assert set(ids) == {"OG01", "OG05"}
    i01, i05 = ids.index("OG01"), ids.index("OG05")
    p = body["presence"]
    assert p["A"][i01] == "1" and p["B"][i01] == "1" and p["C"][i01] == "0"
    assert p["A"][i05] == "1" and p["B"][i05] == "1" and p["C"][i05] == "1"
    # Presence strings are aligned to scm_ids length.
    assert all(len(p[g]) == len(ids) for g in ("A", "B", "C"))


def test_fish_set_scms_unknown_404(client: TestClient) -> None:
    assert client.get("/api/fish/nope/scms").status_code == 404
