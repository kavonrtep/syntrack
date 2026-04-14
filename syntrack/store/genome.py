"""GenomeStore — loaded from FAI files; computes cumulative offsets and palette colors."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

from syntrack.io.fai import read_fai
from syntrack.model import Genome, Sequence
from syntrack.palette import assign_colors

if TYPE_CHECKING:
    from syntrack.config import PaletteCfg
    from syntrack.io.manifest import GenomeEntry


class GenomeStore:
    """All loaded genomes plus per-genome sequence-name lookup tables."""

    __slots__ = ("_by_id", "_seq_lookup", "genomes")

    genomes: tuple[Genome, ...]
    _by_id: dict[str, Genome]
    _seq_lookup: dict[str, dict[str, Sequence]]

    def __init__(self, genomes: list[Genome]) -> None:
        ids = [g.id for g in genomes]
        if len(set(ids)) != len(ids):
            raise ValueError(f"duplicate genome ids in input: {ids}")
        self.genomes = tuple(genomes)
        self._by_id = {g.id: g for g in self.genomes}
        self._seq_lookup = {g.id: {s.name: s for s in g.sequences} for g in self.genomes}

    def __getitem__(self, genome_id: str) -> Genome:
        return self._by_id[genome_id]

    def __contains__(self, genome_id: str) -> bool:
        return genome_id in self._by_id

    def __iter__(self) -> Iterator[Genome]:
        return iter(self.genomes)

    def __len__(self) -> int:
        return len(self.genomes)

    @property
    def ids(self) -> list[str]:
        """Genome IDs in load order (same as the manifest)."""
        return [g.id for g in self.genomes]

    def get_sequence(self, genome_id: str, seq_name: str) -> Sequence:
        """Look up a Sequence by ``(genome_id, seq_name)``. Raises ``KeyError`` if absent."""
        return self._seq_lookup[genome_id][seq_name]

    @classmethod
    def load(
        cls,
        manifest: list[GenomeEntry],
        palette_cfg: PaletteCfg,
        labels: dict[str, str] | None = None,
    ) -> GenomeStore:
        """Load a GenomeStore from a parsed manifest.

        For each manifest entry: read the FAI, compute cumulative offsets in file order,
        run :func:`syntrack.palette.assign_colors` (with any per-genome overrides from
        ``palette_cfg``), and build a :class:`Genome`.

        Display label precedence (highest first): ``labels[genome_id]`` from config →
        ``manifest_entry.label`` → ``genome_id``.
        """
        labels = labels or {}
        genomes: list[Genome] = []
        for entry in manifest:
            fai_entries = read_fai(entry.fai_path)
            label = labels.get(entry.genome_id) or entry.label or entry.genome_id
            colors = assign_colors(
                fai_entries,
                distinct_top_n=palette_cfg.distinct_top_n,
                minor_color=palette_cfg.minor_color,
                overrides=palette_cfg.palette_overrides.get(entry.genome_id),
            )
            offset = 0
            sequences: list[Sequence] = []
            for name, length in fai_entries:
                sequences.append(
                    Sequence(name=name, length=length, offset=offset, color=colors[name])
                )
                offset += length
            genomes.append(
                Genome(
                    id=entry.genome_id,
                    label=label,
                    sequences=tuple(sequences),
                    total_length=offset,
                )
            )
        return cls(genomes)
