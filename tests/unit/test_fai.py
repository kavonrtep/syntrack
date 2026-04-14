from pathlib import Path

import pytest

from syntrack.io.fai import read_fai


def test_basic_parse(tmp_path: Path) -> None:
    fai = tmp_path / "test.fai"
    fai.write_text("chr1\t100\t6\t60\t61\nchr2\t200\t...\t60\t61\n")
    assert read_fai(fai) == [("chr1", 100), ("chr2", 200)]


def test_only_two_columns_required(tmp_path: Path) -> None:
    fai = tmp_path / "test.fai"
    fai.write_text("chr1\t100\nchr2\t200\n")
    assert read_fai(fai) == [("chr1", 100), ("chr2", 200)]


def test_skips_blank_and_comment_lines(tmp_path: Path) -> None:
    fai = tmp_path / "test.fai"
    fai.write_text("# header comment\nchr1\t100\n\n# mid comment\nchr2\t200\n")
    assert read_fai(fai) == [("chr1", 100), ("chr2", 200)]


def test_handles_crlf_line_endings(tmp_path: Path) -> None:
    fai = tmp_path / "test.fai"
    fai.write_bytes(b"chr1\t100\r\nchr2\t200\r\n")
    assert read_fai(fai) == [("chr1", 100), ("chr2", 200)]


def test_too_few_fields_raises(tmp_path: Path) -> None:
    fai = tmp_path / "test.fai"
    fai.write_text("chr1\nchr2\t200\n")
    with pytest.raises(ValueError, match="at least 2"):
        read_fai(fai)


def test_invalid_length_raises(tmp_path: Path) -> None:
    fai = tmp_path / "test.fai"
    fai.write_text("chr1\tNOT_A_NUMBER\n")
    with pytest.raises(ValueError, match="invalid length"):
        read_fai(fai)


def test_negative_length_raises(tmp_path: Path) -> None:
    fai = tmp_path / "test.fai"
    fai.write_text("chr1\t-100\n")
    with pytest.raises(ValueError, match="negative length"):
        read_fai(fai)


def test_zero_length_allowed(tmp_path: Path) -> None:
    fai = tmp_path / "test.fai"
    fai.write_text("chr1\t0\n")
    assert read_fai(fai) == [("chr1", 0)]


def test_duplicate_name_raises(tmp_path: Path) -> None:
    fai = tmp_path / "test.fai"
    fai.write_text("chr1\t100\nchr1\t200\n")
    with pytest.raises(ValueError, match="duplicate sequence name"):
        read_fai(fai)


def test_empty_file_raises(tmp_path: Path) -> None:
    fai = tmp_path / "empty.fai"
    fai.write_text("")
    with pytest.raises(ValueError, match="no sequence entries"):
        read_fai(fai)


def test_only_comments_raises(tmp_path: Path) -> None:
    fai = tmp_path / "comments.fai"
    fai.write_text("# only\n# comments\n")
    with pytest.raises(ValueError, match="no sequence entries"):
        read_fai(fai)


@pytest.mark.integration
def test_parse_real_pea_fai() -> None:
    fai = Path("example_data/JI1006_2026-01-19.fai")
    if not fai.exists():
        pytest.skip("example_data not linked; run example_data/link_data.sh")
    entries = read_fai(fai)
    assert len(entries) >= 7  # at least 7 chromosomes
    assert all(length > 0 for _, length in entries)
    names = {n for n, _ in entries}
    assert "chr1" in names
