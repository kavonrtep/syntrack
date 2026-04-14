import pytest

from syntrack.api.regions import parse_region


def test_basic() -> None:
    assert parse_region("chr1:100-200") == ("chr1", 100, 200)


def test_seq_with_colon() -> None:
    assert parse_region("scaffold:1:100-200") == ("scaffold:1", 100, 200)


def test_zero_start_allowed() -> None:
    assert parse_region("chr1:0-100") == ("chr1", 0, 100)


def test_start_equals_end_allowed() -> None:
    assert parse_region("chr1:100-100") == ("chr1", 100, 100)


@pytest.mark.parametrize("bad", ["", "chr1", "chr1:", "chr1:100", "chr1:abc-def", "chr1:-100"])
def test_malformed_raises(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_region(bad)


def test_negative_coord_rejected() -> None:
    with pytest.raises(ValueError, match="invalid coords"):
        parse_region("chr1:100-50")
