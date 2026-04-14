"""Parser for ``seq:start-end`` region strings used as query parameters."""

from __future__ import annotations


def parse_region(region: str) -> tuple[str, int, int]:
    """Parse ``"seq:start-end"`` into ``(seq, start, end)`` (0-based half-open).

    Sequence names may contain colons (rare); we split on the *last* colon.
    Raises ``ValueError`` on malformed input.
    """
    if ":" not in region:
        raise ValueError(f"region {region!r} missing ':'")
    seq, range_part = region.rsplit(":", 1)
    if not seq:
        raise ValueError(f"region {region!r} has empty sequence name")
    if "-" not in range_part:
        raise ValueError(f"region {region!r} missing '-' in range part {range_part!r}")
    start_str, end_str = range_part.split("-", 1)
    try:
        start = int(start_str)
        end = int(end_str)
    except ValueError as exc:
        raise ValueError(f"region {region!r} has non-integer coords") from exc
    if start < 0 or end < start:
        raise ValueError(f"region {region!r} has invalid coords (start={start}, end={end})")
    return seq, start, end
