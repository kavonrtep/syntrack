"""Tests for /healthz (not under /api)."""

from fastapi.testclient import TestClient

from syntrack import __version__


def test_healthz_returns_status_ok(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    # Fixture has 3 genomes (A, B, C) with 14 unique SCMs.
    assert body["genomes"] == 3
    assert body["universe_size"] == 14
