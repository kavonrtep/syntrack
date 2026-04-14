from pathlib import Path

import pytest

from syntrack.io.manifest import GenomeEntry, read_manifest


def _touch(directory: Path, *names: str) -> None:
    for n in names:
        (directory / n).write_text("")


def test_basic_manifest(tmp_path: Path) -> None:
    _touch(tmp_path, "a.fai", "a.blast", "b.fai", "b.blast")
    csv = tmp_path / "genomes.csv"
    csv.write_text("genome_id,fai,SCM\nA,a.fai,a.blast\nB,b.fai,b.blast\n")

    entries = read_manifest(csv)

    assert entries == [
        GenomeEntry(
            genome_id="A",
            fai_path=(tmp_path / "a.fai").resolve(),
            blast_path=(tmp_path / "a.blast").resolve(),
            label=None,
        ),
        GenomeEntry(
            genome_id="B",
            fai_path=(tmp_path / "b.fai").resolve(),
            blast_path=(tmp_path / "b.blast").resolve(),
            label=None,
        ),
    ]


def test_optional_label_kept(tmp_path: Path) -> None:
    _touch(tmp_path, "a.fai", "a.blast")
    csv = tmp_path / "g.csv"
    csv.write_text("genome_id,fai,SCM,label\nA,a.fai,a.blast,Genome A\n")
    entries = read_manifest(csv)
    assert entries[0].label == "Genome A"


def test_empty_label_becomes_none(tmp_path: Path) -> None:
    _touch(tmp_path, "a.fai", "a.blast")
    csv = tmp_path / "g.csv"
    csv.write_text("genome_id,fai,SCM,label\nA,a.fai,a.blast,\n")
    entries = read_manifest(csv)
    assert entries[0].label is None


def test_paths_resolved_relative_to_csv(tmp_path: Path) -> None:
    sub = tmp_path / "data"
    sub.mkdir()
    _touch(sub, "x.fai", "x.blast")
    csv = sub / "genomes.csv"
    csv.write_text("genome_id,fai,SCM\nX,x.fai,x.blast\n")
    [entry] = read_manifest(csv)
    assert entry.fai_path == (sub / "x.fai").resolve()


def test_missing_required_column_raises(tmp_path: Path) -> None:
    csv = tmp_path / "bad.csv"
    csv.write_text("genome_id,fai\nA,a.fai\n")
    with pytest.raises(ValueError, match="missing required columns"):
        read_manifest(csv)


def test_empty_genome_id_raises(tmp_path: Path) -> None:
    _touch(tmp_path, "a.fai", "a.blast")
    csv = tmp_path / "g.csv"
    csv.write_text("genome_id,fai,SCM\n,a.fai,a.blast\n")
    with pytest.raises(ValueError, match="empty genome_id"):
        read_manifest(csv)


def test_duplicate_genome_id_raises(tmp_path: Path) -> None:
    _touch(tmp_path, "a.fai", "a.blast")
    csv = tmp_path / "g.csv"
    csv.write_text("genome_id,fai,SCM\nA,a.fai,a.blast\nA,a.fai,a.blast\n")
    with pytest.raises(ValueError, match="duplicate genome_id"):
        read_manifest(csv)


def test_missing_fai_raises(tmp_path: Path) -> None:
    _touch(tmp_path, "a.blast")  # a.fai absent
    csv = tmp_path / "g.csv"
    csv.write_text("genome_id,fai,SCM\nA,a.fai,a.blast\n")
    with pytest.raises(FileNotFoundError, match="fai not found"):
        read_manifest(csv)


def test_missing_blast_raises(tmp_path: Path) -> None:
    _touch(tmp_path, "a.fai")
    csv = tmp_path / "g.csv"
    csv.write_text("genome_id,fai,SCM\nA,a.fai,a.blast\n")
    with pytest.raises(FileNotFoundError, match="SCM table not found"):
        read_manifest(csv)


def test_no_entries_raises(tmp_path: Path) -> None:
    csv = tmp_path / "empty.csv"
    csv.write_text("genome_id,fai,SCM\n")
    with pytest.raises(ValueError, match="no genome entries"):
        read_manifest(csv)


def test_no_header_raises(tmp_path: Path) -> None:
    csv = tmp_path / "noheader.csv"
    csv.write_text("")
    with pytest.raises(ValueError, match="empty manifest"):
        read_manifest(csv)


def test_empty_path_field_raises(tmp_path: Path) -> None:
    _touch(tmp_path, "a.fai")
    csv = tmp_path / "g.csv"
    csv.write_text("genome_id,fai,SCM\nA,a.fai,\n")
    with pytest.raises(ValueError, match="empty fai/SCM"):
        read_manifest(csv)


@pytest.mark.integration
def test_parse_real_genomes_csv() -> None:
    csv = Path("example_data/genomes.csv")
    if not csv.exists():
        pytest.skip("example_data not linked")
    entries = read_manifest(csv)
    assert len(entries) == 8
    ids = {e.genome_id for e in entries}
    assert "JI1006_2026-01-19" in ids
    assert all(e.fai_path.exists() and e.blast_path.exists() for e in entries)
