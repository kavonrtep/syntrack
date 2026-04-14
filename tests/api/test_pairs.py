from fastapi.testclient import TestClient


def test_list_pairs(client: TestClient) -> None:
    body = client.get("/api/pairs").json()
    pair_keys = {(p["genome1_id"], p["genome2_id"]) for p in body["pairs"]}
    # combinations(["A","B","C"], 2) → AB, AC, BC
    assert pair_keys == {("A", "B"), ("A", "C"), ("B", "C")}


def test_pair_shared_count_correct(client: TestClient) -> None:
    body = client.get("/api/pairs").json()
    ab = next(p for p in body["pairs"] if (p["genome1_id"], p["genome2_id"]) == ("A", "B"))
    # A: OG01..OG10; B: OG01..OG08, OG11, OG12 → shared = OG01..OG08 = 8
    assert ab["shared_scm_count"] == 8


def test_pair_derived_flag_reflects_cache(client: TestClient) -> None:
    body = client.get("/api/pairs").json()
    # Nothing derived yet
    assert all(not p["derived"] for p in body["pairs"])

    # Trigger derivation of (A, B)
    client.get("/api/synteny/blocks", params={"g1": "A", "g2": "B"})

    body2 = client.get("/api/pairs").json()
    ab = next(p for p in body2["pairs"] if (p["genome1_id"], p["genome2_id"]) == ("A", "B"))
    assert ab["derived"] is True
    assert ab["block_count"] is not None
