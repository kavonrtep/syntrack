from fastapi.testclient import TestClient


def test_list_genomes(client: TestClient) -> None:
    r = client.get("/api/genomes")
    assert r.status_code == 200
    body = r.json()
    ids = [g["id"] for g in body["genomes"]]
    assert ids == ["A", "B", "C"]
    assert body["scm_universe_size"] == 14  # OG01..OG14


def test_genome_includes_filtering_stats(client: TestClient) -> None:
    body = client.get("/api/genomes").json()
    a = next(g for g in body["genomes"] if g["id"] == "A")
    assert a["scm_count"] == 10
    assert a["filtering"]["raw_hits"] == 10
    assert a["filtering"]["after_validation"] == 10


def test_genome_includes_sequences_with_color(client: TestClient) -> None:
    body = client.get("/api/genomes").json()
    a = next(g for g in body["genomes"] if g["id"] == "A")
    assert len(a["sequences"]) == 1
    seq = a["sequences"][0]
    assert seq["name"] == "chr1"
    assert seq["length"] == 10_000
    assert seq["offset"] == 0
    assert seq["color"].startswith("#")
