"""genomes.csv reader — the canonical loader-input contract (D4)."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

REQUIRED_COLUMNS: tuple[str, ...] = ("genome_id", "fai", "SCM")
OPTIONAL_COLUMNS: tuple[str, ...] = ("label",)


@dataclass(frozen=True, slots=True)
class GenomeEntry:
    """One row of the manifest, with paths resolved to absolute and existence-checked."""

    genome_id: str
    fai_path: Path
    blast_path: Path
    label: str | None
    """Display label. ``None`` means use ``genome_id``."""


def read_manifest(csv_path: Path) -> list[GenomeEntry]:
    """Parse a ``genomes.csv``.

    Columns:
        genome_id (required) — opaque identifier, must be unique across rows.
        fai (required) — path to the FAI index (resolved relative to the CSV's directory).
        SCM (required) — path to the BLAST -outfmt 6 hits table.
        label (optional) — display name; empty string is treated as missing.

    Raises:
        ValueError: missing required columns, empty/duplicate genome_id, no entries.
        FileNotFoundError: a referenced fai or SCM file doesn't exist.
    """
    base = csv_path.parent
    entries: list[GenomeEntry] = []
    seen: set[str] = set()

    with csv_path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise ValueError(f"{csv_path}: empty manifest (no header)")
        missing = [c for c in REQUIRED_COLUMNS if c not in reader.fieldnames]
        if missing:
            raise ValueError(f"{csv_path}: missing required columns: {missing}")

        for line_num, row in enumerate(reader, start=2):
            genome_id = (row.get("genome_id") or "").strip()
            if not genome_id:
                raise ValueError(f"{csv_path}:{line_num}: empty genome_id")
            if genome_id in seen:
                raise ValueError(f"{csv_path}:{line_num}: duplicate genome_id {genome_id!r}")
            seen.add(genome_id)

            fai_rel = (row.get("fai") or "").strip()
            blast_rel = (row.get("SCM") or "").strip()
            if not fai_rel or not blast_rel:
                raise ValueError(f"{csv_path}:{line_num}: empty fai/SCM for genome {genome_id!r}")

            fai_path = (base / fai_rel).resolve()
            blast_path = (base / blast_rel).resolve()

            if not fai_path.exists():
                raise FileNotFoundError(
                    f"{csv_path}:{line_num}: fai not found for {genome_id!r}: {fai_path}"
                )
            if not blast_path.exists():
                raise FileNotFoundError(
                    f"{csv_path}:{line_num}: SCM table not found for {genome_id!r}: {blast_path}"
                )

            label_val = (row.get("label") or "").strip()
            entries.append(
                GenomeEntry(
                    genome_id=genome_id,
                    fai_path=fai_path,
                    blast_path=blast_path,
                    label=label_val or None,
                )
            )

    if not entries:
        raise ValueError(f"{csv_path}: no genome entries")
    return entries
