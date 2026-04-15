<script lang="ts">
  import { onMount } from 'svelte'
  import { SvelteMap, SvelteSet } from 'svelte/reactivity'

  import { api } from './api/client'
  import type {
    BlocksResponse,
    ConfigResponse,
    Genome,
    PaintRegion,
    SCMsResponse,
  } from './api/types'
  import { referenceColorMap } from './canvas/colors'
  import {
    DEFAULT_VIEWPORT,
    panByFraction,
    pixelsPerBp,
    visibleRange,
    zoomAtFraction,
    type Viewport,
  } from './canvas/coords'
  import {
    DEFAULT_LAYOUT,
    drawTracks,
    totalTrackedHeight,
  } from './canvas/draw_tracks'
  import { drawRibbons, type AdjacentPair } from './canvas/draw_ribbons'
  import { drawScmLines, type AdjacentPairScms } from './canvas/draw_scms'
  import { fmtBp } from './canvas/format'
  import { lodMode } from './canvas/lod'

  // ----------------------------- State -----------------------------------

  let genomes = $state<Genome[] | null>(null)
  let universeSize = $state(0)
  let order = $state<string[]>([])
  let viewport = $state<Viewport>(DEFAULT_VIEWPORT)
  let error = $state<string | null>(null)
  let config = $state<ConfigResponse | null>(null)

  // ----------------------------- Layout ----------------------------------

  let containerEl = $state<HTMLDivElement | undefined>(undefined)
  let trackCanvas = $state<HTMLCanvasElement | undefined>(undefined)
  let ribbonCanvas = $state<HTMLCanvasElement | undefined>(undefined)
  let canvasWidth = $state(800)
  let canvasHeight = $state(600)

  // Per-pair caches; keys are "g1|g2|reference" so reorder (→ new reference)
  // re-derives colors correctly.
  const pairBlocks = new SvelteMap<string, BlocksResponse>()
  const loadingBlocks = new SvelteSet<string>()
  const pairScms = new SvelteMap<string, SCMsResponse>()
  const loadingScms = new SvelteSet<string>()
  // Paint cache: key = "genome_id|reference"
  const paintByPair = new SvelteMap<string, PaintRegion[]>()
  const loadingPaint = new SvelteSet<string>()
  function pairKey(g1: string, g2: string, ref: string): string {
    return `${g1}|${g2}|${ref}`
  }
  function paintKey(genomeId: string, ref: string): string {
    return `${genomeId}|${ref}`
  }

  // ----------------------------- Drag state ------------------------------

  let dragState = $state<{ startX: number; startCenter: number } | null>(null)

  // Genome-reorder drag.
  let dragFromIdx = $state<number | null>(null)
  let dragOverIdx = $state<number | null>(null)

  // ----------------------------- Lifecycle -------------------------------

  onMount(async () => {
    try {
      const [genomeResp, cfgResp] = await Promise.all([api.genomes(), api.config()])
      genomes = genomeResp.genomes
      order = genomeResp.genomes.map((g) => g.id)
      universeSize = genomeResp.scm_universe_size
      config = cfgResp
    } catch (err) {
      error = err instanceof Error ? err.message : String(err)
    }
  })

  $effect(() => {
    if (!containerEl) return
    const ro = new ResizeObserver((entries) => {
      const e = entries[0]
      canvasWidth = e.contentRect.width
      canvasHeight = e.contentRect.height
    })
    ro.observe(containerEl)
    return () => ro.disconnect()
  })

  function sizeAndContext(canvas: HTMLCanvasElement, w: number, h: number) {
    const dpr = window.devicePixelRatio || 1
    const wi = Math.floor(w * dpr)
    const hi = Math.floor(h * dpr)
    if (canvas.width !== wi) canvas.width = wi
    if (canvas.height !== hi) canvas.height = hi
    canvas.style.width = `${w}px`
    canvas.style.height = `${h}px`
    const ctx = canvas.getContext('2d')
    if (!ctx) return null
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    return ctx
  }

  let genomesInOrder = $derived.by<Genome[]>(() => {
    if (!genomes) return []
    const byId = new Map(genomes.map((g) => [g.id, g]))
    return order
      .map((id) => byId.get(id))
      .filter((g): g is Genome => g !== undefined)
  })

  // The reference is always the top genome in current order (design §5.7).
  let referenceGenome = $derived<Genome | null>(genomesInOrder[0] ?? null)
  let refColorMap = $derived<Map<string, string>>(
    referenceGenome ? referenceColorMap(referenceGenome) : new Map(),
  )

  // LOD: blocks at low zoom, SCM lines at high zoom. Anchor on the top genome.
  let lodModeValue = $derived.by<'block' | 'scm'>(() => {
    if (genomesInOrder.length === 0 || canvasWidth < 2) return 'block'
    const ppb = pixelsPerBp(viewport, genomesInOrder[0].total_length, canvasWidth)
    const threshold = config?.rendering_defaults.block_threshold_bp_per_px ?? 50_000
    return lodMode(ppb, threshold)
  })

  let adjacentPairs = $derived.by<AdjacentPair[]>(() => {
    const out: AdjacentPair[] = []
    const ref = referenceGenome?.id ?? ''
    for (let i = 0; i < genomesInOrder.length - 1; i++) {
      const g1 = genomesInOrder[i]
      const g2 = genomesInOrder[i + 1]
      const cached = pairBlocks.get(pairKey(g1.id, g2.id, ref))
      out.push({
        topIndex: i,
        bottomIndex: i + 1,
        g1,
        g2,
        blocks: cached ? cached.blocks : null,
      })
    }
    return out
  })

  let adjacentPairsScms = $derived.by<AdjacentPairScms[]>(() => {
    const out: AdjacentPairScms[] = []
    const ref = referenceGenome?.id ?? ''
    for (let i = 0; i < genomesInOrder.length - 1; i++) {
      const g1 = genomesInOrder[i]
      const g2 = genomesInOrder[i + 1]
      const cached = pairScms.get(pairKey(g1.id, g2.id, ref))
      out.push({
        topIndex: i,
        bottomIndex: i + 1,
        g1,
        g2,
        scms: cached ? cached.scms : null,
      })
    }
    return out
  })

  // Fetch blocks for any adjacent pair we haven't seen yet (always — LOD-low default).
  $effect(() => {
    const ref = referenceGenome?.id
    if (!ref) return
    for (let i = 0; i < genomesInOrder.length - 1; i++) {
      const g1 = genomesInOrder[i].id
      const g2 = genomesInOrder[i + 1].id
      const key = pairKey(g1, g2, ref)
      if (pairBlocks.has(key) || loadingBlocks.has(key)) continue
      loadingBlocks.add(key)
      api.blocks(g1, g2, { reference: ref }).then(
        (resp) => pairBlocks.set(key, resp),
        (err) => {
          error = `Failed to load blocks for ${g1}/${g2}: ${err}`
        },
      ).finally(() => loadingBlocks.delete(key))
    }
  })

  // Fetch SCMs only when LOD switches to scm mode.
  $effect(() => {
    if (lodModeValue !== 'scm') return
    const ref = referenceGenome?.id
    if (!ref) return
    for (let i = 0; i < genomesInOrder.length - 1; i++) {
      const g1 = genomesInOrder[i].id
      const g2 = genomesInOrder[i + 1].id
      const key = pairKey(g1, g2, ref)
      if (pairScms.has(key) || loadingScms.has(key)) continue
      loadingScms.add(key)
      api.scms(g1, g2, { reference: ref }).then(
        (resp) => pairScms.set(key, resp),
        (err) => {
          error = `Failed to load SCMs for ${g1}/${g2}: ${err}`
        },
      ).finally(() => loadingScms.delete(key))
    }
  })

  // Fetch reference painting for every genome in order.
  $effect(() => {
    const ref = referenceGenome?.id
    if (!ref) return
    for (const g of genomesInOrder) {
      const key = paintKey(g.id, ref)
      if (paintByPair.has(key) || loadingPaint.has(key)) continue
      loadingPaint.add(key)
      api.paint(g.id, ref).then(
        (resp) => paintByPair.set(key, resp.regions),
        (err) => {
          error = `Failed to load painting for ${g.id}: ${err}`
        },
      ).finally(() => loadingPaint.delete(key))
    }
  })

  let paintByGenome = $derived.by<Map<string, PaintRegion[]>>(() => {
    const map = new Map<string, PaintRegion[]>()
    const ref = referenceGenome?.id
    if (!ref) return map
    for (const g of genomesInOrder) {
      const regions = paintByPair.get(paintKey(g.id, ref))
      if (regions) map.set(g.id, regions)
    }
    return map
  })

  // Track canvas redraws.
  $effect(() => {
    if (!trackCanvas || !genomes || canvasWidth < 2 || canvasHeight < 2) return
    const ctx = sizeAndContext(trackCanvas, canvasWidth, canvasHeight)
    if (!ctx) return
    drawTracks(
      ctx,
      genomesInOrder,
      viewport,
      canvasWidth,
      canvasHeight,
      paintByGenome,
      refColorMap,
    )
  })

  // Connection canvas: ribbons (LOD-low) or SCM lines (LOD-high).
  $effect(() => {
    if (!ribbonCanvas || canvasWidth < 2 || canvasHeight < 2) return
    const ctx = sizeAndContext(ribbonCanvas, canvasWidth, canvasHeight)
    if (!ctx) return
    if (lodModeValue === 'scm') {
      drawScmLines(ctx, adjacentPairsScms, viewport, canvasWidth, canvasHeight, refColorMap)
    } else {
      drawRibbons(ctx, adjacentPairs, viewport, canvasWidth, canvasHeight, refColorMap)
    }
  })

  // ----------------------------- Interaction -----------------------------

  function onWheel(e: WheelEvent) {
    if (!trackCanvas) return
    e.preventDefault()
    const rect = trackCanvas.getBoundingClientRect()
    const cursorFraction = (e.clientX - rect.left) / rect.width
    const factor = e.deltaY < 0 ? 1.25 : 1 / 1.25
    viewport = zoomAtFraction(viewport, cursorFraction, factor)
  }

  function onPointerDown(e: PointerEvent) {
    if (e.button !== 0) return
    dragState = { startX: e.clientX, startCenter: viewport.center }
    ;(e.target as Element).setPointerCapture(e.pointerId)
  }

  function onPointerMove(e: PointerEvent) {
    if (!dragState) return
    const dx = e.clientX - dragState.startX
    const fraction = dx / canvasWidth
    viewport = panByFraction(
      { zoom: viewport.zoom, center: dragState.startCenter },
      fraction,
    )
  }

  function onPointerUp(_e: PointerEvent) {
    dragState = null
  }

  function resetView() {
    viewport = DEFAULT_VIEWPORT
  }

  // Reorder handlers (HTML5 drag/drop).
  function onRowDragStart(e: DragEvent, idx: number) {
    dragFromIdx = idx
    if (e.dataTransfer) {
      e.dataTransfer.effectAllowed = 'move'
      e.dataTransfer.setData('text/plain', String(idx))
    }
  }

  function onRowDragOver(e: DragEvent, idx: number) {
    e.preventDefault()
    if (e.dataTransfer) e.dataTransfer.dropEffect = 'move'
    dragOverIdx = idx
  }

  function onRowDragLeave(idx: number) {
    if (dragOverIdx === idx) dragOverIdx = null
  }

  function onRowDrop(e: DragEvent, toIdx: number) {
    e.preventDefault()
    const fromIdx = dragFromIdx
    dragFromIdx = null
    dragOverIdx = null
    if (fromIdx === null || fromIdx === toIdx) return
    const next = [...order]
    const [moved] = next.splice(fromIdx, 1)
    next.splice(toIdx, 0, moved)
    order = next
  }

  function onRowDragEnd() {
    dragFromIdx = null
    dragOverIdx = null
  }

  function genomeById(gid: string): Genome | undefined {
    return genomes?.find((g) => g.id === gid)
  }

  // ----------------------------- Status helpers --------------------------

  let statusLine = $derived.by(() => {
    if (!genomes || genomes.length === 0) return ''
    // Use the first ordered genome as the anchor for status display
    const byId = new Map(genomes.map((g) => [g.id, g]))
    const anchor = byId.get(order[0]) ?? genomes[0]
    const { startBp, endBp } = visibleRange(viewport, anchor.total_length, canvasWidth)
    const ppb = pixelsPerBp(viewport, anchor.total_length, canvasWidth)
    const bpPerPx = ppb > 0 ? 1 / ppb : 0
    return (
      `${anchor.label}: ${fmtBp(startBp)} – ${fmtBp(endBp)}  ` +
      `(${(bpPerPx / 1000).toFixed(1)} kb/px, zoom ${viewport.zoom.toFixed(1)}×, LOD: ${lodModeValue})`
    )
  })

  let canvasContentHeight = $derived(
    genomes ? totalTrackedHeight(genomes.length, DEFAULT_LAYOUT) : 0,
  )
</script>

<header>
  <h1>SynTrack</h1>
  {#if genomes}
    <span class="meta"
      >{genomes.length} genomes · {universeSize.toLocaleString()} SCMs</span
    >
  {/if}
  <button onclick={resetView} disabled={!genomes}>Reset view</button>
</header>

<main>
  {#if error}
    <div class="error">{error}</div>
  {:else if genomes === null}
    <p class="loading">Loading genomes…</p>
  {:else}
    <aside class="sidebar" role="list" aria-label="Genome order">
      {#each order as gid, i (gid)}
        {@const g = genomeById(gid)}
        {#if g}
          <div
            class="genome-row"
            class:dragging={dragFromIdx === i}
            class:drop-target={dragOverIdx === i && dragFromIdx !== i}
            role="listitem"
            draggable="true"
            ondragstart={(e) => onRowDragStart(e, i)}
            ondragover={(e) => onRowDragOver(e, i)}
            ondragleave={() => onRowDragLeave(i)}
            ondrop={(e) => onRowDrop(e, i)}
            ondragend={onRowDragEnd}
          >
            <span class="handle" aria-hidden="true">≡</span>
            <span class="row-label">{g.label}</span>
            <span class="row-meta">{g.scm_count.toLocaleString()}</span>
          </div>
        {/if}
      {/each}
    </aside>

    <div
      bind:this={containerEl}
      class="canvas-container"
      role="application"
      aria-label="Synteny canvas"
      style:cursor={dragState ? 'grabbing' : 'grab'}
      onwheel={onWheel}
      onpointerdown={onPointerDown}
      onpointermove={onPointerMove}
      onpointerup={onPointerUp}
      onpointercancel={onPointerUp}
    >
      <div
        class="canvas-stack"
        style:height={`${Math.max(canvasHeight, canvasContentHeight)}px`}
      >
        <canvas bind:this={ribbonCanvas} class="layer ribbons"></canvas>
        <canvas bind:this={trackCanvas} class="layer tracks"></canvas>
      </div>
      {#if loadingBlocks.size + loadingScms.size + loadingPaint.size > 0}
        {@const total = loadingBlocks.size + loadingScms.size + loadingPaint.size}
        <div class="badge">
          loading {total} request{total === 1 ? '' : 's'}…
        </div>
      {/if}
    </div>
  {/if}
</main>

<footer>
  <span class="status">{statusLine}</span>
</footer>

<style>
  header {
    padding: 0.4em 1em;
    border-bottom: 1px solid #333;
    background: #232323;
    display: flex;
    align-items: center;
    gap: 1em;
  }

  h1 {
    margin: 0;
    font-size: 1.1em;
    font-weight: 500;
  }

  .meta {
    color: #888;
    font-size: 0.9em;
  }

  main {
    flex: 1;
    overflow: hidden;
    display: flex;
    min-height: 0;
  }

  .sidebar {
    flex: 0 0 220px;
    border-right: 1px solid #333;
    background: #1f1f1f;
    overflow-y: auto;
    padding: 0.4em 0;
  }

  .genome-row {
    display: flex;
    align-items: center;
    gap: 0.5em;
    padding: 0.4em 0.6em;
    cursor: grab;
    border-bottom: 1px solid #2a2a2a;
    user-select: none;
  }

  .genome-row:hover {
    background: #2a2a2a;
  }

  .genome-row.dragging {
    opacity: 0.4;
    cursor: grabbing;
  }

  .genome-row.drop-target {
    background: #1f3a4a;
    box-shadow: inset 0 -2px 0 #4ab2e0;
  }

  .handle {
    color: #777;
    font-size: 0.95em;
  }

  .row-label {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .row-meta {
    color: #888;
    font-size: 0.8em;
    font-variant-numeric: tabular-nums;
  }

  .loading,
  .error {
    margin: 1em;
  }

  .canvas-container {
    width: 100%;
    height: 100%;
    overflow-y: auto;
    overflow-x: hidden;
    user-select: none;
    touch-action: none;
  }

  .canvas-stack {
    position: relative;
    width: 100%;
  }

  .layer {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    display: block;
  }

  .ribbons {
    /* drawn first; tracks on top to mask the strip behind genome bars */
    z-index: 1;
  }

  .tracks {
    z-index: 2;
    pointer-events: none;
  }

  .badge {
    position: absolute;
    bottom: 8px;
    right: 8px;
    background: rgba(40, 40, 40, 0.85);
    border: 1px solid #555;
    padding: 0.3em 0.6em;
    border-radius: 3px;
    color: #ddd;
    font-size: 0.8em;
    pointer-events: none;
  }

  footer {
    padding: 0.3em 1em;
    background: #232323;
    border-top: 1px solid #333;
    font-size: 0.85em;
    color: #aaa;
    font-variant-numeric: tabular-nums;
    min-height: 1.4em;
  }
</style>
