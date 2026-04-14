from fastapi.testclient import TestClient


def test_get_config(client: TestClient) -> None:
    body = client.get("/api/config").json()
    assert body["block_detection"]["max_gap"] == 300_000
    assert body["block_detection"]["min_block_size"] == 2  # synthetic fixture override
    assert "min_pident" in body["blast_filtering"]
    assert "block_threshold_bp_per_px" in body["rendering_defaults"]


def test_put_config_updates_block_detection(client: TestClient) -> None:
    # First derive a pair so the cache has something to re-block.
    client.get("/api/synteny/blocks", params={"g1": "A", "g2": "B"})

    r = client.put(
        "/api/config",
        json={"block_detection": {"max_gap": 50, "min_block_size": 10}},
    )
    assert r.status_code == 200
    assert r.json()["block_detection"]["max_gap"] == 50

    # Subsequent /blocks call sees the new params (B should now be empty).
    body = client.get("/api/synteny/blocks", params={"g1": "A", "g2": "B"}).json()
    assert body["block_count"] == 0  # min_block_size=10 kills the only block (size 8)


def test_put_config_validates(client: TestClient) -> None:
    # max_gap must be >= 1 per schema
    r = client.put(
        "/api/config",
        json={"block_detection": {"max_gap": 0, "min_block_size": 1}},
    )
    assert r.status_code == 422


def test_put_config_rejects_unknown_fields(client: TestClient) -> None:
    r = client.put(
        "/api/config",
        json={
            "block_detection": {"max_gap": 1000, "min_block_size": 1},
            "extra_field": "nope",
        },
    )
    assert r.status_code == 422
