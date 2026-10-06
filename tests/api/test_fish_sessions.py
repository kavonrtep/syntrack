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


# --------------------------- diagnostics / logging --------------------------


def test_404_detail_says_the_set_was_evicted(client: TestClient, app_state: AppState) -> None:
    """A user's bug report should carry the cause, not just "not found"."""
    monkey = FishStore(max_sets=2)
    app_state.fish = monkey
    for n in range(3):
        _create(client, f"s{n}", ["OG01"], A_HDR)
    resp = client.get("/api/fish/s0/scms", headers=A_HDR)
    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert "set cap" in detail
    assert "removed" in detail
    assert "session holds 2 set(s)" in detail


def test_404_detail_distinguishes_never_held_from_removed(
    client: TestClient,
    app_state: AppState,
) -> None:
    _create(client, "mine", ["OG01"], A_HDR)
    never = client.get("/api/fish/typo/scms", headers=A_HDR).json()["detail"]
    assert "never held that label" in never
    # A session the server has never seen at all reads differently again.
    unknown = client.get(
        "/api/fish/mine/scms",
        headers={"X-SynTrack-Session": "never-seen"},
    ).json()["detail"]
    assert "holds no sets on this server" in unknown
    assert app_state.fish.miss_reason("session-a", "mine").startswith("this session never held")


def test_removals_are_logged_with_cause(
    client: TestClient,
    app_state: AppState,
    caplog: pytest.LogCaptureFixture,
) -> None:
    app_state.fish = FishStore(max_sets=2)
    with caplog.at_level("INFO", logger="syntrack.fish"):
        for n in range(3):
            _create(client, f"s{n}", ["OG01"], A_HDR)
    messages = [r.message for r in caplog.records]
    assert any("stored" in m and "label='s0'" in m for m in messages)
    assert any("dropped set" in m and "reason=set cap" in m for m in messages)


def test_miss_is_logged_at_warning(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING", logger="syntrack.fish"):
        client.get("/api/fish/nope/scms", headers=A_HDR)
    assert any("miss op=export" in r.message for r in caplog.records)
    assert all(r.levelname == "WARNING" for r in caplog.records)


def test_session_keys_are_abbreviated_in_logs(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Logs carry a short session prefix — enough to correlate, short to read."""
    long_id = "0123456789abcdef-0123456789abcdef"
    with caplog.at_level("INFO", logger="syntrack.fish"):
        _create(client, "s", ["OG01"], {"X-SynTrack-Session": long_id})
    joined = "\n".join(r.message for r in caplog.records)
    assert "sid=01234567 " in joined
    assert long_id not in joined


# --------------------------- budget accounting ------------------------------


def test_store_keeps_only_metadata_and_indices(client: TestClient, app_state: AppState) -> None:
    """Positions must NOT be retained: they are ~300x the index array, which is
    what made the byte budget meaningless (fixed after the field report)."""
    _create(client, "s", ["OG01", "OG02"], A_HDR)
    stored = app_state.fish.get("session-a", "s")
    assert stored is not None
    meta, idxs = stored
    assert meta.scm_count == 2
    assert idxs.dtype == np.int32
    # The stored object has no positions attribute at all.
    assert not hasattr(meta, "genomes")
    assert not hasattr(meta, "positions")
    # Accounted bytes are the index array, and nothing hidden alongside it.
    assert app_state.fish.usage("session-a").session_bytes == idxs.nbytes


def test_get_rebuilds_positions_on_demand(client: TestClient) -> None:
    """Dropping stored positions must not change what the client receives."""
    created = _create(client, "s", ["OG01", "OG02"], A_HDR).json()
    fetched = client.get("/api/fish/s", headers=A_HDR).json()
    assert fetched["scm_count"] == created["scm_count"]
    assert fetched["genome_coverage"] == created["genome_coverage"]
    created_pos = {
        g["genome_id"]: [(p["scm_id"], p["start"]) for p in g["positions"]]
        for g in created["genomes"]
    }
    fetched_pos = {
        g["genome_id"]: [(p["scm_id"], p["start"]) for p in g["positions"]]
        for g in fetched["genomes"]
    }
    assert fetched_pos == created_pos


def test_usage_is_reported_on_create_and_list(client: TestClient) -> None:
    created = _create(client, "s1", ["OG01", "OG02"], A_HDR).json()
    usage = created["usage"]
    assert usage["session_sets"] == 1
    assert usage["session_bytes"] == 8  # 2 x int32
    assert usage["max_bytes"] > 0
    assert usage["sessions"] >= 1

    _create(client, "s2", ["OG03"], A_HDR)
    listed = client.get("/api/fish", headers=A_HDR).json()["usage"]
    assert listed["session_sets"] == 2
    assert listed["session_bytes"] == 12
    assert listed["total_bytes"] >= listed["session_bytes"]


def test_usage_counts_only_the_callers_sets(client: TestClient) -> None:
    _create(client, "a", ["OG01", "OG02"], A_HDR)
    _create(client, "b", ["OG03"], B_HDR)
    a_usage = client.get("/api/fish", headers=A_HDR).json()["usage"]
    assert a_usage["session_sets"] == 1
    assert a_usage["session_bytes"] == 8
    # The byte budget is shared, so the total exceeds this session's share.
    assert a_usage["total_bytes"] == 12
    assert a_usage["sessions"] == 2


def test_warns_once_the_shared_budget_is_half_used(
    client: TestClient,
    app_state: AppState,
    caplog: pytest.LogCaptureFixture,
) -> None:
    app_state.fish = FishStore(max_bytes=16)  # 4 int32 entries
    with caplog.at_level("WARNING", logger="syntrack.fish"):
        _create(client, "s", ["OG01", "OG02", "OG03"], A_HDR)
    assert any("budget" in r.message and "used" in r.message for r in caplog.records)
