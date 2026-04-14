"""samtools .fai parser. Returns just (name, length) — SynTrack ignores byte offsets."""

from __future__ import annotations

from pathlib import Path


def read_fai(path: Path) -> list[tuple[str, int]]:
    """Parse a `.fai` file. Returns ``[(name, length), ...]`` in file order.

    .fai format (samtools faidx): ``name<TAB>length<TAB>byte_offset<TAB>linebases<TAB>linewidth``.
    Only the first two columns are used. Blank lines and lines starting with ``#`` are skipped.

    Raises:
        ValueError: malformed line, negative length, duplicate sequence name, or empty file.
    """
    entries: list[tuple[str, int]] = []
    seen: set[str] = set()
    with path.open() as fh:
        for line_num, raw in enumerate(fh, start=1):
            line = raw.rstrip("\r\n")
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            min_fields = 2  # we only need name + length
            if len(parts) < min_fields:
                raise ValueError(
                    f"{path}:{line_num}: expected at least {min_fields} tab-separated "
                    f"fields, got {len(parts)}"
                )
            name = parts[0]
            try:
                length = int(parts[1])
            except ValueError as exc:
                raise ValueError(f"{path}:{line_num}: invalid length {parts[1]!r}") from exc
            if length < 0:
                raise ValueError(f"{path}:{line_num}: negative length {length}")
            if name in seen:
                raise ValueError(f"{path}:{line_num}: duplicate sequence name {name!r}")
            seen.add(name)
            entries.append((name, length))
    if not entries:
        raise ValueError(f"{path}: no sequence entries")
    return entries
