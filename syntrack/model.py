"""Internal dataclasses for genomes, sequences, and SCM hits.

These are plain dataclasses chosen for memory and speed; the API layer maps
them to pydantic schemas at the boundary.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Sequence:
    """One chromosome / scaffold within a genome."""

    name: str
    length: int
    offset: int
    """Cumulative length of preceding sequences in the genome — used as the base
    for converting local coordinates to a genome-global linear coordinate."""
    color: str
    """Hex color assigned by the karyotype-agnostic palette (D14)."""


@dataclass(frozen=True, slots=True)
class Genome:
    """A genome assembly: ordered sequences plus metadata."""

    id: str
    label: str
    sequences: tuple[Sequence, ...]
    total_length: int
