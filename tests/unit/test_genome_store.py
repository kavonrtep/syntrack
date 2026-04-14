from pathlib import Path

import pytest

from syntrack.config import PaletteCfg
from syntrack.io.manifest import GenomeEntry
from syntrack.model import Genome, Sequence
from syntrack.palette import DEFAULT_BASE_PALETTE
from syntrack.store.genome import GenomeStore


def _entry(tmp_path: Path, gid: str, sequences: list[tuple[str, int]]) -> GenomeEntry:
    fai = tmp_path / f"{gid}.fai"
    fai.write_text("".join(f"{n}\t{length}\n" for n, length in sequences))
    blast = tmp_path / f"{gid}.blast"
    blast.write_text("")  # empty blast — manifest only checks existence
    return GenomeEntry(
        genome_id=gid, fai_path=fai.resolve(), blast_path=blast.resolve(), label=None
    )


def test_load_computes_offsets_and_palette(tmp_path: Path) -> None:
    entries = [_entry(tmp_path, "A", [("chr1", 1000), ("chr2", 500), ("chr3", 100)])]
    store = GenomeStore.load(entries, PaletteCfg(distinct_top_n=2, minor_color="#888"))

    [g] = store.genomes
    assert g.id == "A"
    assert g.label == "A"  # default to id
    assert g.total_length == 1600
    assert g.sequences[0].offset == 0
    assert g.sequences[1].offset == 1000
    assert g.sequences[2].offset == 1500
    # Palette: chr1 (longest) → palette[0], chr2 → palette[1], chr3 → minor
    assert g.sequences[0].color == DEFAULT_BASE_PALETTE[0]
    assert g.sequences[1].color == DEFAULT_BASE_PALETTE[1]
    assert g.sequences[2].color == "#888"


def test_label_precedence_config_over_manifest(tmp_path: Path) -> None:
    fai = tmp_path / "G.fai"
    fai.write_text("chr1\t100\n")
    blast = tmp_path / "G.blast"
    blast.write_text("")
    entries = [GenomeEntry(genome_id="G", fai_path=fai, blast_path=blast, label="manifest_label")]

    store = GenomeStore.load(entries, PaletteCfg(), labels={"G": "config_label"})
    assert store["G"].label == "config_label"


def test_label_precedence_manifest_over_id(tmp_path: Path) -> None:
    fai = tmp_path / "G.fai"
    fai.write_text("chr1\t100\n")
    blast = tmp_path / "G.blast"
    blast.write_text("")
    entries = [GenomeEntry(genome_id="G", fai_path=fai, blast_path=blast, label="manifest_label")]

    store = GenomeStore.load(entries, PaletteCfg(), labels={})
    assert store["G"].label == "manifest_label"


def test_palette_overrides_per_genome(tmp_path: Path) -> None:
    entries = [_entry(tmp_path, "A", [("chr1", 1000), ("chr2", 500)])]
    palette = PaletteCfg(
        distinct_top_n=2,
        minor_color="#888",
        palette_overrides={"A": {"chr1": "#ff0000"}},
    )
    store = GenomeStore.load(entries, palette)
    assert store["A"].sequences[0].color == "#ff0000"
    # chr2 still gets palette[1] (no override)
    assert store["A"].sequences[1].color == DEFAULT_BASE_PALETTE[1]


def test_get_sequence_lookup(tmp_path: Path) -> None:
    entries = [_entry(tmp_path, "A", [("chr1", 1000), ("chr2", 500)])]
    store = GenomeStore.load(entries, PaletteCfg())

    seq = store.get_sequence("A", "chr2")
    assert seq.name == "chr2"
    assert seq.offset == 1000


def test_get_sequence_unknown_raises(tmp_path: Path) -> None:
    entries = [_entry(tmp_path, "A", [("chr1", 100)])]
    store = GenomeStore.load(entries, PaletteCfg())
    with pytest.raises(KeyError):
        store.get_sequence("A", "nope")
    with pytest.raises(KeyError):
        store.get_sequence("nope", "chr1")


def test_iteration_and_membership(tmp_path: Path) -> None:
    entries = [
        _entry(tmp_path, "A", [("chr1", 100)]),
        _entry(tmp_path, "B", [("chr1", 100)]),
    ]
    store = GenomeStore.load(entries, PaletteCfg())
    assert store.ids == ["A", "B"]
    assert "A" in store
    assert "C" not in store
    assert len(store) == 2
    assert [g.id for g in store] == ["A", "B"]


def test_duplicate_ids_rejected() -> None:
    g = Genome(
        id="dup", label="dup", sequences=(Sequence("chr1", 100, 0, "#000"),), total_length=100
    )
    with pytest.raises(ValueError, match="duplicate genome ids"):
        GenomeStore([g, g])


def test_manifest_order_preserved(tmp_path: Path) -> None:
    entries = [
        _entry(tmp_path, "Zzz", [("chr1", 100)]),
        _entry(tmp_path, "Aaa", [("chr1", 100)]),
        _entry(tmp_path, "Mmm", [("chr1", 100)]),
    ]
    store = GenomeStore.load(entries, PaletteCfg())
    assert store.ids == ["Zzz", "Aaa", "Mmm"]
