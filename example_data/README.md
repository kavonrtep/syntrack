# example_data/

Development / test dataset for SynTrack: 8 *Pisum sativum* (pea) pangenome assemblies with SCM BLAST tables, linked from the shared filesystem.

## Contents

- `link_data.sh` — idempotent script that (re)creates the symlinks and regenerates `genomes.csv`. Re-run whenever genomes are added/updated; edit the `GENOMES` array in-place to add entries.
- `genomes.csv` — index consumed by the loader. Columns: `genome_id,fai,SCM`.
- `<genome_id>.fai` — symlink to the assembly FASTA index.
- `<genome_id>.blast_out` — symlink to the SCM BLAST hits table.
- `example_data_source.md` — original spec for this dataset.

Symlink targets are under `/mnt/ceph/454_data/Pisum_pangenome/assemblies/<genome_id>/`. This directory is gitignored (`example_data/*.fai`, `*.blast_out`, `genomes.csv`); only the script and docs are checked in.

## Genomes (8)

| genome_id | | genome_id |
|---|---|---|
| JI1006_2026-01-19 | | JI281_2026-02-05 |
| JI15_2026-01-19 | | IPIP200731_2026-04-14 |
| IPIP201118_2026-01-27 | | IPIP200579_2026-04-14 |
| JI2822_2026-02-02 | | |
| IPIP200590_2026-02-04 | | |

Scale (JI1006 reference): 63 sequences in `.fai`, ~950k BLAST hits pre-filter.

## File formats

### `.fai` — FASTA index (samtools faidx)

Tab-separated, one row per sequence in the assembly:

```
chr1    518136898       6          60  61
chr2    539960455       526772525  60  61
chr3    751648620       1075732327 60  61
```

Columns: `name`, `length`, `byte_offset_in_fasta`, `linebases`, `linewidth`. SynTrack uses only `name` and `length`; the file-byte offsets are irrelevant to us (we compute our own cumulative genomic offsets in `GenomeStore`).

Sequence names here are pseudomolecule-level (`chr1`–`chr7`) plus unanchored scaffolds. Chromosomes are in lowercase.

### `.blast_out` — BLAST `-outfmt 6` SCM hits

Tab-separated, one row per BLAST hit of an SCM marker against the assembly:

```
Chr7__1538439-1538483   chr4   95.349  43  2  0  1  43  444158877  444158835  6.91e-11  69.8
Chr7__1548465-1548509   chr7   97.778  45  1  0  1  45  1047343    1047299    4.66e-13  77.9
```

Columns (standard `-outfmt 6`, 0-indexed):

| col | name | meaning | SynTrack use |
|---|---|---|---|
| 0 | `qseqid` | SCM marker ID | **SCM ID** — canonical across all genomes |
| 1 | `sseqid` | assembly sequence hit | **seq_name** (chromosome/scaffold) |
| 2 | `pident` | % identity | quality filter (`min_pident`, default 95) |
| 3 | `length` | alignment length (bp) | quality filter (`min_length`, default 100) |
| 4 | `mismatch` | mismatches | unused |
| 5 | `gapopen` | gap openings | unused |
| 6 | `qstart` | query start | unused |
| 7 | `qend` | query end | unused |
| 8 | `sstart` | subject start | **start** (after strand normalization) |
| 9 | `send` | subject end | **end** (after strand normalization) |
| 10 | `evalue` | e-value | quality filter (`max_evalue`, default 1e-10) |
| 11 | `bitscore` | bit score | uniqueness filter (best/second ratio) |

**Strand inference:** `sstart < send` → `+`; otherwise `−` with `start` and `end` swapped to canonical `start < end`.

**SCM ID semantics:** `qseqid` format here is `Chr<N>__<refstart>-<refend>`, where `Chr<N>` and `refstart-refend` are coordinates on the *Cameor v2 reference* probe set (see the source `0INFO.txt` in each genome's `painting_probes_CAM/all_oligos/`). SynTrack treats the full qseqid string as an opaque canonical SCM identifier — the reference-coordinate encoding is not parsed.

**Uniqueness:** the upstream BLAST was run with `-num_alignments 1`, so each query typically has a single hit per genome, but the uniqueness filter in the loader (Section 3.2.1 of the design doc) still applies to guarantee single-copy semantics.

**Filter overrides for this dataset.** The probe oligos are short (~40–47 bp), so the default `min_length=100` from `syntrack_config.example.yaml` would discard everything. Use [`example_data/syntrack_config.yaml`](syntrack_config.yaml) — it sets `min_length=30` while keeping the rest of the defaults.

### `genomes.csv` — loader index

```
genome_id,fai,SCM
JI1006_2026-01-19,JI1006_2026-01-19.fai,JI1006_2026-01-19.blast_out
...
```

`genome_id` is the directory basename from the source path. The `SCM` column holds the per-genome BLAST table filename (not a directory). Paths are resolved relative to this CSV's location.

## Refreshing the dataset

```bash
./link_data.sh
```

Script is idempotent (`ln -sfn`); it overwrites existing links and truncates/rewrites `genomes.csv`. It exits non-zero if any source file is missing, listing the offenders on stderr.
