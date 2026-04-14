from fastapi.testclient import TestClient


def test_scm_present_in_multiple_genomes(client: TestClient) -> None:
    # OG05 is in A, B, and C
    body = client.get("/api/scm/OG05").json()
    assert body["scm_id"] == "OG05"
    assert body["present_in"] == 3
    genome_ids = {p["genome_id"] for p in body["positions"]}
    assert genome_ids == {"A", "B", "C"}


def test_scm_present_in_single_genome(client: TestClient) -> None:
    # OG09 is in A and C (not B)
    body = client.get("/api/scm/OG09").json()
    assert body["present_in"] == 2
    assert {p["genome_id"] for p in body["positions"]} == {"A", "C"}


def test_unknown_scm_404(client: TestClient) -> None:
    r = client.get("/api/scm/NEVER_SEEN")
    assert r.status_code == 404


def test_position_includes_strand(client: TestClient) -> None:
    body = client.get("/api/scm/OG05").json()
    for p in body["positions"]:
        assert p["strand"] in ("+", "-")
