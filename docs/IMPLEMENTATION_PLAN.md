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

## 0a. Shipped increments

Running on the real pea dataset (`example_data/`, 8 genomes, 1.39 M unique SCMs); end-to-end verified each time. **181 backend + 38 frontend tests** pass; ruff / mypy / svelte-check clean.

### v0.1 ✅ (Phases 1 + 2 core)
- All of Phase 1 — backend MVP, `syntrack serve` / `lint-data` CLI, tests.
- Phase 2 core — Svelte 5 frontend: tracks, block ribbons, SCM-line LOD, cursor-pinned wheel zoom, drag-pan, sidebar drag-to-reorder, status bar, in-memory LRU cache.

### v0.1.1 ✅ (reference-propagated colors + scoped zoom/pan, §5.7)
- `SCMStore.reference_seq_map` (cached CSR-derived map); `SyntenyBlock` carries row-range indices.
- `/api/synteny/{blocks,scms}` accept `?reference=`; schemas gain `reference_seq`.
- `/api/paint` — block-based aggregation against the reference so non-reference chromosomes are painted in multi-colour stripes (paint and ribbons share `BlockParams`, so `PUT /api/config` block-detection re-draws both).
- Frontend: ribbon / SCM-line / track-bar colour resolved through the reference palette with `UNKNOWN_COLOR` fallback.
- Scope deltas: override = `{ zoomFactor, centerDelta }` applied on top of `globalViewport`, so global pan/zoom propagate to everyone including overridden genomes.

### v0.1.2 ✅ (perf, alignment, sidebar redesign, dev-workflow — §5.8)
- rAF-throttled pan coalesces pointermove into one viewport update per frame.
- Pixel-aware LOD: sub-pixel ribbons and paint regions clamp to 1 px instead of being dropped — no more "sparse at 1 ×" gaps.
- Color-batched Canvas fills (`Path2D` per colour for tracks, per `(colour, opacity-bucket)` for ribbons).
- High-contrast chromosome separators (1 px dark + 1 px light + tick above/below) independent of bar colour.
- Double-click on any bar aligns every other genome so the syntenic basepair lands at the click pixel (`/api/align`, `canvas/alignment.ts`, anchor untouched, follows global pan/zoom afterwards).
- Sidebar redesign: reorder moved to DOM handles sitting above each canvas bar; sidebar is now a visibility selector (checkboxes, `All` / `None` shortcuts, strike-through on unchecked).
- `./dev.sh` auto-picks `.venv-hermit` inside hermit and falls back to `.venv` outside, so one script works in both contexts.

### Still deferred (v0.2+)
- `/api/highlight` (click-select a region, highlight syntenic SCMs as ticks on every genome — complementary to alignment, which moves the viewports). Phase 3.
- `/api/fish` — *user-defined* custom paint sets (arbitrary SCM IDs / source regions become stackable colour overlays). Scope reduced because reference painting already covers the default "FISH the top genome's chromosomes" use case. Phase 3.
- Block-param slider UI + `/api/stats/blocks` sweep diagnostics. Phase 4.
- Exports (BED, TSV, txt, PNG/SVG). Phase 4.
- `syntrack precompute` + on-disk `.npz` cache + manifest-hash invalidation. Phase 4.
- Request debouncing + `AbortController` cancellation on rapid zoom. Phase 4 polish.
- Axis ticks on the track canvas. Phase 4 polish.
- `syntrack stats` CLI. Phase 4 polish.
- Playwright E2E. Phase 4 polish.

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
├── pyproject.toml, uv.lock, ruff.toml, mypy.ini
├── dev.sh                       # hermit-venv wrapper, auto-picks .venv-hermit / .venv
├── README.md, CLAUDE.md, syntrack_config.example.yaml
├── .venv-hermit/                # ./dev.sh setup target (gitignored)
├── .venv/                       # host-side tools (gitignored; never touched by dev.sh setup)
├── docs/
│   ├── DESIGN_v03.md            # spec, authoritative
│   └── IMPLEMENTATION_PLAN.md   # this file
├── example_data/
│   ├── README.md, link_data.sh, syntrack_config.yaml
│   └── *.fai / *.blast_out (+ genomes.csv symlinks; gitignored)
├── syntrack/                    # Python package
│   ├── __init__.py, __main__.py, cli.py, loader.py
│   ├── config.py                # pydantic settings, YAML loader
│   ├── model.py                 # Sequence / Genome dataclasses
│   ├── palette.py               # karyotype-agnostic palette (D14)
│   ├── io/
│   │   ├── fai.py, blast.py, manifest.py
│   ├── store/
│   │   ├── genome.py            # GenomeStore + palette assignment
│   │   └── scm.py               # SCMStore + reference_seq_map cache
│   ├── derive/
│   │   ├── pair.py              # PairwiseSCM merge join
│   │   └── block.py             # SyntenyBlock strict-order scan (+ row-range for paint/align)
│   ├── cache.py                 # PairCache (LRU; .npz deferred)
│   └── api/
│       ├── app.py, deps.py, schemas.py, regions.py, state.py
│       ├── routes_genomes.py, routes_pairs.py, routes_scm.py
│       ├── routes_synteny.py    # /synteny/{blocks,scms} with ?reference=
│       ├── routes_paint.py      # /paint — block-based reference painting
│       ├── routes_align.py      # /align — double-click alignment mapping
│       └── routes_config.py     # GET/PUT block_detection
├── frontend/
│   ├── package.json, vite.config.ts, tsconfig.json, svelte.config.js, index.html
│   └── src/
│       ├── main.ts, App.svelte, app.css
│       ├── api/client.ts, api/types.ts
│       └── canvas/
│           ├── coords.ts         # Viewport + bp↔px transforms
│           ├── lod.ts            # bp-per-px → mode
│           ├── hit_test.ts       # genomeIndexAt for scoped / dbl-click
│           ├── colors.ts         # referenceColorMap + UNKNOWN_COLOR
│           ├── alignment.ts      # alignmentDelta({anchor, target, xClick, …})
│           ├── draw_tracks.ts    # painted + separator bars
│           ├── draw_ribbons.ts   # Path2D-batched trapezoids
│           ├── draw_scms.ts      # SCM lines at LOD-high
│           └── format.ts
└── tests/
    ├── conftest.py
    ├── unit/
    │   ├── test_fai.py, test_blast.py, test_manifest.py
    │   ├── test_config.py, test_cli.py, test_regions.py
    │   ├── test_palette.py, test_genome_store.py, test_scm_store.py
    │   ├── test_pair.py, test_block.py
    │   └── test_cache.py
    └── api/
        ├── conftest.py          # 3-genome synthetic AppState fixture
        ├── test_genomes.py, test_pairs.py, test_synteny.py
        ├── test_scm_lookup.py, test_config.py
        ├── test_paint.py, test_align.py
        └── (test_highlight.py, test_fish.py — Phase 3)
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
- [x] Genome reorder via HTML5 drag-and-drop on **per-track DOM handles** overlaid on the canvas (the label strip above each bar; `pointer-events: auto` only on the handle itself so pan / dblclick on the bar below are unaffected). *Note: originally planned as sidebar drag — moved to canvas per v0.1.2.*
- [x] Sidebar repurposed as a visibility selector (checkboxes, `All` / `None` shortcuts, strike-through on unchecked).
- [ ] Request debounce (200 ms) on adjacency changes. *(deferred — v0.2 polish)*
- [ ] Request cancellation on rapid zoom: `AbortController` per pending fetch, cancel on next request. *(deferred — v0.2 polish; AbortSignal plumbing exists in the API client)*

### 5.6 Status bar ✅
- [x] Shows current visible region (top genome as anchor), bp/px, current LOD mode, and a "loading N pairs" badge for in-flight derivations.

### 5.7 v0.1.1 refinements — reference-propagated colors + scoped zoom/pan ✅

**Color propagation via the top (reference) genome.** Today every genome carries its own palette and a ribbon is coloured by its *target* sequence. This makes translocations invisible: the same piece of ancestry carries different colours in different genomes. Fix by propagating colour along SCM identity from a single reference (the top-ordered genome):

- The top genome in `order` is the **reference**. Its palette defines the colour space for the whole display.
- Every SCM's colour is the reference's colour for whichever of its sequences contains the SCM (via `scm_to_genomes`).
- SCMs not present in the reference fall back to a configurable "minor" colour (reuse `PaletteCfg.minor_color`).
- **Consequence:** a non-reference genome's single chromosome can be painted in multiple colours, reflecting the reference-relative origin of each SCM — that's the point; it makes rearrangements visually obvious.
- **Block-level colour** is the *dominant* reference sequence among the block's SCMs (plurality vote; tie-broken by lowest seq index).
- **Reorder triggers repaint.** Changing the top genome swaps the colour space; pair caches are invalidated because blocks' `reference_seq` changes.

Backend tasks:
- [x] `SCMStore.reference_seq_map(ref_genome_id)` — returns an `int32` array of length `universe_size` mapping `scm_id_idx → reference_seq_idx` (or `-1` if the SCM is absent from the reference). Cached lazily per reference id.
- [x] Extend `SyntenyBlock` with `scm_row_start, scm_row_end` (indices into `PairwiseSCM.rows`) so the API layer can look up each block's SCMs for dominant-reference computation. Update `detect_blocks` + tests.
- [x] `/api/synteny/blocks` + `/api/synteny/scms` accept `reference=<genome_id>` query param; validate. When provided, populate `reference_seq` on each block (plurality) and each SCM (direct lookup).
- [x] Schema updates: optional `reference_seq: str | null` on `SyntenyBlockSchema` and `PairwiseSCMSchema`.
- [x] **Track painting:** `GET /api/paint?genome_id=X&reference=Y` returns run-length-encoded `PaintRegion`s (one per contiguous run of same-reference-seq SCMs), so non-reference chromosome bars can be drawn in multiple colours.

Frontend tasks:
- [x] API client: add `reference` to `blocks()` and `scms()` options.
- [x] Pair-cache keys include the reference id (`"g1|g2|ref"`). Reorder → new reference → re-fetch under new keys.
- [x] Ribbon + SCM renderers: colour = reference genome's `Sequence.color` looked up from `reference_seq`; fallback to `UNKNOWN_COLOR` (#3a3a3a, darker than palette minor) when `reference_seq` is null.
- [x] **Painted track bars:** fetch `/api/paint` per genome; `drawTracks` paints each region in its reference colour, fills uncovered stretches with `UNKNOWN_COLOR`, falls back to per-sequence palette during initial load.

**Scoped zoom + pan: global by default, per-genome on modifier or mid-track interaction.**

- Default zoom/pan applies to *all* genomes simultaneously (current behaviour).
- **Shift + wheel** (or Shift + drag) while the cursor is over a specific genome row affects that genome only — a per-genome override layered on top of the global viewport.
- No modifier, or cursor in the gap between rows: global.
- Per-genome overrides persist until reset.
- **Reset view** clears all per-genome overrides and resets the global viewport.
- Status bar reflects current scope ("global" or "genome: ID").

Frontend tasks:
- [x] Replace the single `viewport` with `globalViewport: Viewport` + `viewportOverrides: SvelteMap<genome_id, Viewport>`.
- [x] Helper `effectiveViewport(genome_id)` returns override if present else global; all renderers switched to a `ViewportFn` signature so ribbons compute left/right x-mappings with per-genome viewports.
- [x] `canvas/hit_test.ts::genomeIndexAt(y, n)` — geometric hit test against `trackY`/`trackHeight`; returns index or null. 8 vitest cases.
- [x] Wheel handler: `e.shiftKey && pointerGenomeId` → update that genome's override; else update global.
- [x] Pointer handlers: capture target genome at `pointerdown`; apply to the same genome (or global) throughout the drag.
- [x] Reset-view clears `viewportOverrides` alongside resetting `globalViewport`.
- [x] Status bar shows `global` / `N override(s)` indicator; LOD + zoom anchor is the top genome's effective viewport.
- [x] Header hint text ("Shift = scope to one genome") with tooltip.

Tests (additions):
- [x] Backend: `reference_seq_map` correctness (absent SCMs → -1; multi-sequence reference; cached identity).
- [x] Backend: API returns expected `reference_seq` on blocks (dominant-vote) and SCMs (direct lookup); unknown-reference 404; `/api/paint` trivial self + mixed non-reference + 404s + monotonic invariant.
- [x] Frontend (vitest): `genomeIndexAt` boundary cases; `colorFor` null/unknown/known.

**Phase-2 done criteria:**
1. With `example_data` loaded and 8 genomes, a fresh page renders all tracks + initial adjacent-pair ribbons within < 3 s.
2. Reorder a genome: stale ribbons clear, new ribbons appear; first-time pair derive < 2 s, cached re-adjacency instant.
3. Zoom from whole-genome to a 1 Mb window: smooth LOD transition, no dropped frames > 100 ms during steady zoom.

### 5.8 v0.1.2 refinements — perf, alignment, sidebar redesign, dev workflow ✅

Work that wasn't in the original plan but landed before moving on to Phase 3.

**Rendering performance.** Painted-bar + ribbon cost at 1× on the 8-genome pea dataset was blocking smooth interaction.
- [x] rAF-throttled pan — pointermove events coalesce into one viewport update per animation frame.
- [x] Color-batched Canvas fills: one `Path2D` per colour (tracks), one per `(colour, opacity-bucket)` (ribbons). Cuts fill calls from ≫10⁴/frame to O(palette × 4).
- [x] Pixel-aware LOD with clamp-to-1-px: sub-pixel blocks / paint regions no longer dropped (fixes the "sparse at 1×, dense at 4×+" bug) — they render as min-width columns that merge in their colour's Path2D, so cost stays flat.
- [x] High-contrast chromosome separators (1 px dark + 1 px light + tick above/below) independent of bar colour.

**Scope deltas (bug fix).** Full-replacement overrides froze scoped genomes out of global pan/zoom. Overrides are now `{ zoomFactor, centerDelta }` applied on top of `globalViewport`, so global changes propagate to every genome including overridden ones; the scoped offset rides on top.

**Block-based paint.** `/api/paint` originally RLE'd every SCM transition on a genome; regions could be single-SCM-sized and didn't match ribbon aggregation. Now computed as the blocks of pair `(genome_id, reference)` projected onto the genome — paint and ribbons share `BlockParams` and re-aggregate together when `PUT /api/config` changes block params.

**Double-click alignment.**
- [x] `GET /api/align?genome_id=X&seq=S&pos=BP&k=3`: for every other genome, find the block containing `pos` (interpolate, confidence 1) or the top-K nearest blocks on the clicked chromosome (weight = `scm_count / (1 + distance_Mb)`, majority-vote on target seq, weighted-average of interpolated positions). 7 new tests.
- [x] Frontend: `canvas/alignment.ts::alignmentDelta` turns a target syntenic bp into a `{ zoomFactor, centerDelta }` override so the target's bp-per-pixel matches the anchor and the syntenic bp lands at the click pixel. 4 vitest cases with `bpToPx(bpTarget, reconstructed_vp) == xClick` invariant.
- [x] `ondblclick` on the track canvas → `api.align()` → rewrite `viewportOverrides` for every mapped target; anchor and `globalViewport` untouched.

**Sidebar redesign.**
- [x] Reorder moved from sidebar list to DOM handles overlaid above each canvas bar.
- [x] Sidebar repurposed as a visibility selector (checkbox per genome; unchecked genomes drop out of `order` / display; sticky header with `All` / `None` + live count).
- [x] Canvas no longer draws its own labels (handle provides them; avoids overdraw).

**Dev workflow.**
- [x] `.venv-hermit` (hermit-sandbox-managed via `./dev.sh setup`) / `.venv` (host-side, managed by you) kept strictly separate. `./dev.sh <cmd>` resolves whichever venv has a working Python at invocation time, so the same commands work inside and outside the hermit sandbox.

---

## 6. Phase 3 — Highlight & FISH

**Scope note (updated post-v0.1.2).** Reference-propagated painting already delivers the default "FISH the reference genome's chromosomes onto all genomes" use case, and double-click alignment handles "move all genomes to this region" without needing click-highlight. Phase 3 is now about the *remaining* complementary behaviours:

- `/api/highlight` — click-select a region on genome X; mark the individual SCMs (as ticks) that belong to that region across every other genome *without* moving their viewports. Complementary to alignment (which moves viewports but doesn't mark individual SCMs).
- `/api/fish` — *user-defined custom* paint sets (arbitrary SCM ID list or a specific non-reference region becomes a stackable colour overlay on top of the reference painting). Lets users compose multiple coloured overlays for figure-making, independent of whichever genome is currently reference.

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

Current totals after v0.1.2: **181 backend** (pytest) + **38 frontend** (vitest). Ruff, mypy, svelte-check all clean.

| Layer | Tool | What it covers |
|---|---|---|
| Pure functions (parsers, filters, block scan, alignment math) | pytest with synthetic fixtures | Correctness on every branch of design §3.2.1 / §3.3 and v0.1.2 align algorithm |
| Stores & cache | pytest with `tmp_path` | Universe build, CSR consistency, LRU eviction, `reference_seq_map` cache |
| API | FastAPI `TestClient` via pytest | Schema, query parameters, error paths, reference / paint / align / config-PUT invariants |
| Integration | pytest `--integration` + real `example_data` | End-to-end load + 1 derived pair + 1 block scan (~34 s for 8 pea genomes) |
| Frontend logic | vitest | Coord transforms, LOD cutoff, hit-test, colour lookup, alignment delta round-trip |
| E2E (Phase 4) | Playwright | One scripted user flow — still deferred |

Micro-fixtures are hand-authored so every test asserts on **exact** known counts and IDs — no "looks reasonable" assertions in unit tests.

---

## 9. Performance plan

Backend — implemented:
- **Loading:** polars reads `.blast_out` with explicit schema; quality/uniqueness filters + strand normalisation stay in Rust; only kept rows materialize into numpy.
- **Pair derive:** numpy `intersect1d(..., return_indices=True)` over `scm_id_idx`. No Python iteration.
- **Block scan:** per-condition checks in a single Python loop — ≤ ~50 k blocks per pair, loop cost fine; block detection now also records `(scm_row_start, scm_row_end)` so paint / align can reuse the block decomposition without re-walking rows.
- **Reference seq map:** one pass over `_hits_flat`, vectorised; cached per reference id so repeated `?reference=` queries are free.
- **Caching:** `PairCache` keyed by ordered `(g1, g2)`. `g1 < g2` normalisation deferred — paint needs one direction, align needs the other.

Backend — still pending:
- **Benchmarks:** `pytest-benchmark` regression gates for full load, single-pair derive, block detect, `/api/align` and `/api/highlight` round-trips on 1 Mb / 10 Mb / 50 Mb windows. *(infra added but no gates yet)*
- **Frontend-direct binary format:** `.to_dict()` avoidance; current responses build dicts from numpy slices, still JSON. Good enough so far.

Frontend — implemented (v0.1.2):
- **rAF-throttled pan** coalesces pointermove into one update per animation frame.
- **Color-batched `Path2D`:** one path per colour (tracks), per `(colour, opacity bucket)` (ribbons). Cuts fill calls from ≫10⁴/frame to O(palette × ≤ 4) regardless of block count.
- **Pixel-aware LOD clamp:** sub-pixel blocks / paint regions render as min 1 px columns, overlapping merges inside the same Path2D — low-zoom density matches what's visible at 4 ×+ without re-adding per-pixel-alias gaps.
- **High-contrast separators** (1 px dark + 1 px light + tick) independent of bar colour.

Frontend — pending:
- Pre-bake per-pair ribbon Path2D on derive (avoid rebuild every pan frame). *Not yet needed — batching is fast enough on 8 pea genomes.*
- Request debounce + `AbortController` cancellation on rapid zoom. *Deferred; AbortSignal plumbing already in the client.*

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
v0.1  ──────────────────────────────────────────── ✅ SHIPPED
  Phase 1 backend + Phase 2 frontend core
    scaffold → io → stores → derive → cache → api → CLI
                                          └─> frontend MVP

v0.1.1 ──────────────────────────────────────────── ✅ SHIPPED (§5.7)
  Reference-propagated colors
    SCMStore.reference_seq_map · /synteny/* ?reference= · /api/paint
    Ribbons + SCM lines + painted bars coloured via reference palette
  Scoped zoom/pan (Shift + wheel/drag over a track)

v0.1.2 ──────────────────────────────────────────── ✅ SHIPPED (§5.8)
  Perf: rAF pan · Path2D color-batching · pixel-aware LOD clamp
  Separators independent of bar colour
  Scope *delta* model — global changes now propagate to overridden genomes
  Block-based /api/paint — bars and ribbons re-aggregate in lockstep
  Double-click alignment (/api/align + canvas/alignment.ts)
  Sidebar → visibility selector; reorder moved to canvas DOM handles
  dev.sh resolves .venv-hermit (inside) / .venv (outside) automatically

v0.2+ ────────────────────────────────────────────── ⏸
  Phase 3 (highlight + custom-FISH — scope reduced, see §6 note)
  Phase 4 (block-param slider UI, /stats/blocks, exports, precompute CLI,
           .npz cache, request debouncing/cancellation, axis ticks,
           tooltips, filtering-stats UI, Playwright E2E)
```

Phases 3 and 4 are independent and can be picked up in either order.

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
