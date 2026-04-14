"""Karyotype-agnostic palette assignment (IMPLEMENTATION_PLAN D14).

Strategy: per genome, the top-N sequences by length get distinct colors from a
base palette; the remainder collapse into a single "minor" color. Per-sequence
overrides win.
"""

from __future__ import annotations

from collections.abc import Iterable

# Visually distinct hex palette of 12 colors (Glasbey-derived).
DEFAULT_BASE_PALETTE: tuple[str, ...] = (
    "#e6194b",  # red
    "#3cb44b",  # green
    "#4363d8",  # blue
    "#f58231",  # orange
    "#911eb4",  # purple
    "#42d4f4",  # cyan
    "#f032e6",  # magenta
    "#bfef45",  # lime
    "#fabed4",  # pink
    "#469990",  # teal
    "#dcbeff",  # lavender
    "#9a6324",  # brown
)


def assign_colors(
    sequences: Iterable[tuple[str, int]],
    distinct_top_n: int,
    minor_color: str,
    overrides: dict[str, str] | None = None,
    base_palette: tuple[str, ...] = DEFAULT_BASE_PALETTE,
) -> dict[str, str]:
    """Return ``{seq_name: hex_color}`` for every input sequence.

    Args:
        sequences: ``[(name, length), ...]`` in any order.
        distinct_top_n: how many of the longest sequences receive distinct colors.
            Capped at ``len(base_palette)``.
        minor_color: fallback hex color for sequences past the top-N.
        overrides: optional ``{seq_name: hex}`` overrides — applied last, win
            against everything else.
        base_palette: ordered palette to draw distinct colors from.

    Ties in length are broken by the input order (Python's sort is stable).
    """
    overrides = overrides or {}
    palette_size = min(distinct_top_n, len(base_palette))
    by_length = sorted(sequences, key=lambda x: -x[1])

    colors: dict[str, str] = {}
    for i, (name, _length) in enumerate(by_length):
        colors[name] = base_palette[i] if i < palette_size else minor_color

    for name, color in overrides.items():
        if name in colors:
            colors[name] = color

    return colors
