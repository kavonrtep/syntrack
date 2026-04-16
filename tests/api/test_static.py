"""StaticFiles mount behaviour (container mode)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from syntrack.api.app import create_app
from syntrack.api.state import AppState


def test_static_mount_when_env_set(
    tmp_path: Path,
    app_state: AppState,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When SYNTRACK_FRONTEND_DIR points at a valid dir, `/` serves index.html."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text(
        "<!doctype html><html><body>hello syntrack</body></html>"
    )
    monkeypatch.setenv("SYNTRACK_FRONTEND_DIR", str(dist))

    client = TestClient(create_app(app_state))
    r = client.get("/")
    assert r.status_code == 200
    assert "hello syntrack" in r.text

    # API still works — routers have priority over the static mount.
    r = client.get("/api/genomes")
    assert r.status_code == 200
    assert "genomes" in r.json()

    # Health check also unaffected.
    r = client.get("/healthz")
    assert r.status_code == 200


def test_no_static_mount_when_env_unset(
    app_state: AppState,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without SYNTRACK_FRONTEND_DIR, `/` returns 404 (dev mode)."""
    monkeypatch.delenv("SYNTRACK_FRONTEND_DIR", raising=False)
    client = TestClient(create_app(app_state))
    r = client.get("/")
    assert r.status_code == 404


def test_no_static_mount_when_dir_missing(
    tmp_path: Path,
    app_state: AppState,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Env var set but the directory doesn't exist — skip the mount silently."""
    monkeypatch.setenv("SYNTRACK_FRONTEND_DIR", str(tmp_path / "ghost"))
    client = TestClient(create_app(app_state))
    r = client.get("/")
    assert r.status_code == 404
    # But the API is still up.
    r = client.get("/api/genomes")
    assert r.status_code == 200
