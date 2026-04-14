# SynTrack — Genome Synteny Visualization Tool

## Design Document v0.3

---

## 1. Problem Formulation

### 1.1 Context

Comparative genomics requires visualizing structural relationships (synteny)
between multiple genome assemblies simultaneously. Existing tools (JBrowse2
linear synteny view, SynVisio, D-GENIES) lack critical interactive features
needed for exploratory analysis of genome evolution.

Syntenic relationships are represented through **Single Copy Markers (SCMs)**
— orthologous loci present in exactly one copy per genome. SCMs have canonical
identities: a given SCM has a unique ID and a defined position in every genome
where it exists. Not all SCMs are present in all genomes (gene loss,
assembly gaps, detection limits), but where an SCM is present, its identity
and position are unambiguous.

### 1.2 Input Data Model

**Primary inputs:**
1. `.fai` files — one per genome, standard FASTA index format (sequence names
   and lengths).
2. **SCM BLAST tables** — one per genome, standard BLAST tabular output
   (`-outfmt 6`) from aligning SCM marker sequences against the genome assembly.

SCM positions are the primary experimental data, produced by BLASTing a
canonical set of SCM marker sequences against each genome assembly. Each
BLAST hit defines one SCM's position in one genome. The application ingests
these per-genome tables and builds a unified SCM position index.

This is a deliberate design choice over pairwise PAF files. The per-genome
BLAST tables are the single source of truth. Pairwise synteny information is
**derived** by intersecting the SCMs present in any two genomes. This
eliminates:
- The need for N×(N-1)/2 PAF files.
- SCM ID consistency issues — all tables reference the same marker set.
- Redundant storage of the same SCM position in multiple files.

**Per-genome BLAST table format (`-outfmt 6`):**

```
# genome: arabidopsis
# Standard BLAST -outfmt 6 columns:
# qseqid sseqid pident length mismatch gapopen qstart qend sstart send evalue bitscore
OG00012847  Chr1  99.2  1658  13  0  1  1658  1500234  1501892  0.0  3012
OG00013001  Chr1  98.7  700   9   0  1  700   1623400  1624100  0.0  1245
OG00019234  Chr2  99.5  2100  10  0  1  2100  890112   892212   0.0  3890
...
```

Key column mapping:
- `qseqid` (col 0) → SCM ID (marker name from the canonical marker set)
- `sseqid` (col 1) → sequence name in this genome (chromosome/scaffold)
- `sstart` (col 8) → start position in the genome
- `send`   (col 9) → end position in the genome
- `pident` (col 2) → used for quality filtering
- `evalue` (col 10) → used for quality filtering

Strand is inferred from sstart/send: if sstart < send → '+', else → '−'
(and coordinates are swapped to canonical start < end order).

Genome ID is derived from the filename (e.g., `arabidopsis.blast` → genome
ID `arabidopsis`).

**Filtering and validation at load time (Section 3.2.1):** BLAST output may
contain non-unique hits (SCM mapping to multiple locations in a genome,
partial hits, low-quality alignments). The loader applies configurable filters
to ensure SCM uniqueness per genome before building the index.

### 1.3 Key Data Properties

**SCM presence is genome-dependent.** An SCM present in genomes A and B may be
absent from genome C. When deriving pairwise synteny for (A,C), that SCM is
excluded. Consequence: the number of shared SCMs varies per pair. Typically,
closely related genomes share more SCMs than distant ones.

**Collinear blocks are pair-specific.** Blocks computed for pair (A,B) are
independent of blocks for pair (A,C). Block boundaries will not align across
pairs — this reflects real biology (lineage-specific rearrangements).

**SCMs cluster spatially.** SCMs are not uniformly distributed along
chromosomes. They occur in clusters corresponding to conserved syntenic
regions, with gaps at rearrangement breakpoints, repeat-rich regions, and
centromeres. This clustering enables 100–500× data reduction through block
summarization.

### 1.4 Data Scale

| Parameter                         | Typical       | Maximum       |
|-----------------------------------|---------------|---------------|
| Number of genomes                 | 5–10          | 20            |
| SCM universe size (unique SCMs)   | 200K–800K     | 1.5M          |
| SCMs per genome (after filtering) | 100K–500K     | 1.2M          |
| Raw BLAST hits per genome         | 150K–700K     | 2M+           |
| Shared SCMs per pair              | 80K–400K      | 1.2M          |
| Derived pairs (N genomes)         | 10–45         | 190           |
| Sequences per genome (fai)        | 7–50          | 500+          |
| Genome size                       | 500 Mb–5 Gb   | 20 Gb         |
| Syntenic blocks per derived pair  | 1K–10K        | 50K           |

### 1.5 Feature Requirements

**F1 — Multi-genome synteny view.**
Display N genomes as horizontal tracks (one per genome) stacked vertically.
Between each adjacent pair of tracks, draw syntenic connections (lines or
ribbons). Connections are shown only between adjacent pairs in the current
visual order. Supports whole-genome overview and region zoom.

**F2 — Interactive genome reordering.**
User can drag-reorder genome tracks. Reordering changes which pairs are
adjacent and therefore which derived pairwise synteny is visible. Pairwise
data for newly adjacent pairs is computed lazily and cached.

**F3 — Region highlight propagation.**
User selects a region on any genome track (click-drag). All SCMs within that
region are identified, and their positions in ALL other genomes are
highlighted (not limited to adjacent pairs). This enables tracing the syntenic
fate of a genomic region across the full genome set.

**F4 — In silico FISH painting.**
User defines a "paint set" by selecting a region on a genome or providing
SCM IDs. The tool maps these SCMs to their positions across all genomes and
renders colored markers on every genome track. Multiple paint sets can be
active simultaneously with distinct colors. This is not limited to adjacent
pairs — every genome that contains any of the selected SCMs shows the
painting. Simulates chromosome painting for karyotype evolution analysis.

**F5 — Visual data reduction.**
At whole-genome zoom, SCMs are aggregated into collinear blocks displayed as
ribbons. Block width/opacity encodes SCM density. On zoom-in, blocks dissolve
into individual SCM connections. Level-of-detail is driven by viewport
resolution.

---

## 2. Application Architecture

### 2.1 Architecture Decision

**Python backend (FastAPI) + JavaScript/Canvas frontend**, served locally.

Rationale:
- Python provides mature genomic interval libraries (NCLS, numpy) and fast
  tabular parsing (polars or pandas).
- Canvas rendering handles 10K+ connections at interactive frame rates.
- FastAPI serves as a lightweight local API; no external deployment needed.
- Decoupled frontend/backend allows independent iteration.
- Single-user local deployment — no auth, no database, file-based data.

### 2.2 Component Overview

```
┌─────────────────────────────────────────────────────┐
│                   Browser (Frontend)                │
│                                                     │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ Genome   │  │  Connection  │  │  Highlight /  │  │
│  │ Track    │  │  Canvas      │  │  FISH Canvas  │  │
│  │ Canvas   │  │  (ribbons/   │  │  (overlay)    │  │
│  │          │  │   lines)     │  │               │  │
│  └──────────┘  └──────────────┘  └───────────────┘  │
│  ┌─────────────────────────────────────────────┐    │
│  │  UI Controls: order, zoom, selection, FISH  │    │
│  └─────────────────────────────────────────────┘    │
└────────────────────┬────────────────────────────────┘
                     │ REST API (JSON)
┌────────────────────┴────────────────────────────────┐
│                Backend (FastAPI)                     │
│                                                     │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────┐  │
│  │ GenomeStore  │  │  SCMStore    │  │ QueryEngine│  │
│  │ (.fai data)  │  │ (pos table)  │  │ (intervals)│  │
│  └─────────────┘  └──────────────┘  └────────────┘  │
│  ┌──────────────────┐  ┌──────────────────────────┐  │
│  │  PairDeriver      │  │  BlockComputer           │  │
│  │  (pairwise join)  │  │  (collinear detection)   │  │
│  └──────────────────┘  └──────────────────────────┘  │
│  ┌─────────────────────────────────────────────┐    │
│  │  PairCache (LRU cache of derived pairs)     │    │
│  └─────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────┘
                     │
        ┌────────────┴────────────┐
        │    Local Filesystem     │
        │  *.fai files            │
        │  *.blast files          │
        │  (config.yaml)          │
        │  cache/ (optional .npz) │
        └─────────────────────────┘
```

### 2.3 Canvas Layering Strategy

Three stacked `<canvas>` elements (bottom to top):

1. **Track canvas** — genome bars segmented by chromosomes, axis labels,
   chromosome names. Redrawn only on resize or genome reorder.
2. **Connection canvas** — syntenic connections (ribbons at block level,
   lines at SCM level) between adjacent pairs only. Redrawn on reorder,
   zoom, pan.
3. **Overlay canvas** — region selection rectangle, highlight connections
   (to ALL genomes), FISH markers (on ALL genomes). Redrawn on user
   interaction.

---

## 3. Data Model

### 3.1 Core Entities

```
Genome:
    id:           str             # unique genome identifier (from fai filename)
    label:        str             # display name
    sequences:    list[Sequence]
    total_length: int

Sequence:
    name:         str             # chromosome/scaffold name
    length:       int             # from .fai
    offset:       int             # cumulative offset within genome
                                  # (for linear layout: seq positions → global coords)

SCMPosition:
    scm_id:       str             # canonical marker ID
    genome_id:    str             # which genome
    seq_name:     str             # chromosome/scaffold
    start:        int             # start position (0-based)
    end:          int             # end position (exclusive)
    strand:       str             # '+' or '-'
```

### 3.2 In-Memory Data Structures

#### 3.2.1 SCMStore (loaded at startup)

The SCM position data is loaded from per-genome BLAST tables, filtered for
quality and uniqueness, then indexed.

**Loading and filtering pipeline:**

```
For each genome BLAST file:
  1. Parse BLAST -outfmt 6 columns.
  2. Infer strand from sstart/send; normalize to start < end.
  3. Quality filter:
     - Discard hits below min_pident (default: 95.0).
     - Discard hits below min_length (default: 100 bp).
     - Discard hits above max_evalue (default: 1e-10).
  4. Uniqueness filter (per genome):
     - Group hits by SCM ID (qseqid).
     - If an SCM has exactly 1 hit → keep (single-copy confirmed).
     - If an SCM has multiple hits:
       a. If best hit is unambiguously superior (e.g., bitscore ratio
          best/second ≥ 1.5) → keep best, discard others.
       b. Otherwise → discard all hits for this SCM in this genome
          (not reliably single-copy).
     - Log discarded SCMs with reason (multi-copy, low quality) for
       user review.
  5. Validate against .fai:
     - seq_name must exist in the genome's .fai.
     - Coordinates must be within [0, seq_length).
     - Mismatches → warning + discard hit.
  6. Store validated hits in per-genome numpy array.
```

**Filtering statistics** are reported at startup and available via API:

```
Genome: arabidopsis
  Raw BLAST hits:        523,401
  After quality filter:  498,212
  After uniqueness:      342,891  (discarded 155,321 multi-copy/ambiguous)
  After validation:      342,891
  Final SCM count:       342,891
```

**In-memory structures after loading:**

```
Per-genome index:
    genome_positions[genome_id] → numpy structured array, sorted by offset
    Fields: [scm_id_idx, seq_idx, start, end, strand, offset]

    - offset = sequence cumulative offset + start (global linear coordinate)
    - scm_id_idx = integer index into global SCM ID string table
    - seq_idx = integer index into genome's sequence name table
    - Sorted by offset for binary search range queries

Global SCM lookup:
    scm_to_genomes[scm_id_idx] → list of (genome_id, offset, seq_idx, start, end, strand)

    Purpose: given an SCM ID, find its position in every genome.
    This powers FISH painting (F4) and highlight propagation (F3).
    Built once at startup by scanning all validated per-genome arrays.

SCM presence matrix (lightweight):
    scm_genome_matrix[scm_id_idx] → set of genome_ids

    Purpose: fast pair intersection count (how many SCMs shared
    between two genomes) without materializing the full join.
    Useful for /api/pairs summary statistics.
```

**Memory estimate:**

```python
scm_pos_dtype = np.dtype([
    ('scm_id_idx', np.int32),     # index into SCM name table
    ('seq_idx',    np.int16),     # index into sequence name table
    ('start',      np.int64),     # local start position
    ('end',        np.int64),     # local end position
    ('strand',     np.int8),      # +1 or -1
    ('offset',     np.int64),     # global linear coordinate
])
# 30 bytes per row
# 1.2M SCMs × 15 genomes (avg) = 18M rows × 30 bytes ≈ 540 MB
# 1.2M SCMs × 5 genomes (avg)  = 6M rows × 30 bytes  ≈ 180 MB
```

If memory is tight, the SCM ID string table can use integer hashing instead
of storing strings. With 1.5M unique SCMs, a 4-byte integer index is
sufficient.

#### 3.2.2 PairwiseSynteny (derived on demand)

When a genome pair becomes adjacent in the view, the backend derives their
shared synteny:

```
Derivation: inner join of genome_positions[g1] and genome_positions[g2]
            on scm_id_idx → produces array of shared SCMs with positions
            in both genomes.

PairwiseSCM:
    Fields: [scm_id_idx, g1_offset, g2_offset, g1_seq_idx, g2_seq_idx,
             strand_g1, strand_g2]
    Derived strand: relative_strand = strand_g1 × strand_g2

    Sorted by g1_offset for range queries on genome 1.
    Secondary sorted copy by g2_offset for reverse queries.
```

**Derivation cost:**

```
Time:  sorted merge join on scm_id_idx, O(n + m) where n, m are the
       SCM counts in each genome. For 1.2M × 1.2M: ~0.1–0.3s in numpy.
Memory: ~50 bytes × shared_count per pair. For 500K shared: ~25 MB.
```

#### 3.2.3 SyntenyBlocks (derived from PairwiseSynteny)

Collinear blocks are computed from PairwiseSCM after derivation.

```
SyntenyBlock:
    block_id:     int
    g1_seq:       str
    g1_start:     int
    g1_end:       int
    g2_seq:       str
    g2_start:     int
    g2_end:       int
    strand:       str          # relative strand (predominant)
    scm_count:    int
```

#### 3.2.4 PairCache

```
Strategy: LRU cache of derived PairwiseSynteny + SyntenyBlocks.
Capacity: configurable, default 30 pairs (~750 MB at 500K SCMs/pair).
Eviction: least recently accessed pair.
Optional: write derived pairs to disk as .npz files for fast reload.
```

### 3.3 Collinear Block Detection

Blocks represent runs of SCMs that are in the **same order** in both genomes,
within a maximum distance. The algorithm is strict about order preservation
to avoid generating large, sparse blocks that conflate independent syntenic
regions.

**Algorithm:**

```
Input:  PairwiseSCM array (shared SCMs between g1 and g2)
Output: list of SyntenyBlocks

1. Sort PairwiseSCM by g1_offset (position in genome 1).

2. Initialize: current_block = [first SCM]

3. For each subsequent SCM_i (in g1_offset order):

   a. Check STRAND continuity:
      - SCM_i must have the same relative_strand as previous SCM in block.

   b. Check SEQUENCE continuity:
      - SCM_i must be on the same g1_seq AND g2_seq as previous SCM.

   c. Check DISTANCE in both genomes:
      - g1_gap = SCM_i.g1_offset - prev.g1_offset
      - g2_gap = abs(SCM_i.g2_offset - prev.g2_offset)
      - Both must be ≤ max_gap (default: 1 Mb).

   d. Check ORDER preservation (strict collinearity):
      - For + strand: SCM_i.g2_offset > prev.g2_offset
        (g2 positions must be monotonically increasing)
      - For − strand: SCM_i.g2_offset < prev.g2_offset
        (g2 positions must be monotonically decreasing)

   e. If ALL conditions (a–d) met: append SCM_i to current_block.
      Otherwise: close current_block, start new block with SCM_i.

4. After scan, close final block.

5. Filter: discard blocks with scm_count < min_block_size (default: 3).
   This eliminates noise from spurious 1–2 SCM "blocks."
```

**Why strict order matters:** Without the order check (step 3d), two SCMs on
the same chromosomes in both genomes but in reversed order would be merged
into one block if they're within max_gap. This produces a misleadingly large
block that actually spans a rearrangement breakpoint. The strict order
constraint ensures each block represents a genuinely collinear segment.

**Complexity:** O(n log n) for the initial sort; O(n) for the scan.

**Tuning parameters:**

| Parameter        | Default  | Effect of increasing                          |
|------------------|----------|-----------------------------------------------|
| `max_gap`        | 1 Mb     | Larger blocks, may bridge small rearrangements|
| `min_block_size` | 3 SCMs   | Fewer blocks, only well-supported ones remain |

Both parameters are exposed via the UI and API. Changing them triggers
re-computation of blocks only (the underlying PairwiseSCM data is retained).

**Development plan for parameter tuning:** During development, the following
diagnostics will be implemented to find robust defaults:

- Block count vs. max_gap curve (sweep max_gap from 100 kb to 10 Mb).
- Distribution of block sizes (SCM count per block) as histogram.
- Fraction of SCMs assigned to blocks vs. "orphaned" (below min_block_size).
- Visual inspection overlay: show block boundaries on the synteny view to
  verify they correspond to biological breakpoints.

These diagnostics will be available as a developer/tuning panel in the UI
and as CLI commands for batch analysis across multiple genome pairs.

### 3.4 Data Pipeline Overview

```
    ┌────────────────────┐    ┌────────────────────┐
    │  Per-genome BLAST  │    │  Per-genome .fai    │
    │  tables (-outfmt 6)│    │  files              │
    └─────────┬──────────┘    └─────────┬───────────┘
              │                         │
              ▼                         ▼
    ┌────────────────────┐    ┌────────────────────┐
    │  Quality filter    │    │  GenomeStore        │
    │  (pident, evalue,  │    │  (sequences,offsets)│
    │   length)          │    └─────────┬───────────┘
    └─────────┬──────────┘              │
              ▼                         │
    ┌────────────────────┐              │
    │  Uniqueness filter │              │
    │  (1 hit per SCM    │              │
    │   per genome)      │              │
    └─────────┬──────────┘              │
              ▼                         │
    ┌────────────────────┐              │
    │  Validate vs .fai  │◄─────────────┘
    │  (seq names, bounds)│
    └─────────┬──────────┘
              │ startup complete
              ▼
    ┌────────────────────┐
    │  SCMStore           │   genome_positions[genome_id]
    │  (per-genome arrays │   scm_to_genomes[scm_id_idx]
    │   + global lookup)  │   filtering_stats[genome_id]
    └─────────┬──────────┘
              │ on-demand (pair becomes adjacent or highlight/FISH)
              ▼
    ┌────────────────────┐
    │  PairwiseSynteny   │   merge join on scm_id_idx
    │  (shared SCMs)     │   ~0.1-0.3s per pair
    └─────────┬──────────┘
              │ immediate
              ▼
    ┌────────────────────┐
    │  SyntenyBlocks     │   collinear scan (strict order)
    │                    │   ~0.05s per pair
    └─────────┬──────────┘
              │
              ▼
    ┌────────────────────┐
    │  PairCache (LRU)   │   in-memory + optional .npz
    └────────────────────┘
```

### 3.5 Pre-computation Option

For repeated use with the same dataset, a CLI command can pre-compute all
pairs and write to disk:

```bash
syntrack precompute --data-dir ./data --output-dir ./data/cache
```

This produces:
- `{g1}_{g2}_scms.npz` — PairwiseSCM array for each pair
- `{g1}_{g2}_blocks.npz` — SyntenyBlock array for each pair
- `pair_manifest.json` — metadata (SCM counts, block params used)

On startup, if cache files exist and match current config, they are loaded
instead of re-derived. Block parameters embedded in the manifest enable
cache invalidation when parameters change.

---

## 4. API Design

### 4.1 Session Lifecycle

On startup:
1. Scan data directory for .fai files → build GenomeStore.
2. Scan BLAST directory for per-genome tables → parse, filter, validate →
   build SCMStore. Log filtering statistics per genome.
3. If pre-computed cache exists and is valid → load into PairCache.
4. Start FastAPI server.

On genome reorder:
1. Identify newly adjacent pairs not in PairCache.
2. Derive pairwise synteny + blocks (background task).
3. Return data when ready (frontend shows loading indicator).

### 4.2 Endpoints

#### `GET /api/genomes`

Returns list of available genomes with sequence information, SCM statistics,
and BLAST filtering summary.

```json
{
  "genomes": [
    {
      "id": "arabidopsis",
      "label": "A. thaliana Col-0",
      "total_length": 119668634,
      "scm_count": 342891,
      "filtering": {
        "raw_hits": 523401,
        "after_quality": 498212,
        "after_uniqueness": 342891,
        "discarded_multicopy": 148302,
        "discarded_quality": 25189,
        "discarded_validation": 0
      },
      "sequences": [
        {"name": "Chr1", "length": 30427671, "offset": 0},
        {"name": "Chr2", "length": 19698289, "offset": 30427671}
      ]
    }
  ],
  "scm_universe_size": 1248003
}
```

#### `GET /api/pairs`

Returns all possible genome pairs with derivation status.

```json
{
  "pairs": [
    {
      "genome1_id": "arabidopsis",
      "genome2_id": "lyrata",
      "shared_scm_count": 298451,
      "block_count": 4521,
      "derived": true,
      "cached_on_disk": true
    }
  ]
}
```

#### `GET /api/synteny/blocks`

Block-level synteny for a genome pair. Triggers pair derivation if not cached.

Parameters:
- `g1` (required): genome 1 ID
- `g2` (required): genome 2 ID
- `region_g1` (optional): restrict to region, format `seq:start-end`
- `region_g2` (optional): restrict to region in g2
- `min_scm` (optional): minimum SCMs per block

Response:
```json
{
  "pair": ["arabidopsis", "lyrata"],
  "shared_scm_count": 298451,
  "block_count": 4521,
  "blocks": [
    {
      "block_id": 1,
      "g1_seq": "Chr1", "g1_start": 1000, "g1_end": 450000,
      "g2_seq": "scaffold_3", "g2_start": 890000, "g2_end": 1320000,
      "strand": "+",
      "scm_count": 127
    }
  ]
}
```

#### `GET /api/synteny/scms`

SCM-level synteny for a genome pair within a region. Used for zoomed view.

Parameters:
- `g1`, `g2` (required): genome IDs
- `region_g1` (optional): region in g1
- `region_g2` (optional): region in g2
- `limit` (optional): max SCMs to return (uniform downsampling if exceeded)

Response:
```json
{
  "pair": ["arabidopsis", "lyrata"],
  "scms": [
    {
      "scm_id": "OG00012847",
      "g1_seq": "Chr1", "g1_start": 1500234, "g1_end": 1501892,
      "g2_seq": "scaffold_3", "g2_start": 891023, "g2_end": 892501,
      "strand": "+"
    }
  ],
  "total_in_region": 3421,
  "returned": 1000,
  "downsampled": true
}
```

#### `POST /api/highlight`

Region highlight propagation. Given a region on one genome, find all SCMs in
that region and return their positions across ALL other genomes.

This operates directly on the SCMStore (not on derived pairs), so it works
for all genomes regardless of whether pairs have been derived.

Request:
```json
{
  "genome_id": "arabidopsis",
  "region": "Chr1:1000000-5000000"
}
```

Response:
```json
{
  "source": {
    "genome_id": "arabidopsis",
    "region": "Chr1:1000000-5000000",
    "scm_count": 1423
  },
  "targets": [
    {
      "genome_id": "lyrata",
      "scm_count": 1389,
      "positions": [
        {"scm_id": "OG00012847", "seq": "scaffold_3",
         "start": 891023, "end": 892501, "strand": "+"}
      ]
    },
    {
      "genome_id": "capsella",
      "scm_count": 1102,
      "positions": [...]
    }
  ]
}
```

Implementation:
1. Binary search genome_positions[source] for SCMs in the region → get scm_id_idx set.
2. For each scm_id_idx, lookup scm_to_genomes → get positions in all other genomes.
3. Group by target genome, return.

Note: target genomes will have different scm_counts because SCM presence
varies. This is expected and should be rendered transparently.

#### `POST /api/fish`

In silico FISH painting. Maps SCM IDs to positions across all genomes.

Request (by SCM IDs):
```json
{
  "scm_ids": ["OG00012847", "OG00013001", "OG00019234"],
  "color": "#FF4444",
  "label": "FISH_set_1"
}
```

Request (by source region — backend extracts SCM IDs):
```json
{
  "source_genome": "arabidopsis",
  "source_region": "Chr1:1000000-5000000",
  "color": "#FF4444",
  "label": "Chr1_proximal"
}
```

Response:
```json
{
  "label": "Chr1_proximal",
  "color": "#FF4444",
  "scm_count": 1423,
  "genome_coverage": {
    "arabidopsis": 1423,
    "lyrata": 1389,
    "capsella": 1102,
    "brassica": 987
  },
  "positions": {
    "arabidopsis": [
      {"scm_id": "OG00012847", "seq": "Chr1", "start": 1500234, "end": 1501892}
    ],
    "lyrata": [
      {"scm_id": "OG00012847", "seq": "scaffold_3", "start": 891023, "end": 892501}
    ]
  }
}
```

Implementation: identical to highlight but with arbitrary SCM set as input
instead of region-derived set. Both use scm_to_genomes lookup.

#### `GET /api/scm/{scm_id}`

Lookup a single SCM across all genomes. Useful for tooltips and debugging.

```json
{
  "scm_id": "OG00012847",
  "present_in": 15,
  "positions": [
    {"genome_id": "arabidopsis", "seq": "Chr1", "start": 1500234, "end": 1501892, "strand": "+"},
    {"genome_id": "lyrata", "seq": "scaffold_3", "start": 891023, "end": 892501, "strand": "+"}
  ]
}
```

#### `GET /api/config`

Returns current configuration (block detection, rendering defaults).

#### `PUT /api/config`

Update block detection parameters. Triggers re-computation of blocks for
all cached pairs (PairwiseSCM data is retained; only blocks are recomputed).

#### `POST /api/precompute`

Trigger pre-computation of all pairs (or a subset). Returns job status.

```json
{
  "pairs": "all",
  "write_cache": true
}
```

#### `GET /api/export/scm_ids`

Export SCM IDs from a region or FISH set as a plain text list.

Parameters:
- `genome_id` + `region` (region-based), OR
- `scm_ids` (explicit list, e.g., from a FISH set)
- `format`: `txt` (one ID per line) or `json`

Response (txt): plain text, one SCM ID per line.

#### `GET /api/export/bed`

Export SCM positions as BED format for a genome, optionally filtered to
a region or SCM ID set.

Parameters:
- `genome_id` (required)
- `region` (optional): restrict to region
- `scm_ids` (optional): restrict to specific SCMs (e.g., from FISH set)

Response:
```
# BED format: chrom  start  end  name  score  strand
Chr1	1500234	1501892	OG00012847	0	+
Chr1	1623400	1624100	OG00013001	0	+
Chr2	890112	892212	OG00019234	0	+
```

#### `GET /api/export/blocks`

Export synteny blocks for a pair as TSV.

Parameters:
- `g1`, `g2` (required): genome pair

Response:
```
# block_id  g1_seq  g1_start  g1_end  g2_seq  g2_start  g2_end  strand  scm_count
1	Chr1	1000	450000	scaffold_3	890000	1320000	+	127
2	Chr1	520000	890000	scaffold_5	100000	470000	-	89
```

#### `GET /api/stats/blocks`

Block detection diagnostics for parameter tuning.

Parameters:
- `g1`, `g2` (required): genome pair
- `max_gap_sweep` (optional): comma-separated list of max_gap values to test

Response:
```json
{
  "pair": ["arabidopsis", "lyrata"],
  "shared_scm_count": 298451,
  "current_params": {"max_gap": 1000000, "min_block_size": 3},
  "current_stats": {
    "block_count": 4521,
    "scms_in_blocks": 285102,
    "orphaned_scms": 13349,
    "orphan_fraction": 0.045,
    "block_size_histogram": [[3,5,1200], [6,10,980], [11,50,1540], [51,200,650], [201,1000,148], [1001,5000,3]],
    "block_span_histogram_mb": [[0,0.1,890], [0.1,0.5,1800], [0.5,1,1100], [1,5,700], [5,50,31]]
  },
  "sweep": [
    {"max_gap": 100000, "block_count": 8921, "orphan_fraction": 0.12},
    {"max_gap": 500000, "block_count": 5102, "orphan_fraction": 0.06},
    {"max_gap": 1000000, "block_count": 4521, "orphan_fraction": 0.045},
    {"max_gap": 5000000, "block_count": 3200, "orphan_fraction": 0.02},
    {"max_gap": 10000000, "block_count": 2890, "orphan_fraction": 0.015}
  ]
}
```

---

## 5. Frontend Design

### 5.1 Layout

```
┌─────────────────────────────────────────────────────────┐
│  Toolbar: [FISH palette] [Block params] [Export] [Help] │
├─────────────────────────────────────────────────────────┤
│  ☰ Genome A  │  ═══╤══════════╤════════╤═══════════     │
│  (drag)      │  Chr1  Chr2    Chr3     Chr4             │
│              │                                           │
│              │  ╲╲╲  ╱╱╱  ╲╲╲╲  ╱╱   ← adj. synteny   │
│              │  ╲╲╲╱╱╱╱  ╲╲╲╲╱╱╱╱                      │
│              │                                           │
│  ☰ Genome B  │  ═══╤══════════╤════════╤═══════════     │
│  (drag)      │  ScfA   ScfB      ScfC    ScfD           │
│              │                                           │
│              │  ╱╱╱  ╲╲╲  ╱╱╱╱  ╲╲   ← adj. synteny   │
│              │                                           │
│  ☰ Genome C  │  ═══╤══════════╤════════╤═══════════     │
│              │  chr1    chr2      chr3                    │
├─────────────────────────────────────────────────────────┤
│  [Zoom slider]  [Region: Chr1:1.2M-4.5M]  [SCM info]   │
└─────────────────────────────────────────────────────────┘

FISH overlay (on all tracks, not just adjacent):
│  ☰ Genome A  │  ═══╤████══════╤════════╤═══════════     │
│  ☰ Genome B  │  ═══╤══════╤███════╤═══════════          │
│  ☰ Genome C  │  ═══╤══════════╤════╤███═══════          │
                      ████ = FISH paint (all genomes)
```

### 5.2 Interaction Model

**Zoom/Pan:**
- Mouse wheel zooms centered on cursor (horizontal genomic axis only).
- Click-drag on empty area pans horizontally.
- Vertical layout (track height, connection band height) is fixed.
- Zoom triggers level-of-detail transition and data re-request.

**Genome reorder (F2):**
- Drag ☰ handle up/down to reorder.
- On drop: update track positions, request synteny for newly adjacent pairs.
- If pair not yet derived: show loading indicator, derive in background.
- Previously derived pairs served from PairCache.

**Region selection and highlight (F3):**
- Click-drag on genome track creates selection.
- On mouse-up: send to `POST /api/highlight`.
- Overlay canvas renders:
  - Source region: colored rectangle.
  - Target positions: colored ticks on ALL genome tracks.
  - Adjacent-pair connections from highlighted SCMs drawn prominently;
    non-highlighted connections dimmed.
- Highlight persists until cleared or new selection made.

**FISH painting (F4):**
- Toolbar FISH palette: create sets by region selection or SCM ID list.
- Each set: distinct color, toggle on/off, delete.
- FISH markers render on ALL genome tracks (overlay canvas).
- Multiple sets simultaneously — distinct colors.
- Not limited to adjacent pairs: FISH paints are genome-level markers,
  independent of the pair-based synteny connections.

### 5.3 Level-of-Detail Rendering

```
pixels_per_bp = canvas_width / visible_genomic_range

if pixels_per_bp < BLOCK_THRESHOLD:
    render blocks as ribbons (width ∝ block span, opacity ∝ SCM density)
    request: GET /api/synteny/blocks?g1=...&g2=...
else:
    render individual SCMs as lines
    request: GET /api/synteny/scms?g1=...&g2=...&region=...&limit=5000
```

BLOCK_THRESHOLD ≈ 1/50000 (one pixel per 50 kb), configurable.
MAX_VISIBLE_SCMS ≈ 5000 — server downsamples uniformly if exceeded.

### 5.4 Color Encoding

- **Syntenic connections (adjacent pairs):** colored by target chromosome
  to show which regions of one genome correspond to which chromosomes of
  the neighbor. Standard karyotype palette (12–20 colors).
  Strand: + = parallel ribbon, − = crossed ribbon.
- **Highlight markers/connections:** single accent color, user-configurable.
- **FISH paint sets:** user-defined palette, distinct per set.
- **Dimming:** non-highlighted connections drop to opacity 0.05–0.1.

---

## 6. Implementation Plan

### Phase 1 — Data Layer (Backend MVP)

- [ ] Project scaffolding: FastAPI app, config loader (YAML), CLI entry point
- [ ] FAI parser → GenomeStore (sequence names, lengths, cumulative offsets)
- [ ] BLAST table parser with configurable quality filters
- [ ] Uniqueness filter with logging (per-genome SCM deduplication)
- [ ] Validation against .fai (seq names, coordinate bounds)
- [ ] SCMStore: per-genome arrays, global SCM lookup, filtering stats
- [ ] Pair derivation: merge join on scm_id_idx → PairwiseSynteny
- [ ] Block detection: strict collinear scan → SyntenyBlocks
- [ ] PairCache with LRU eviction
- [ ] API: `/genomes`, `/pairs`, `/synteny/blocks`, `/synteny/scms`
- [ ] Unit tests with synthetic BLAST data (known filtering outcomes,
      known block structure, known pair intersections)

### Phase 2 — Core Frontend (MVP)

- [ ] Three-layer canvas setup
- [ ] Genome track renderer (chromosome bars from .fai)
- [ ] Block ribbon renderer (between adjacent tracks)
- [ ] Zoom/pan (mouse wheel + drag)
- [ ] Genome reorder (drag-and-drop with loading state)
- [ ] Level-of-detail: block ↔ SCM transition
- [ ] API client with request debouncing

### Phase 3 — Highlight & FISH

- [ ] Region selection UI (click-drag on track)
- [ ] `POST /api/highlight` endpoint
- [ ] Overlay canvas: highlight markers + emphasized connections
- [ ] FISH palette UI (create/manage/toggle/color sets)
- [ ] `POST /api/fish` endpoint
- [ ] FISH overlay rendering on all tracks

### Phase 4 — Tuning, Export & Polish

- [ ] Block diagnostics endpoint (`/api/stats/blocks`) with parameter sweep
- [ ] Block parameter tuning UI (sliders for max_gap, min_block_size)
- [ ] Export endpoints: SCM IDs (txt), BED, block TSV
- [ ] Pre-computation CLI: `syntrack precompute`
- [ ] .npz cache read/write with manifest validation
- [ ] Export: SVG/PNG of current view
- [ ] Tooltips: hover on block → details; hover on SCM → cross-genome info
- [ ] Request debouncing and cancellation on rapid zoom/pan
- [ ] Filtering stats display in UI (per-genome loading summary)

---

## 7. Configuration

```yaml
# syntrack_config.yaml
data:
  fai_dir: ./data/fai              # directory containing .fai files
  blast_dir: ./data/blast          # directory containing per-genome BLAST tables
  blast_pattern: "*.blast"         # glob for BLAST files (filename = genome_id)
  cache_dir: ./data/cache          # pre-computed pair cache (optional)

# Optional: override genome labels (default: derived from BLAST filename)
genome_labels:
  arabidopsis: "A. thaliana Col-0"
  lyrata: "A. lyrata"
  capsella: "C. rubella"

# BLAST hit filtering (applied at load time)
blast_filtering:
  min_pident: 95.0                 # minimum percent identity
  min_length: 100                  # minimum alignment length (bp)
  max_evalue: 1.0e-10              # maximum e-value
  uniqueness_ratio: 1.5            # bitscore ratio best/second for ambiguous SCMs
                                   # set to 0 to discard all multi-hit SCMs

block_detection:
  max_gap: 1_000_000              # max gap in either genome to merge into block
  min_block_size: 3               # minimum consecutive collinear SCMs per block

pair_cache:
  max_pairs: 30                    # LRU cache capacity
  write_npz: true                  # persist derived pairs to disk

server:
  host: 127.0.0.1
  port: 8765

rendering_defaults:
  block_threshold_bp_per_px: 50000
  max_visible_scms: 5000
  connection_opacity: 0.3
  highlight_opacity: 0.8
  dimmed_opacity: 0.05
```

---

## 8. Open Questions and Future Considerations

### Resolved from v0.1/v0.2

- ~~PAF field mapping~~ — eliminated; BLAST -outfmt 6 has well-defined columns.
- ~~SCM ID consistency~~ — all BLAST tables reference the same marker set.
- ~~Non-adjacent pairs~~ — synteny connections: adjacent only. FISH/highlight:
  all genomes.
- ~~Circular genomes~~ — out of scope.
- ~~Input format~~ — per-genome BLAST tables (primary data) replace PAF/TSV.

### Remaining

1. **BLAST table variants.** Some users may have custom BLAST formats or
   additional columns (e.g., `qcovs`). The parser should handle standard
   `-outfmt 6` as default but allow column mapping override in config for
   non-standard formats.
COMMENT - standard blast 6 format is used

2. **Block parameter tuning.** The `/api/stats/blocks` endpoint and sweep
   diagnostics will be used during development to find robust defaults.
   Goal: defaults that work well across closely related species (e.g.,
   within a genus) and more distant comparisons (across family). May need
   to expose per-pair parameter overrides if one default doesn't fit all.

3. **Memory ceiling.** 20 genomes × 1.2M SCMs each, ~15 genome average
   coverage: ~540 MB for SCMStore + 30 cached pairs × 25 MB = ~1.3 GB.
   Comfortable on 16+ GB workstations. For constrained environments,
   numpy.memmap is a fallback option.

COMMENT - hagher memory usage is ok, and memmap is not needed at this scale.

4. **Export functionality.** BED export and SCM ID lists confirmed as
   requirements. Block export as TSV also included. Future: GFF3 export
   of blocks as syntenic features, PAF export of derived pairwise data
   for compatibility with other tools.

5. **Sequence reordering within genome.** Not in initial release but
   architecture supports it — recomputing sequence offsets in GenomeStore
   and re-triggering block derivation for affected pairs. UI design TBD.

6. **Uniqueness edge cases.** The BLAST uniqueness filter (Section 3.2.1)
   handles the common case but edge cases may arise: SCMs with two
   near-equal hits due to recent tandem duplication, SCMs mapping to
   unplaced scaffolds that are actually the same region as a chromosomal
   hit, etc. The filtering log should make these transparent so users can
   adjust thresholds or manually curate the filter output.

7. **SCM marker set management.** The current design assumes the marker set
   is fixed. If users want to compare results with different marker sets
   (e.g., different ortholog detection stringencies), the config would need
   to support multiple BLAST directories or a session-level marker set
   selector. Deferred.
