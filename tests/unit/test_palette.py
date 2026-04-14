from syntrack.palette import DEFAULT_BASE_PALETTE, assign_colors


def test_top_n_get_distinct_palette_colors() -> None:
    seqs = [("chr1", 1000), ("chr2", 800), ("chr3", 500), ("chr4", 100)]
    colors = assign_colors(seqs, distinct_top_n=3, minor_color="#888")
    assert colors["chr1"] == DEFAULT_BASE_PALETTE[0]
    assert colors["chr2"] == DEFAULT_BASE_PALETTE[1]
    assert colors["chr3"] == DEFAULT_BASE_PALETTE[2]
    assert colors["chr4"] == "#888"


def test_input_order_irrelevant() -> None:
    seqs = [("c", 100), ("a", 1000), ("b", 500)]
    colors = assign_colors(seqs, distinct_top_n=3, minor_color="#888")
    assert colors == {
        "a": DEFAULT_BASE_PALETTE[0],
        "b": DEFAULT_BASE_PALETTE[1],
        "c": DEFAULT_BASE_PALETTE[2],
    }


def test_top_n_capped_at_palette_length() -> None:
    seqs = [(f"s{i}", 1000 - i) for i in range(20)]
    colors = assign_colors(seqs, distinct_top_n=999, minor_color="#888")
    distinct = {c for c in colors.values() if c != "#888"}
    assert len(distinct) == len(DEFAULT_BASE_PALETTE)
    # Sequences past the palette get the minor color
    assert colors[f"s{len(DEFAULT_BASE_PALETTE)}"] == "#888"


def test_overrides_apply_last() -> None:
    seqs = [("chr1", 1000), ("chr2", 500)]
    colors = assign_colors(
        seqs,
        distinct_top_n=2,
        minor_color="#888",
        overrides={"chr1": "#ff0000"},
    )
    assert colors["chr1"] == "#ff0000"
    assert colors["chr2"] == DEFAULT_BASE_PALETTE[1]


def test_override_for_unknown_seq_ignored() -> None:
    seqs = [("chr1", 1000)]
    colors = assign_colors(
        seqs, distinct_top_n=1, minor_color="#888", overrides={"missing": "#ff0000"}
    )
    assert colors == {"chr1": DEFAULT_BASE_PALETTE[0]}


def test_empty_input_returns_empty_dict() -> None:
    assert assign_colors([], distinct_top_n=12, minor_color="#888") == {}


def test_zero_distinct_means_all_minor() -> None:
    seqs = [("chr1", 1000), ("chr2", 500)]
    colors = assign_colors(seqs, distinct_top_n=0, minor_color="#888")
    assert colors == {"chr1": "#888", "chr2": "#888"}


def test_ties_in_length_resolved_by_input_order() -> None:
    seqs = [("a", 100), ("b", 100), ("c", 100)]
    colors = assign_colors(seqs, distinct_top_n=3, minor_color="#888")
    # stable sort preserves a, b, c order
    assert colors == {
        "a": DEFAULT_BASE_PALETTE[0],
        "b": DEFAULT_BASE_PALETTE[1],
        "c": DEFAULT_BASE_PALETTE[2],
    }
