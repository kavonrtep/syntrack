# SynTrack

Genome synteny visualization tool for comparative genomics. Displays N genomes as stacked tracks with syntenic connections between adjacent pairs, supports interactive reordering, cross-genome region highlighting, and in silico FISH painting.

Authoritative docs:
- `docs/DESIGN_v03.md` — what we build (data model, algorithms, API contract).
- `docs/IMPLEMENTATION_PLAN.md` — how we build it (stack, repo layout, phased tasks, decisions D1–D16).

When the two conflict, the design wins; the plan is updated.

## Status

Planning complete. Decisions D1–D16 fixed. **v0.1 = Phases 1 + 2** (backend MVP + browse-only viewer with reorder & ribbons; no highlight, no FISH, no exports). Scaffolding is the next concrete step.

## Stack (per IMPLEMENTATION_PLAN §0)

- **Backend:** Python 3.12, `uv` venv, FastAPI, polars (BLAST/FAI parsing), numpy structured arrays, typer CLI, pydantic v2.
- **Frontend:** Svelte 5 + Vite + TypeScript, raw HTML Canvas (three layers: track / connection / overlay), no charting library.
- **Tooling:** ruff (lint+format), mypy --strict on `syntrack/`, pytest + pytest-benchmark, vitest. Playwright deferred past v0.1.
- **Config:** YAML (`syntrack_config.yaml`).
- **Loader input:** `genomes.csv` with columns `genome_id,fai,SCM[,label]`, paths relative to the CSV. (Supersedes the dir-scan / `blast_pattern` form in design §7.)

## Core Domain Model

- **SCM (Single Copy Marker):** orthologous locus present in ≤1 copy per genome. Canonical ID, unambiguous position where present. SCMs are the unit of synteny.
- **Primary inputs:** per-genome `.fai` files + per-genome BLAST tables (`-outfmt 6`). Filename stem = genome ID. BLAST tables are single source of truth; pairwise synteny is **derived**, never stored as PAF.
- **Pairwise synteny** is derived on demand by inner-joining two genomes' SCM arrays on `scm_id_idx`. Only adjacent pairs in the current visual order are derived; cached in LRU `PairCache`.
- **Collinear blocks** are derived from pairwise SCMs with strict order preservation (Section 3.3). Parameters: `max_gap`, `min_block_size`.

## Key Architectural Constraints

- **Per-genome BLAST tables, not pairwise PAF.** Don't introduce pairwise file formats as inputs — this was an explicit design choice to avoid N×(N−1)/2 files and SCM ID consistency issues.
- **Synteny connections are adjacent-pair only**; highlights (F3) and FISH (F4) span ALL genomes via `scm_to_genomes` lookup, not via pair derivation.
- **Blocks exist for data reduction at low zoom, not biological annotation.** Defaults must favour many small tight blocks over few large sprawling ones. The strict order check (design §3.3 step 3d) is non-negotiable. Default `max_gap` is **300 kb** (lower than the design's draft 1 Mb), `min_block_size` 3.
- **Karyotype-agnostic.** Sequence count, naming, and structure (pseudomolecule vs. scaffold-level) vary across input genomes. No code path may assume `chr1`–`chr7`, a specific chromosome count, or a particular naming convention. Connection palette is computed per genome from `.fai` (top-*N* sequences by length get distinct colors, the rest collapse into one "minor" color); per-genome overrides allowed via config.
- **SCM-IDs are opaque strings.** Format may change. Never split, parse, or pattern-match on them. The current `Chr<N>__<start>-<end>` shape is incidental to one upstream marker set.
- **Level-of-detail rendering:** blocks as ribbons when zoomed out, individual SCM lines when zoomed in. Threshold ~50 kb/px.
- **Memory target:** ~1.3 GB for 20 genomes × 1.2M SCMs + 30 cached pairs. numpy structured arrays with integer ID indices, not string-keyed dicts.

## Data Filtering (load time)

BLAST hits pass through: quality filter (`min_pident`, `min_length`, `max_evalue`) → uniqueness filter (bitscore ratio ≥ `uniqueness_ratio`, else discard all hits for that SCM) → `.fai` coordinate validation. Per-genome filtering stats are exposed via `/api/genomes`.

## Layout

```
docs/                     design documents
hermit/                   Claude Code harness config (not project code — ignore for feature work)
.idea/                    IDE config
```

Planned (not yet created): `syntrack/` (Python package), `frontend/`, `tests/`, `data/` (user-supplied fai + blast), `data/cache/` (optional precomputed `.npz`).

## Next steps

See `docs/IMPLEMENTATION_PLAN.md` §4 (Phase 1 backend) and §5 (Phase 2 frontend) for the v0.1 task list and done-criteria. Start with §4.1 scaffolding (`pyproject.toml` + `uv` venv + ruff/mypy/pytest config + typer CLI stub).
