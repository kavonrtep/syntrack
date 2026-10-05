"""Tests for per-session FISH marker sets (docs/design/FISH_SESSION_SCOPE.md).

One process serves several browsers, so sets are namespaced by the opaque
``X-SynTrack-Session`` header. Fixture recap is in tests/api/conftest.py.
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from syntrack.api.deps import DEFAULT_SESSION, MAX_SESSION_ID_LEN, get_session
from syntrack.api.fish_store import FishSetTooLargeError, FishStore
from syntrack.api.schemas import FishSetResponse
from syntrack.api.state import AppState

A_HDR = {"X-SynTrack-Session": "session-a"}
B_HDR = {"X-SynTrack-Session": "session-b"}


def _create(client: TestClient, label: str, ids: list[str], headers: dict[str, str] | None):
    return client.post(
        "/api/fish",
        json={"scm_ids": ids, "label": label, "color": "#FF0000"},
        headers=headers,
    )


# --------------------------- isolation between sessions ---------------------


def test_same_label_in_two_sessions_does_not_collide(client: TestClient) -> None:
    assert _create(client, "shared", ["OG01"], A_HDR).status_code == 201
    assert _create(client, "shared", ["OG02", "OG03"], B_HDR).status_code == 201

    a_labels = [s["label"] for s in client.get("/api/fish", headers=A_HDR).json()["sets"]]
    b_labels = [s["label"] for s in client.get("/api/fish", headers=B_HDR).json()["sets"]]
    assert a_labels == ["shared"] == b_labels

    # Each session keeps its own membership under that label.
    a_ids = client.get("/api/fish/shared/scms", headers=A_HDR).json()["scm_ids"]
    b_ids = client.get("/api/fish/shared/scms", headers=B_HDR).json()["scm_ids"]
    assert a_ids == ["OG01"]
    assert b_ids == ["OG02", "OG03"]


def test_list_shows_only_the_callers_sets(client: TestClient) -> None:
    _create(client, "a_only", ["OG01"], A_HDR)
    assert client.get("/api/fish", headers=B_HDR).json()["sets"] == []


def test_delete_cannot_reach_another_session(client: TestClient) -> None:
    _create(client, "mine", ["OG01"], A_HDR)
    assert client.delete("/api/fish/mine", headers=B_HDR).status_code == 404
    # A's set is untouched.
    assert [s["label"] for s in client.get("/api/fish", headers=A_HDR).json()["sets"]] == ["mine"]


def test_density_reports_another_sessions_label_as_missing(client: TestClient) -> None:
    _create(client, "a_only", ["OG01"], A_HDR)
    resp = client.post("/api/fish/density", json={"bins": 4, "labels": ["a_only"]}, headers=B_HDR)
    assert resp.status_code == 200
    body = resp.json()
    assert body["sets"] == []
    assert body["missing"] == ["a_only"]


def test_get_set_cannot_reach_another_session(client: TestClient) -> None:
    """The hydration getter is session-scoped too, or a reloaded page would
    rebuild its sidebar from someone else's sets."""
    _create(client, "a_only", ["OG01"], A_HDR)
    assert client.get("/api/fish/a_only", headers=A_HDR).status_code == 200
    assert client.get("/api/fish/a_only", headers=B_HDR).status_code == 404


def test_get_set_returns_positions_for_hydration(client: TestClient) -> None:
    _create(client, "s", ["OG01", "OG02"], A_HDR)
    body = client.get("/api/fish/s", headers=A_HDR).json()
    assert body["label"] == "s"
    assert body["scm_count"] == 2
    # Positions are what the overlay needs and the list endpoint omits.
    assert any(g["positions"] for g in body["genomes"])


def test_scms_export_cannot_reach_another_session(client: TestClient) -> None:
    _create(client, "a_only", ["OG01"], A_HDR)
    assert client.get("/api/fish/a_only/scms", headers=B_HDR).status_code == 404


def test_density_without_labels_covers_only_the_callers_sets(client: TestClient) -> None:
    _create(client, "a_only", ["OG01"], A_HDR)
    _create(client, "b_only", ["OG02"], B_HDR)
    body = client.post("/api/fish/density", json={"bins": 4}, headers=B_HDR).json()
    assert [s["label"] for s in body["sets"]] == ["b_only"]


# --------------------------- backward compatibility -------------------------


def test_no_header_behaves_like_the_old_global_store(client: TestClient) -> None:
    """An older frontend, the CLI or curl send no header and must keep working."""
    assert _create(client, "legacy", ["OG01"], None).status_code == 201
    assert [s["label"] for s in client.get("/api/fish").json()["sets"]] == ["legacy"]
    assert client.get("/api/fish/legacy/scms").json()["scm_ids"] == ["OG01"]
    assert client.delete("/api/fish/legacy").status_code == 204


def test_header_and_no_header_are_separate_namespaces(client: TestClient) -> None:
    _create(client, "x", ["OG01"], None)
    assert client.get("/api/fish", headers=A_HDR).json()["sets"] == []


@pytest.mark.parametrize(
    "value",
    ["", "   ", "x" * (MAX_SESSION_ID_LEN + 1)],
)
def test_malformed_session_ids_fall_back_to_the_default(value: str) -> None:
    """Degrade to the shared namespace rather than failing the request."""
    assert get_session(value) == DEFAULT_SESSION


def test_session_id_is_opaque() -> None:
    assert get_session("  Session/With:Odd Chars  ") == "Session/With:Odd Chars"
    assert get_session(None) == DEFAULT_SESSION


# --------------------------- bounds and eviction ----------------------------


def _resp(label: str) -> FishSetResponse:
    return FishSetResponse(
        label=label, color="#FF0000", scm_count=1, genome_coverage={}, genomes=[]
    )


def _idx(n: int) -> np.ndarray:
    return np.arange(n, dtype=np.int32)


def test_byte_cap_evicts_the_least_recently_active_session() -> None:
    # Room for two 100-int32 sets (400 bytes each) and no more.
    store = FishStore(max_bytes=900)
    store.put("old", "s", _resp("s"), _idx(100), replace=False)
    store.put("mid", "s", _resp("s"), _idx(100), replace=False)
    # Touch 'mid' so 'old' is the least recently active.
    store.labels("mid")
    store.put("new", "s", _resp("s"), _idx(100), replace=False)

    assert store.get("old", "s") is None
    assert store.get("mid", "s") is not None
    assert store.get("new", "s") is not None
    assert store.total_bytes() <= 900


def test_byte_cap_sheds_own_sets_when_only_one_session_remains() -> None:
    store = FishStore(max_bytes=900)
    store.put("solo", "first", _resp("first"), _idx(100), replace=False)
    store.put("solo", "second", _resp("second"), _idx(100), replace=False)
    store.put("solo", "third", _resp("third"), _idx(100), replace=False)
    assert store.labels("solo") == ["second", "third"]


def test_replacing_a_set_does_not_count_twice() -> None:
    store = FishStore(max_bytes=900)
    store.put("s", "a", _resp("a"), _idx(100), replace=False)
    for _ in range(5):
        store.put("s", "a", _resp("a"), _idx(100), replace=True)
    assert store.labels("s") == ["a"]
    assert store.total_bytes() == 400


def test_set_larger_than_the_whole_budget_is_rejected() -> None:
    store = FishStore(max_bytes=100)
    with pytest.raises(FishSetTooLargeError):
        store.put("s", "huge", _resp("huge"), _idx(1000), replace=False)


def test_oversize_set_returns_413(
    client: TestClient,
    app_state: AppState,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A set no eviction could fit is refused outright, not silently dropped."""
    monkeypatch.setattr(app_state, "fish", FishStore(max_bytes=4))
    resp = _create(client, "huge", ["OG01", "OG02", "OG03"], A_HDR)
    assert resp.status_code == 413
    assert "budget" in resp.json()["detail"]


def test_session_cap_evicts_the_oldest_session() -> None:
    store = FishStore(max_sessions=2)
    store.put("s1", "a", _resp("a"), _idx(1), replace=False)
    store.put("s2", "a", _resp("a"), _idx(1), replace=False)
    store.labels("s2")
    store.put("s3", "a", _resp("a"), _idx(1), replace=False)
    assert sorted(store.session_keys()) == ["s2", "s3"]


def test_idle_sessions_expire(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = {"t": 1000.0}
    monkeypatch.setattr("syntrack.api.fish_store.time.monotonic", lambda: clock["t"])
    store = FishStore(ttl_s=60)
    store.put("s", "a", _resp("a"), _idx(1), replace=False)
    assert store.get("s", "a") is not None
    clock["t"] += 61
    assert store.get("s", "a") is None
    assert store.session_keys() == []


def test_evicted_session_can_recreate_its_set(client: TestClient) -> None:
    """The client keeps the SCM IDs, so eviction costs a round trip, not data."""
    _create(client, "s", ["OG01"], A_HDR)
    assert client.delete("/api/fish/s", headers=A_HDR).status_code == 204
    again = client.post(
        "/api/fish",
        json={"scm_ids": ["OG01"], "label": "s", "color": "#FF0000", "replace": True},
        headers=A_HDR,
    )
    assert again.status_code == 201
    assert client.get("/api/fish/s/scms", headers=A_HDR).json()["scm_ids"] == ["OG01"]
