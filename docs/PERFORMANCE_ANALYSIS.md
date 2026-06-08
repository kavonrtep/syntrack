# SynTrack — Performance Analysis & Optimization Plan

Conducted 2026-06-08 against a production dataset: **11 pea genomes, ~1M SCMs per genome, 1.39M universe**.

---

## 1. Dataset Profile

| Genome | SCMs | Sequences | Total bp |
|--------|------|-----------|----------|
| JI1006_2026-01-19 | 887,480 | 63 | 4.2 Gb |
| JI15_2026-01-19 | 1,243,987 | 39 | 3.9 Gb |
| IPIP201118_2026-01-27 | 1,152,703 | 33 | 3.9 Gb |
| JI2822_2026-02-02 | 1,279,594 | 39 | 3.9 Gb |
| IPIP200590_2026-02-04 | 1,089,011 | 30 | 3.8 Gb |
| JI281_2026-02-05 | 1,184,366 | 25 | 3.9 Gb |
| IPIP200731_2026-04-14 | 1,045,219 | 41 | 4.4 Gb |
| IPIP200579_2026-04-14 | 1,131,323 | 15 | 3.9 Gb |
| JI2202_251016 | 1,023,628 | 97 | 4.2 Gb |
| IPIP200580_260602 | 1,035,624 | 162 | 4.4 Gb |
| IPIP202077_251113 | 999,587 | 80 | 4.6 Gb |

10 adjacent pairs at any given time. Total sequences across all genomes: ~625.

---

## 2. Data Volume per API Call

| Endpoint | Calls (N=11) | Items/call | JSON/call | Total |
|----------|-------------|------------|-----------|-------|
| `/api/synteny/blocks` | 10 | ~500 blocks | ~50 KB | 500 KB |
| `/api/synteny/scms` | 10 | 5,000 (capped) | ~400 KB | 4 MB |
| `/api/paint` | 11 | ~500 regions | ~30 KB | 330 KB |
| **Initial load (LOD=block)** | **23** | | | **~1 MB** |
| **High zoom (LOD=scm)** | **+10** | | | **+4 MB** |
| **Reference change** | **31** | | | **~5 MB** |

---

## 3. Rendering Pipeline — Per-Frame Cost

### 3.1 `drawTracks()` — track canvas

| Pass | Operations | Items (N=11) |
|------|-----------|-------------|
| Base pass (chromosome bars) | `Path2D.rect()` | 625 sequences |
| Paint overlay | `Path2D.rect()` | 5,500 regions |
| Fill (batched by color) | `ctx.fill()` | ~13 calls |
| Separators | `ctx.stroke()` per extent | 625 calls |
| Labels | `ctx.fillText()` + `ctx.strokeText()` | 625 calls |

Total: **~6,800 operations/frame**.

### 3.2 `drawRibbons()` — LOD=block (zoomed out)

| Pass | Operations | Items |
|------|-----------|-------|
| Block quadrilaterals | 4 × `lineTo()` per block | 5,000 blocks |
| Fill (batched by color × opacity) | `ctx.fill()` | ~48 calls |

Total: **~20,000 Path2D operations/frame**.

### 3.3 `drawScmLines()` — LOD=scm (high zoom)

| Pass | Operations | Items |
|------|-----------|-------|
| SCM lines | `moveTo()` + `lineTo()` per SCM | 50,000 lines |
| Stroke (batched by color) | `ctx.stroke()` | ~12 calls |

Total: **~100,000 Path2D operations/frame**.

### 3.4 Aggregate at 60 FPS

| Scenario | Ops/frame | Ops/sec |
|----------|----------|---------|
| Zoomed out (blocks) | ~27,000 | 1,620,000 |
| High zoom (SCMs) | ~107,000 | 6,420,000 |

---

## 4. Bottlenecks (Ranked)

### B1. Unthrottled wheel zoom (CRITICAL)

`onWheel()` updates `globalViewport` synchronously on every wheel event.
Wheel events fire at **100+ Hz** on most mice. Each update triggers 3 canvas
`$effect` redraws. Pointer-move panning already uses `requestAnimationFrame`
batching; wheel does not.

**Impact:** 100+ redraws/sec during scroll zoom instead of 60.

### B2. No viewport clipping in draw functions (HIGH)

`drawTracks()`, `drawRibbons()`, and `drawScmLines()` iterate **all** blocks,
paint regions, and SCMs regardless of whether they fall within the visible
viewport. At 1× zoom, most of a 4 Gb genome is off-screen, but every region
is still processed.

**Impact:** ~70% of Path2D operations are wasted on invisible geometry.

### B3. No API request cancellation (HIGH)

The three data-fetching `$effect` blocks fire 31 API calls on a reference
change. If the user changes reference again before the first batch completes,
both batches run to completion — no `AbortController` is used.

**Impact:** Doubled network traffic + map churn on rapid reference switching.

### B4. 50K SCM lines at high zoom (HIGH)

`/api/synteny/scms` returns up to 5,000 SCMs per pair × 10 pairs = 50,000
lines. Most are outside the visible viewport but still added to the Path2D.

**Impact:** 100K Path2D ops/frame at high zoom; frame rate drops to ~20 FPS.

### B5. Unbatched text rendering (MEDIUM)

`drawTracks()` renders chromosome labels one at a time with individual
`fillText()` + `strokeText()` calls (~1,250 calls for 625 sequences). These
are expensive GPU operations compared to batched path fills.

**Impact:** ~5 ms/frame on text alone; labels for off-screen sequences waste time.

### B6. Redundant paint regions (MEDIUM)

Backend paint regions are 1:1 with projected blocks. Adjacent regions with
the same `reference_seq` could be merged server-side, reducing region count
by ~30–50%.

**Impact:** Fewer Path2D rects in the paint overlay pass.

---

## 5. Optimization Plan

### Phase 1 — Frontend quick wins

Estimated improvement: **60–80% reduction in frame time**.

#### P1.1 rAF-throttle `onWheel`

Batch wheel events through `requestAnimationFrame`, same pattern as pointer-
move. Accumulate zoom factor across coalesced events, apply once per frame.

**Files:** `frontend/src/App.svelte` (`onWheel` handler).

#### P1.2 Viewport clipping in draw functions

Add an early `visibleRange()` check at the start of each drawing loop. Skip
any block, paint region, or SCM line whose genomic extent does not overlap
the viewport's visible basepair range.

For `drawTracks()`: skip sequences entirely off-screen.
For `drawRibbons()`: skip blocks where both g1 and g2 extents are off-screen.
For `drawScmLines()`: skip SCM lines where both endpoints are off-screen.

**Files:** `frontend/src/canvas/draw_tracks.ts`, `draw_ribbons.ts`, `draw_scms.ts`.

#### P1.3 AbortController on API effects

Create one `AbortController` per effect. On re-trigger, abort the previous
controller before starting new fetches. Pass `signal` to `api.blocks()`,
`api.scms()`, `api.paint()`.

**Files:** `frontend/src/App.svelte` (effects at L278–329).

### Phase 2 — Backend compute offloading

Estimated improvement: **30–50% smaller payloads, faster responses**.

#### P2.1 Server-side paint region merging

In `routes_paint.py`, after projecting blocks, merge adjacent paint regions
that share the same `reference_seq` on the same sequence. This reduces the
region count sent to the frontend.

**Files:** `syntrack/api/routes_paint.py`.

#### P2.2 Viewport-filtered SCM endpoint

The frontend already knows the visible basepair range. Pass it as `region_g1`
/ `region_g2` to `/api/synteny/scms` so the backend only returns SCMs within
the viewport. Currently the frontend fetches the full 5,000-cap without
region filtering during pan.

**Files:** `frontend/src/App.svelte` (SCM fetch effect), `frontend/src/api/client.ts`.

### Phase 3 — Rust/WASM (deferred)

These are deferred until Phase 1+2 results are measured.

#### P3.1 WASM geometry computation

Move the coordinate-transform + Path2D construction tight loop for ribbons
and SCM lines into a Rust→WASM module. The loop is vectorizable: for each
block, compute 4 pixel coordinates from (bp, viewport, total_length,
canvas_width) and emit a Float32Array of vertex positions.

#### P3.2 OffscreenCanvas Web Worker

Move the ribbon/SCM canvas rendering to an OffscreenCanvas in a Web Worker
so the main thread stays responsive during heavy draws. Requires
`transferControlToOffscreen()` and message-passing for viewport updates.

#### P3.3 Binary API responses

Replace JSON responses for `/api/synteny/scms` and `/api/synteny/blocks`
with a compact binary format (e.g., `ArrayBuffer` with fixed-width fields).
Eliminates JSON parse overhead for 50K-object arrays.

---

## 6. Memory Budget

| Structure | Entries | Size |
|-----------|---------|------|
| `allGenomes` | 11 | 55 KB |
| `pairBlocks` cache | 10 | 500 KB–1 MB |
| `pairScms` cache | 10 | 400–800 KB |
| `paintByPair` cache | 11–50 | 330 KB–1.5 MB |
| Canvas Path2D (per frame) | 6K–50K | 50–550 KB |
| **Total resident** | | **1.5–4 MB** |

Memory is not the bottleneck; CPU/GPU rendering throughput is.
