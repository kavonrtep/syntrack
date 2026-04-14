<script lang="ts">
  import { onMount } from 'svelte'

  import { api } from './api/client'
  import type { Genome } from './api/types'
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
  import { fmtBp } from './canvas/format'

  // ----------------------------- State -----------------------------------

  let genomes = $state<Genome[] | null>(null)
  let universeSize = $state(0)
  let order = $state<string[]>([])
  let viewport = $state<Viewport>(DEFAULT_VIEWPORT)
  let error = $state<string | null>(null)

  // ----------------------------- Layout ----------------------------------

  let containerEl = $state<HTMLDivElement | undefined>(undefined)
  let trackCanvas = $state<HTMLCanvasElement | undefined>(undefined)
  let canvasWidth = $state(800)
  let canvasHeight = $state(600)

  // ----------------------------- Drag state ------------------------------

  let dragState = $state<{ startX: number; startCenter: number } | null>(null)

  // ----------------------------- Lifecycle -------------------------------

  onMount(async () => {
    try {
      const r = await api.genomes()
      genomes = r.genomes
      order = r.genomes.map((g) => g.id)
      universeSize = r.scm_universe_size
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

  // Re-draw whenever genomes / order / viewport / size changes.
  $effect(() => {
    if (!trackCanvas || !genomes || canvasWidth < 2 || canvasHeight < 2) return

    const dpr = window.devicePixelRatio || 1
    if (trackCanvas.width !== Math.floor(canvasWidth * dpr)) {
      trackCanvas.width = Math.floor(canvasWidth * dpr)
    }
    if (trackCanvas.height !== Math.floor(canvasHeight * dpr)) {
      trackCanvas.height = Math.floor(canvasHeight * dpr)
    }
    trackCanvas.style.width = `${canvasWidth}px`
    trackCanvas.style.height = `${canvasHeight}px`

    const ctx = trackCanvas.getContext('2d')
    if (!ctx) return
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)

    const byId = new Map(genomes.map((g) => [g.id, g]))
    const genomesInOrder = order
      .map((id) => byId.get(id))
      .filter((g): g is Genome => g !== undefined)

    drawTracks(ctx, genomesInOrder, viewport, canvasWidth, canvasHeight)
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
      `(${(bpPerPx / 1000).toFixed(1)} kb/px, zoom ${viewport.zoom.toFixed(1)}×)`
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
      <canvas
        bind:this={trackCanvas}
        style:height={`${Math.max(canvasHeight, canvasContentHeight)}px`}
      ></canvas>
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
    position: relative;
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

  canvas {
    display: block;
    width: 100%;
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
