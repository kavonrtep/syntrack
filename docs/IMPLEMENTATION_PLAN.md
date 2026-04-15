# SynTrack — Implementation Plan

This plan covers **how** we build SynTrack. **What** we build is fixed by `docs/DESIGN_v03.md`, which remains authoritative. When the two documents conflict, the design wins and this plan is updated.

---

## 0. Decisions

| # | Decision | Notes |
|---|---|---|
| D1 | **Frontend:** Svelte 5 + Vite + TypeScript, raw HTML Canvas, no charting library. | |
| D2 | **Python tooling:** `uv` venv, `pyproject.toml` (PEP 621), `ruff` lint+format, `mypy --strict` on `syntrack/`, `pytest` + `pytest-benchmark`. | |
| D3 | **Python:** 3.12 floor. | |
| D4 | **Loader input:** `genomes.csv` (`genome_id,fai,SCM[,label]`) resolved relative to the CSV. Replaces the dir-scan / `blast_pattern` form; design §7 will be amended. | |
| D5 | **Dev server:** FastAPI on `127.0.0.1:8765`; Vite on `:5173` proxying `/api` → 8765 during dev; production build served as static by FastAPI. | |
| D6 | **CLI:** `typer` (`syntrack serve`, `precompute`, `stats`, `lint-data`). | |
| D7 | **Repo layout:** monorepo (`syntrack/`, `frontend/`, `tests/`, `example_data/`, `docs/`). | |
| D8 | **Strand:** `"+"` / `"-"` on the wire, `int8` ±1 in numpy. | |
| D9 | **SCM-ID:** **opaque string**, never parsed. The current `Chr<N>__<start>-<end>` shape is incidental and the format may change. Stored as global `list[str]` + `dict[str,int]`; per-row `int32` index. Any code that splits or pattern-matches on the SCM-ID is a defect. | |
| D10 | **Block purpose:** **data reduction for rendering**, not biological synteny calling. Defaults must favour many small tight blocks over few big sprawling ones. The strict order check (design §3.3 step 3d) is non-negotiable. The block TSV export remains useful for power users but is not the primary product. | |
| D11 | **Karyotype assumptions:** none. Sequence count, naming, and structure (pseudomolecule vs. scaffold) vary across genomes. No code path may assume `chr1`–`chr7`, a fixed chromosome count, or a particular naming convention. Palette assignment is per-genome from `.fai` order/length (D14). | |
| D12 | **Pair-cache:** `.npz` + sibling `manifest.json`; manifest hash covers input mtimes, `block_detection` params, `blast_filtering` params, and code version. | |
| D13 | **Test data tiering:** synthetic micro-fixtures in `tests/fixtures/` for unit tests; real `example_data/` behind a `--integration` pytest marker. | |
| D14 | **Connection palette (karyotype-agnostic):** at load time, per genome, sort sequences by length descending. The top *N* (default 12, configurable) get distinct colors from a base palette; the remainder collapse into a single "minor" color. Connection color = palette of the **target genome's** sequence the connection lands on. Per-genome overrides allowed via config (e.g., user pins `chr1` → red across all genomes for a manuscript figure). | |
| D15 | **Frontend testing:** Vitest for pure logic (LOD math, coordinate transforms, palette assignment); Playwright deferred until after v0.1. | |
| D16 | **First release (v0.1):** Phases 1 + 2 only — backend MVP + browse-only viewer with reorder, block ribbons, and SCM-line LOD. No highlight, no FISH, no exports. Ship this before starting Phase 3. | |

---

## 0a. First release scope (v0.1) — ✅ SHIPPED

Delivered: 159 backend tests + 21 frontend tests pass; ruff/mypy/svelte-check clean; end-to-end verified on the real pea dataset (`example_data/`, 8 genomes, 1.39M unique SCMs).

What shipped:
- All of Phase 1 — backend MVP + `syntrack serve` / `syntrack lint-data` CLI + tests.
- Phase 2 core — Svelte 5 frontend with tracks, block ribbons, SCM-line LOD, drag-to-reorder, cursor-pinned wheel zoom, drag-pan.
- Quickstart in `README.md` with three install paths (uv-managed, plain venv, hermit sandbox).

Deferred to v0.2 (still unchecked in §§5–7 below):
- `/api/highlight`, `/api/fish` and overlay rendering (Phase 3).
- Block-parameter UI (sliders) and `/api/stats/blocks` sweep diagnostics (Phase 4).
- Export endpoints (BED, TSV, txt, PNG/SVG) (Phase 4).
- `syntrack precompute` and on-disk `.npz` cache (Phase 4, §4.5 second bullet).
- Request debouncing + `AbortController` cancellation in the frontend (§5.5 polish).
- Axis ticks on track canvas (§5.3 polish).
- `syntrack stats` CLI (§4.7).

---

## 1. Stack summary (assuming defaults)

**Backend**

- Python 3.12, `uv` venv
- `fastapi`, `uvicorn[standard]`, `pydantic` (v2)
- `numpy` (≥2.0), `polars` (BLAST/FAI parsing)
- `typer` (CLI), `pyyaml` (config)
- `pytest`, `pytest-benchmark`, `pytest-asyncio`, `httpx` (API tests)
- `ruff`, `mypy`

**Frontend**

- Svelte 5 + TypeScript + Vite
- No charting library; raw `CanvasRenderingContext2D`
- Drag/drop: native HTML5 `dragstart`/`dragover` (no library)
- State: Svelte runes + a thin `apiClient.ts`
- Vitest

**Dev workflow**

- `uv sync` → backend deps
- `npm install --prefix frontend` → frontend deps
- `syntrack serve --config config.yaml --reload` → backend on `:8765`
- `npm run dev --prefix frontend` → Vite on `:5173`, proxies `/api` → `:8765`

---

## 2. Repo layout

```
SynTrack/
├── pyproject.toml
├── uv.lock
├── ruff.toml
├── mypy.ini
├── README.md
├── CLAUDE.md
├── syntrack_config.example.yaml
├── docs/
│   ├── DESIGN_v03.md          # spec, authoritative
│   └── IMPLEMENTATION_PLAN.md # this file
├── example_data/              # already populated
│   ├── README.md
│   ├── link_data.sh
│   └── genomes.csv (+ symlinks; gitignored)
├── syntrack/                  # Python package
│   ├── __init__.py
│   ├── __main__.py            # python -m syntrack
│   ├── cli.py                 # typer app
│   ├── config.py              # pydantic settings, YAML loader
│   ├── io/
│   │   ├── fai.py             # FAI parser
│   │   ├── blast.py           # BLAST -outfmt 6 parser + filters
│   │   └── manifest.py        # genomes.csv reader, cache manifest
│   ├── model.py               # dataclasses / pydantic API models
│   ├── store/
│   │   ├── genome.py          # GenomeStore
│   │   └── scm.py             # SCMStore (per-genome arrays, global index)
│   ├── derive/
│   │   ├── pair.py            # PairwiseSynteny merge join
│   │   └── block.py           # SyntenyBlock collinear scan
│   ├── cache.py               # PairCache (LRU + .npz)
│   ├── api/
│   │   ├── app.py             # FastAPI app factory
│   │   ├── routes_genomes.py
│   │   ├── routes_synteny.py
│   │   ├── routes_overlay.py  # /highlight, /fish, /scm/{id}
│   │   ├── routes_export.py
│   │   ├── routes_config.py
│   │   └── routes_stats.py
│   └── precompute.py          # batch derivation entry point
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── index.html
│   └── src/
│       ├── main.ts
│       ├── App.svelte
│       ├── api/client.ts
│       ├── state/             # Svelte runes / stores
│       ├── canvas/
│       │   ├── tracks.ts      # genome bars
│       │   ├── connections.ts # ribbons + SCM lines
│       │   ├── overlay.ts     # highlight + FISH
│       │   └── lod.ts         # bp-per-px → mode
│       ├── components/
│       │   ├── Toolbar.svelte
│       │   ├── GenomeList.svelte    # drag handles
│       │   ├── FishPalette.svelte
│       │   ├── BlockParams.svelte
│       │   └── StatusBar.svelte
│       └── lib/colors.ts      # karyotype palette
└── tests/
    ├── conftest.py
    ├── fixtures/
    │   ├── tiny_a.fai
    │   ├── tiny_a.blast_out
    │   ├── tiny_b.fai
    │   ├── tiny_b.blast_out
    │   └── README.md          # how each fixture was constructed
    ├── unit/
    │   ├── test_fai.py
    │   ├── test_blast_filter.py
    │   ├── test_uniqueness.py
    │   ├── test_pair.py
    │   ├── test_block.py
    │   └── test_cache.py
    ├── api/
    │   ├── test_genomes.py
    │   ├── test_synteny.py
    │   ├── test_highlight.py
    │   └── test_fish.py
    └── integration/           # marker: --integration
        ├── test_load_pea.py
        ├── test_pair_pea.py
        └── test_perf_pea.py
```

---

## 3. Module contracts (key signatures)

These pin the interfaces between modules so each can be built and tested in isolation.

```python
# syntrack/io/fai.py
def read_fai(path: Path) -> list[Sequence]: ...

# syntrack/io/blast.py
@dataclass
class BlastFilterParams:
    min_pident: float = 95.0
    min_length: int = 100
    max_evalue: float = 1e-10
    uniqueness_ratio: float = 1.5

@dataclass
class FilteringStats:
    raw_hits: int
    after_quality: int
    after_uniqueness: int
    after_validation: int
    discarded_quality: int
    discarded_multicopy: int
    discarded_validation: int

def parse_and_filter_blast(
    path: Path,
    sequences: dict[str, int],     # seq_name -> length, for validation
    params: BlastFilterParams,
) -> tuple[pl.DataFrame, FilteringStats]:
    """Returns one row per kept SCM; columns:
       scm_id (str), seq_name (str), start (i64), end (i64), strand (i8)."""

# syntrack/store/scm.py
class SCMStore:
    universe: list[str]                          # SCM-ID string table
    universe_index: dict[str, int]               # str -> idx
    genome_positions: dict[str, np.ndarray]      # genome_id -> structured array
    scm_to_genomes: list[list[GenomeHit]]        # idx -> hits across genomes
    filtering_stats: dict[str, FilteringStats]

    @classmethod
    def load(cls, manifest: GenomesManifest, params: BlastFilterParams,
             genomes: GenomeStore) -> "SCMStore": ...

    def hits_in_region(self, genome_id: str, seq_name: str,
                       start: int, end: int) -> np.ndarray: ...

    def positions_of(self, scm_id_idx: int) -> list[GenomeHit]: ...

# syntrack/derive/pair.py
def derive_pair(scm: SCMStore, g1: str, g2: str) -> PairwiseSCM: ...

# syntrack/derive/block.py
@dataclass
class BlockParams:
    max_gap: int = 1_000_000
    min_block_size: int = 3

def detect_blocks(pair: PairwiseSCM, params: BlockParams) -> list[SyntenyBlock]: ...

# syntrack/cache.py
class PairCache:
    def get_or_derive(self, g1: str, g2: str,
                      block_params: BlockParams) -> tuple[PairwiseSCM, list[SyntenyBlock]]: ...
    def invalidate_blocks(self, params: BlockParams) -> None: ...
```

---

## 4. Phase 1 — Backend MVP

Order is dependency-driven; each task is small and independently testable.

### 4.1 Scaffolding ✅
- [x] `pyproject.toml`, `uv.lock`, `ruff.toml`, `mypy.ini`.
- [x] `syntrack/__init__.py` with version constant.
- [x] `syntrack/cli.py` with `typer` app and `serve` stub.
- [x] `syntrack/config.py`: pydantic-settings model from YAML; load `syntrack_config.example.yaml` round-trip test.

**Done when:** `uv run syntrack --help` and `uv run pytest -q` both succeed against an empty test suite.

### 4.2 IO layer ✅
- [x] `io/fai.py` — `read_fai` returns `list[Sequence]` with cumulative offsets.
- [x] `io/manifest.py` — read `genomes.csv`, resolve relative paths, validate file existence.
- [x] `io/blast.py` — polars-based parser:
  1. Read TSV with explicit dtypes (no schema inference).
  2. Quality filter (`min_pident`, `min_length`, `max_evalue`).
  3. Strand inference + canonical `start < end` swap.
  4. Uniqueness filter using bitscore best/second ratio per `qseqid`.
  5. Validate against `sequences` dict (drop hits with unknown seq or out-of-bounds; record stats).
  6. Return `(DataFrame, FilteringStats)`.

**Tests (synthetic fixtures):**
- 1 SCM, 1 hit → kept.
- 1 SCM, 2 hits, ratio ≥ 1.5 → keep best.
- 1 SCM, 2 hits, ratio < 1.5 → discard both.
- Hit on unknown seq → dropped + counted.
- Hit beyond seq length → dropped + counted.
- Negative-strand hit (sstart > send) → coordinates swapped, strand = `-`.

### 4.3 Stores ✅
- [x] `store/genome.py` — `GenomeStore` from FAI + optional label override. Computes per-genome palette assignment per D14 (top-*N* sequences by length → distinct colors; rest → "minor" color). Output is exposed on `Sequence.color`.
- [x] `store/scm.py` — `SCMStore.load`:
  1. For each genome: `parse_and_filter_blast` → polars DF.
  2. Map `scm_id` strings into a global universe (`dict[str,int]`).
  3. Convert each per-genome DF to a numpy structured array sorted by `offset`.
  4. Build `scm_to_genomes` by scanning all per-genome arrays.

**Tests:**
- 2 synthetic genomes, 5 shared SCMs → universe size correct, presence sets correct.
- `hits_in_region` returns expected slice (binary search bounds).
- `positions_of(idx)` returns positions in every genome containing the SCM.

### 4.4 Derivation ✅
- [x] `derive/pair.py` — sorted merge join on `scm_id_idx`.
  - Use numpy `searchsorted` / `intersect1d`-style approach, not Python loops.
- [x] `derive/block.py` — iterative scan with strict order (design §3.3, all 4 conditions).

**Block defaults (per D10 — blocks exist to reduce points-to-render at low zoom; they are not biological annotations):**

- `max_gap`: start at **300 kb** (lower than the design's 1 Mb default). Rationale: the LOD threshold is 50 kb/px, so at the transition zoom one pixel covers ~50 kb; a 300 kb max gap keeps blocks visually compact and prevents bridging across rearrangement breakpoints that the user would expect to see.
- `min_block_size`: 3 (matches design). Smaller "orphan" SCMs render as individual lines rather than ribbons at low zoom — that's fine; orphan rendering can be added in Phase 2 if needed.
- These are **defaults**, not constants. The diagnostic UI (Phase 4) lets the user sweep them.

**Forbidden in `derive/block.py`:** parsing or interpreting `scm_id` strings; assuming any specific chromosome naming or count; assuming the genome is pseudomolecule-resolved (scaffold-level inputs must work).

**Tests for `derive_pair`:**
- Two genomes with disjoint SCMs → empty pair.
- Identical SCM sets → pair size = SCM count.
- Sorted by `g1_offset` invariant after derivation.

**Tests for `detect_blocks`:**
- 5 SCMs same chr/strand within max_gap, monotonic g2 → 1 block of size 5.
- 5 SCMs but middle one breaks order → 2 blocks of sizes 2 and 2 (third orphaned if min=2; with min=3 both filtered).
- Strand flip mid-run → split.
- Inter-chromosomal jump → split.
- Property test: every block is internally collinear (random fuzz).

### 4.5 Cache ✅ (in-memory) / ⏸ (.npz deferred to v0.2)
- [x] `cache.py` — LRU dict capped at `max_pairs`. `get_or_derive` short-circuits on cache hit.
- [ ] `.npz` write/read with manifest hash; on parameter change, blocks recomputed but PairwiseSCM retained (matches design §3.3 tuning paragraph). *(deferred to v0.2 per D16)*

### 4.6 API surface ✅
- [x] `api/app.py` — FastAPI factory; CORS for `:5173` in dev only.
- [x] Routes (each in its own file, mounted in `app.py`):
  - `GET /api/genomes` — design §4.2.
  - `GET /api/pairs` — derived-status table (presence-matrix counts, no derivation triggered).
  - `GET /api/synteny/blocks?g1=&g2=&region_g1=&region_g2=&min_scm=` — triggers cache.
  - `GET /api/synteny/scms?g1=&g2=&region_g1=&region_g2=&limit=` — uniform downsampling at the SCMStore level (not after JSON serialization).
  - `GET /api/scm/{scm_id}` — universe lookup.
  - `GET /api/config`, `PUT /api/config` (block params only).
- [x] API tests with `httpx.AsyncClient` against the FastAPI app, using a tiny preloaded `SCMStore` fixture. *(implemented with FastAPI `TestClient`)*

### 4.7 CLI commands ✅ (v0.1 subset)
- [x] `syntrack serve --config <path> [--reload]` — runs uvicorn.
- [x] `syntrack lint-data --config <path>` — runs the loader, prints filtering stats per genome, exits non-zero on validation errors. (Useful smoke test on `example_data/`.)
- [ ] `syntrack stats --pair g1,g2` — runs `/api/stats/blocks` logic offline. *(deferred — part of Phase 4 tuning UI)*

**Phase-1 done criteria:**
1. `syntrack lint-data --config example_data/config.yaml` succeeds on all 8 pea genomes and prints filtering stats matching `example_data/README.md` scale (~250–500K SCMs/genome after filter from ~950K raw).
2. `syntrack serve` returns expected JSON for `/api/genomes`, `/api/synteny/blocks?g1=JI1006_2026-01-19&g2=JI15_2026-01-19` within < 2 s on first call (cold derive), < 50 ms on second call (cache hit).
3. `pytest -q` green; integration tests (`pytest -q --integration`) green.

---

## 5. Phase 2 — Frontend MVP

### 5.1 Scaffolding ✅
- [x] Vite + Svelte 5 + TypeScript scaffold (written by hand rather than via `npm create`).
- [x] Vite config: proxy `/api` → `127.0.0.1:8765`.
- [x] `api/client.ts` — typed wrappers for `/api/genomes`, `/api/pairs`, `/api/synteny/blocks`, `/api/synteny/scms`, plus `/scm/{id}` and `/config`.
- [x] App shell: header, central canvas area, status bar. *(no toolbar yet — deferred with Phase 4 tuning UI)*

### 5.2 Coordinate system & LOD ✅
- [x] `canvas/lod.ts`: `bp_per_px = visible_genomic_range / canvas_width`. Threshold derived from config (`block_threshold_bp_per_px`, default 50000).
- [x] Helper: `canvas/coords.ts` — `bpToPx` / `pxToBp` with `Viewport` (zoom + center); cursor-pinned `zoomAtFraction`.

### 5.3 Track canvas ✅ (core) / ⏸ (axis ticks)
- [x] Render genome bars from `/api/genomes`, segmented by `Sequence.offset` and `length`.
- [x] Chromosome labels (sequence name centred when the bar exceeds 30 px).
- [ ] Axis ticks at human-friendly intervals. *(deferred — v0.2 polish)*
- [x] Redraw triggered only on resize / reorder / zoom. *(driven by Svelte 5 `$effect` on relevant state; pan updates viewport.center which also triggers redraw — acceptable for v0.1, optimisation deferred)*

### 5.4 Connection canvas ✅
- [x] Block ribbons for adjacent pairs at low zoom: opacity ∝ density (scm_count / span_kb).
- [x] SCM lines at high zoom from `/api/synteny/scms` with `limit=5000`.
- [x] Color by **target sequence** in the connection's lower-track genome. Palette is supplied per genome by `/api/genomes` (`sequences[i].color`, computed server-side per D14 — top *N* by length get distinct hues, the rest collapse into a "minor" bucket color). Frontend never derives palette from sequence names.
- [x] Strand encoding: `+` parallel ribbon, `−` crossed.

### 5.5 Interaction ✅ (core) / ⏸ (debounce + cancellation)
- [x] Mouse-wheel zoom centred on cursor (X axis only).
- [x] Click-drag pan on empty canvas area.
- [x] Genome reorder via HTML5 drag-and-drop on sidebar items; on drop, recompute adjacency, request newly adjacent pairs (spinner badge shown per pending pair).
- [ ] Request debounce (200 ms) on adjacency changes. *(deferred — v0.2 polish)*
- [ ] Request cancellation on rapid zoom: `AbortController` per pending fetch, cancel on next request. *(deferred — v0.2 polish; AbortSignal plumbing exists in the API client)*

### 5.6 Status bar ✅
- [x] Shows current visible region (top genome as anchor), bp/px, current LOD mode, and a "loading N pairs" badge for in-flight derivations.

**Phase-2 done criteria:**
1. With `example_data` loaded and 8 genomes, a fresh page renders all tracks + initial adjacent-pair ribbons within < 3 s.
2. Reorder a genome: stale ribbons clear, new ribbons appear; first-time pair derive < 2 s, cached re-adjacency instant.
3. Zoom from whole-genome to a 1 Mb window: smooth LOD transition, no dropped frames > 100 ms during steady zoom.

---

## 6. Phase 3 — Highlight & FISH

### 6.1 Backend
- [ ] `POST /api/highlight` (design §4.2). Region → SCM IDs → cross-genome positions via `scm_to_genomes`.
- [ ] `POST /api/fish` — same machinery, input is either explicit `scm_ids` or `source_genome` + `source_region`.

### 6.2 Frontend
- [ ] Region selection: shift-click-drag on a track creates a selection; on mouse-up POSTs `/api/highlight`.
- [ ] Overlay canvas: source rectangle, target tick marks on every genome, dim non-highlighted connections to `dimmed_opacity`.
- [ ] `FishPalette.svelte`: list of FISH sets with color picker, label, toggle, delete. State persisted in `localStorage`.
- [ ] FISH render pass on overlay canvas; multiple sets composited.

**Phase-3 done criteria:**
1. Select a 5 Mb region on JI1006 chr1 → ticks appear on all 7 other genomes within < 500 ms; counts match `/api/highlight` response.
2. Create two FISH sets with distinct colors → both visible simultaneously on every genome.

---

## 7. Phase 4 — Tuning, export, polish

- [ ] `GET /api/stats/blocks` — single pair, optional `max_gap_sweep`. Block size + span histograms.
- [ ] `BlockParams.svelte` — sliders for `max_gap`, `min_block_size`; live preview using cached `PairwiseSCM` (no re-derive).
- [ ] `GET /api/export/scm_ids`, `/api/export/bed`, `/api/export/blocks`, `/api/export/png|svg` (frontend-side canvas export).
- [ ] `syntrack precompute --config ... --pairs all|<list>` writes `.npz` cache and manifest.
- [ ] On startup, load matching cache automatically (manifest-validated).
- [ ] Tooltips: hover SCM/block → details panel.
- [ ] Filtering-stats table in UI (collapsible per-genome).
- [ ] Playwright happy-path E2E (load 2 genomes, reorder, highlight, FISH).

---

## 8. Test strategy summary

| Layer | Tool | What it covers |
|---|---|---|
| Pure functions (parsers, filters, block scan) | pytest with synthetic fixtures | Correctness on every branch of design §3.2.1 / §3.3 |
| Stores & cache | pytest with `tmp_path` | LRU eviction, manifest invalidation, round-trip `.npz` |
| API | pytest + `httpx.AsyncClient` | Schema, query parameters, error paths |
| Integration | pytest `--integration` + real `example_data` | End-to-end load + 1–2 derived pairs; perf benchmarks |
| Frontend logic | vitest | LOD math, palette assignment, debouncer, AbortController flow |
| E2E (Phase 4) | Playwright | One scripted user flow |

`tests/fixtures/` micro-data is hand-authored so every test asserts on **exact** known counts and IDs — no "looks reasonable" assertions in unit tests.

---

## 9. Performance plan

- **Loading:** polars reads `.blast_out` lazily; group-by-qseqid for uniqueness in polars (stays in Rust). Only the kept rows materialize into numpy.
- **Pair derive:** numpy `intersect1d(..., return_indices=True)` over `scm_id_idx`. Avoid Python iteration entirely.
- **Block scan:** vectorize the per-condition checks where possible, but keep the run-grouping in a Python loop — block count is ≤ ~50K so loop cost is fine.
- **API serialization:** avoid pandas/polars `.to_dict()`; build dicts directly from numpy slices to skip per-row overhead.
- **Caching:** PairCache keyed by `(g1, g2)` with `g1 < g2` normalization to dedupe symmetric requests.
- **Frontend:** pre-bake ribbon Path2D objects per pair on first draw; redraw via `ctx.stroke(path)` — avoids re-issuing per-block draw calls during pan.
- **Benchmarks:** `pytest-benchmark` regression gates for: full load, single-pair derive, block detect, `/api/highlight` round-trip on 1 Mb / 10 Mb / 50 Mb windows.

---

## 10. Critical risks

| Risk | Mitigation |
|---|---|
| BLAST uniqueness filter discards too aggressively for closely related genomes (small bitscore differences) | Surface filter ratio + per-genome discard counts in `/api/genomes`; expose as config override; the `lint-data` CLI makes tuning a one-command loop. |
| Default block params produce visually nonsensical blocks across phylogenetic distances | `/api/stats/blocks` sweep + UI sliders are first-class (Phase 4 elevated to mid-Phase-2 if blocks look wrong). |
| Reorder UX feels sluggish on first derivation of a never-seen pair | Background-derive *all* pairs adjacent in **any** plausible permutation? No — too costly. Instead: pre-derive on idle (post-load worker thread), prioritized by current adjacency. Add only if observed slow. |
| Canvas perf at 8 genomes × ~5K SCM lines simultaneously | Cap to `max_visible_scms` per pair (default 5000); use `globalAlpha` instead of per-line alpha; one Path2D per (chr, strand) bucket. |
| `numpy.intersect1d` cost on 1.2M × 1.2M (max-scale) genomes | Profile during integration tests on `example_data` (smaller but representative). Fallback to manual sorted-merge in Cython only if benchmarks fail; keep optional. |

---

## 11. Sequence of work

v0.1 ships Phases 1 + 2 only (D16). Phases 3 and 4 are post-v0.1 and not started until v0.1 has been used against the real `example_data` for at least one round of feedback.

```
v0.1 ───────────────────────────────────────────── ✅ SHIPPED
  4.1 scaffold                    ✅
    └ 4.2 io                      ✅
        └ 4.3 stores              ✅
            ├ 4.4 derive          ✅
            │    └ 4.5 cache      ✅ (in-memory LRU; .npz → v0.2)
            │         └ 4.6 api   ✅
            └ 4.7 cli             ✅ (serve + lint-data; stats → v0.2)
                                  └─> Phase 2 (frontend MVP)  ✅

v0.2+ (post-feedback) ────────────────────────────── ⏸
  Phase 3 (highlight + FISH)
  Phase 4 (tuning UI, exports, precompute CLI, .npz cache,
           request debouncing/cancellation, axis ticks, tooltips)
```

Strict dependencies are linear inside a phase. Phase 2 may start once §4.6 is stable; it does not need §4.7 (CLI). Phases 3 and 4 are independent of each other and can be picked up in either order after v0.1.

---

## 12. Out of scope (per design §8)

Listed here so we don't get ambushed by feature creep:

- Pairwise PAF input formats.
- Circular genomes.
- Per-genome sequence reordering UI.
- Multiple SCM marker sets per session.
- Multi-user / auth / persistence beyond local files.
- GFF3 / PAF export of derived data (export limited to BED, TSV, txt, PNG/SVG).
- Visual regression tests.
