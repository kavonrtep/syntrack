# SynTrack

Genome synteny visualization tool for comparative genomics. Displays N genomes as stacked tracks with syntenic connections between adjacent pairs, supports interactive reordering, cross-genome region highlighting, and in silico FISH painting.

Authoritative docs:
- `docs/DESIGN_v03.md` — what we build (data model, algorithms, API contract).
- `docs/IMPLEMENTATION_PLAN.md` — how we build it (stack, repo layout, phased tasks, decisions D1–D16).
- `AGENTS.md` — build/test commands, coding style, commit conventions, PR checklist. **Read it for the operational workflow.** This file (CLAUDE.md) owns architecture + domain invariants; AGENTS.md owns process. Keep them de-duplicated.

When design and plan conflict, the design wins; the plan is updated.

## Status

**v0.3.0 shipped.** 231 backend tests + 47 frontend tests pass; ruff/mypy --strict/svelte-check all clean; end-to-end verified on the real pea dataset (`example_data/`).

Shipped across v0.1–v0.3:
- Viewer: tracks + block ribbons + SCM-line LOD, cursor-pinned wheel zoom, drag pan, drag-and-drop reorder, sidebar visibility.
- Phase 3: cross-genome highlight (Ctrl-drag), in-silico FISH marker sets, alignment.
- Phase 4: `syntrack precompute` + on-disk `.npz` pair cache (`data.cache_dir`); complete (uncapped) SCM-ID export.
- Multi-colour FISH density preview (frozen whole-genome render) + high-res PNG export + "save highlight as set".
- Perf: vectorized block detection, int32 local coordinates, backend timing instrumentation (Server-Timing header + `SYNTRACK_LOG_LEVEL=DEBUG`), opt-in OffscreenCanvas worker for the connection layer (`?ribbonWorker=1`; default is main-thread).

## Stack (per IMPLEMENTATION_PLAN §0)

- **Backend:** Python 3.12, `uv` venv, FastAPI, polars (BLAST/FAI parsing), numpy structured arrays, typer CLI, pydantic v2, orjson.
- **Frontend:** Svelte 5 (runes) + Vite + TypeScript, raw HTML Canvas (three layers: track / connection / overlay), no charting library. The connection layer can render in a Web Worker via OffscreenCanvas (opt-in).
- **Tooling:** ruff (lint+format), mypy --strict on `syntrack/`, pytest + pytest-benchmark, vitest, pre-commit (ruff --fix + ruff-format).
- **Config:** YAML (`syntrack_config.yaml`).
- **Loader input:** `genomes.csv` with columns `genome_id,fai,SCM[,label]`, paths relative to the CSV.

## Core Domain Model

- **SCM (Single Copy Marker):** orthologous locus present in ≤1 copy per genome. Canonical ID, unambiguous position where present. SCMs are the unit of synteny.
- **Primary inputs:** per-genome `.fai` files + per-genome BLAST tables (`-outfmt 6`). BLAST tables are the single source of truth; pairwise synteny is **derived**, never stored as PAF.
- **Pairwise synteny** is derived on demand by inner-joining two genomes' SCM arrays on `scm_id_idx`. Only adjacent pairs in the current visual order are derived; cached in LRU `PairCache` (in-memory), optionally backed by the on-disk `.npz` cache.
- **Collinear blocks** are derived from pairwise SCMs with strict order preservation (design §3.3). Parameters: `max_gap`, `min_block_size`.
- **Coordinates:** structured-array `start`/`end` are *local* sequence coords stored as **int32** (≤ ~2.1 Gb/sequence, guarded by `MAX_SEQUENCE_LENGTH`); the genome-global `offset` is **int64**.

## Invariants — do not violate (checklist for any change)

- **Per-genome BLAST tables, not pairwise PAF.** Never introduce pairwise file formats as inputs (avoids N×(N−1)/2 files + SCM-ID consistency issues).
- **SCM-IDs are opaque strings.** Never split, parse, or pattern-match on them. The `Chr<N>__<start>-<end>` shape is incidental to one marker set.
- **Karyotype-agnostic.** No code path may assume `chr1`–`chr7`, a chromosome count, or a naming convention. Palette is computed per genome from `.fai`.
- **Strict block order check is non-negotiable** (design §3.3 step 3d). Blocks exist for data reduction at low zoom, not biological annotation; favour many small tight blocks (`max_gap` 300 kb, `min_block_size` 3).
- **Response caps must SUBSAMPLE, never head-truncate.** Any `limit`/cap on positions must uniformly subsample across the region (offset-sorted), or it collapses the cross-genome signal. `limit=0` means complete/uncapped (used by exports — completeness is required for FISH probe design).
- **Synteny connections are adjacent-pair only**; highlight/FISH span ALL genomes via per-genome membership, not pair derivation.
- **Memory target:** ~1.3 GB for 20 genomes × 1.2M SCMs + 30 cached pairs. numpy structured arrays with integer ID indices, never string-keyed dicts.
- **Version lives in TWO files** — `pyproject.toml` and `syntrack/__init__.py`. Bump both together (use the `/release` skill).
- **Frontend cannot be browser-verified in this environment.** Type-check + build + unit tests only. Therefore: harden any new render path so a failure degrades gracefully (never throws into a Svelte `$effect`, which crashes the component). Flag visual changes as needing the user's eyes.

## Data Filtering (load time)

BLAST hits pass through: quality filter (`min_pident`, `min_length`, `max_evalue`) → uniqueness filter (bitscore ratio ≥ `uniqueness_ratio`, else discard all hits for that SCM, keeping the best) → `.fai` coordinate validation. Per-genome filtering stats are exposed via `/api/genomes`.

## Verification loop

Run Python tools through `./dev.sh` (see Dev workflow notes). See `AGENTS.md` for the full command list.

- **Inner loop (fast):** `./dev.sh pytest -m "not integration"` + `./dev.sh ruff check syntrack tests` + `./dev.sh mypy`. The full suite is ~100s because the `integration` tests derive the real pea data; skip them while iterating.
- **Frontend:** `cd frontend && npm run check && npm test`. `npm run build` to confirm bundling (e.g. the worker chunk).
- **Before commit/release:** full `./dev.sh pytest` (no marker filter) + frontend check/test/build.
- **Benchmarks** are `--benchmark-skip` by default: `./dev.sh pytest tests/bench --benchmark-only [--benchmark-compare=NNNN]`.

## Layout

```
syntrack/        Python package — api/ (FastAPI routes), derive/ (synteny), io/ (parsers), store/ (genome/SCM data)
frontend/src/    Svelte app — canvas/ (renderers), api/ (client + types)
tests/           unit/ + api/ + bench/ (benchmarks, skipped by default)
docs/            design documents
example_data/    pea dataset config + data-link helpers (integration tests depend on link_data.sh symlinks)
hermit/          Claude Code harness config (not project code — ignore for feature work)
```

## Dev workflow notes

- The hermit sandbox sets `PIP_TARGET`/`PYTHONPATH` system-wide. The `./dev.sh` wrapper neutralizes both. **Always invoke Python tools through `./dev.sh`** (e.g. `./dev.sh pytest`, `./dev.sh syntrack ...`, `./dev.sh ruff ...`, `./dev.sh mypy`).
- npm/Vite run normally from `frontend/` (no wrapper).
- See `README.md` for the two-terminal dev loop (FastAPI on :8765, Vite on :5173 with /api proxy).
