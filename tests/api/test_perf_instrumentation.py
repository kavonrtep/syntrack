"""The Server-Timing middleware must surface backend sub-timings.

This is also a propagation check: ``perf.timed`` spans run inside a sync endpoint
(executed in Starlette's threadpool), while the request scope is opened in the
async middleware. The contextvars copy across that hop is what makes the spans
land in the header — assert it actually does.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _parse_server_timing(header: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for part in header.split(","):
        name, _, rest = part.strip().partition(";")
        dur = rest.removeprefix("dur=")
        try:
            out[name] = float(dur)
        except ValueError:
            continue
    return out


def test_server_timing_header_present(client: TestClient) -> None:
    resp = client.get("/api/genomes")
    assert resp.status_code == 200
    timings = _parse_server_timing(resp.headers["Server-Timing"])
    assert "total" in timings
    assert timings["total"] >= 0.0


def test_server_timing_includes_derivation_spans(client: TestClient) -> None:
    # First blocks request for (A, B) is a cache miss -> derive_pair + detect_blocks
    # run inside the handler and must show up as Server-Timing spans.
    resp = client.get("/api/synteny/blocks", params={"g1": "A", "g2": "B"})
    assert resp.status_code == 200
    timings = _parse_server_timing(resp.headers["Server-Timing"])
    assert "derive_pair" in timings, timings
    assert "detect_blocks" in timings, timings
    # Sub-timings can't exceed the total wall time of the request.
    assert timings["derive_pair"] <= timings["total"] + 1.0
