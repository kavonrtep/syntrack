"""Lightweight performance instrumentation.

Two cooperating pieces, stdlib-only:

* :func:`timed` — a context manager that measures a labelled span. Every span
  is logged to the ``syntrack.perf`` logger and, when a request scope is active,
  accumulated into that request's timing map.
* :func:`request_timings` / :func:`server_timing_header` — let the ASGI layer
  open a per-request scope and emit a ``Server-Timing`` response header, so the
  browser DevTools → Network → Timing panel shows backend sub-timings inline.

The whole module is a no-op cost when nothing is listening: ``timed`` always
does a ``perf_counter`` pair (nanoseconds) and a dict update; it never formats
log strings unless the logger is enabled for the level.

Enable verbose span logs with ``SYNTRACK_LOG_LEVEL=DEBUG`` (see
:func:`configure_logging`). The ``Server-Timing`` header is always populated
regardless of log level.
"""

from __future__ import annotations

import contextvars
import logging
import os
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager

logger = logging.getLogger("syntrack.perf")

# Active request's {label: cumulative_ms} map, or None outside a request scope.
_request_timings: contextvars.ContextVar[dict[str, float] | None] = contextvars.ContextVar(
    "syntrack_request_timings", default=None
)


@contextmanager
def timed(label: str, **fields: object) -> Iterator[None]:
    """Measure the wrapped block and record it.

    The elapsed milliseconds are (a) added to the active request scope under
    ``label`` (summing repeats, e.g. many ``detect_blocks`` calls in one request)
    and (b) logged at DEBUG with any extra ``fields`` for context::

        with timed("derive_pair", pair=f"{g1}->{g2}", n=a.size):
            ...
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        dur_ms = (time.perf_counter() - start) * 1000.0
        scope = _request_timings.get()
        if scope is not None:
            scope[label] = scope.get(label, 0.0) + dur_ms
        if logger.isEnabledFor(logging.DEBUG):
            extra = "".join(f" {k}={v}" for k, v in fields.items())
            logger.debug("%s dur=%.1fms%s", label, dur_ms, extra)


@contextmanager
def request_timings() -> Iterator[dict[str, float]]:
    """Open a per-request timing scope. ``timed`` spans inside accumulate here."""
    scope: dict[str, float] = {}
    token = _request_timings.set(scope)
    try:
        yield scope
    finally:
        _request_timings.reset(token)


def server_timing_header(total_ms: float, scope: Mapping[str, float]) -> str:
    """Render a ``Server-Timing`` header value from a total + per-span map.

    Span labels are sanitised to the header's token grammar (alnum/_/-).
    """
    parts = [f"total;dur={total_ms:.1f}"]
    for label, dur_ms in scope.items():
        token = "".join(c if c.isalnum() or c in "_-" else "_" for c in label)
        parts.append(f"{token};dur={dur_ms:.1f}")
    return ", ".join(parts)


def configure_logging(default_level: str = "INFO") -> None:
    """Configure root logging from ``SYNTRACK_LOG_LEVEL`` (falling back to ``default_level``).

    Called once from the serve entrypoint. Set ``SYNTRACK_LOG_LEVEL=DEBUG`` to
    see every :func:`timed` span; the ``syntrack.perf`` logger inherits the root
    level. Idempotent enough for a single process start.
    """
    level_name = os.environ.get("SYNTRACK_LOG_LEVEL", default_level).upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger.setLevel(level)
