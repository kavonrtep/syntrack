<script lang="ts">
  import { onMount } from 'svelte'
  import { SvelteMap, SvelteSet } from 'svelte/reactivity'

  import { api } from './api/client'
  import type {
    BlocksResponse,
    ConfigResponse,
    FishDensityResponse,
    FishSetResponse,
    Genome,
    HighlightResponse,
    PaintRegion,
    PaintResponse,
    SCMsResponse,
  } from './api/types'
  import { alignmentDelta } from './canvas/alignment'

  import {
    DEFAULT_VIEWPORT,
    panByFraction,
    pixelsPerBp,
    pxToBp,
    visibleRange,
    visibleRegionString,
    zoomAtFraction,
    type Viewport,
  } from './canvas/coords'
  import {
    DEFAULT_LAYOUT,
    drawTracks,
    totalTrackedHeight,
    trackY,
  } from './canvas/draw_tracks'
  import {
    drawHighlight,
    type HighlightOverlay,
    type HighlightSource,
  } from './canvas/draw_highlight'
  import { drawFishSets } from './canvas/draw_fish'
  import { drawFishDensity } from './canvas/draw_fish_density'
  import { downloadCanvasPng, exportBins, renderFishDensityImage } from './canvas/fish_export'
  import type { AdjacentPair } from './canvas/draw_ribbons'
  import type { AdjacentPairScms } from './canvas/draw_scms'
  import { RibbonRenderer } from './canvas/ribbon_renderer'
  import type { RibbonData, RibbonView } from './canvas/ribbon_protocol'
  import {
    buildPresenceTsv,
    downloadTextFile,
    presenceFromBitstrings,
    safeFilenamePart,
  } from './scm_export'
  import { fmtBp } from './canvas/format'
  import { genomeIndexAt } from './canvas/hit_test'
  import { lodMode } from './canvas/lod'

  // ----------------------------- State -----------------------------------

  // `allGenomes` is the stable server-load order (immutable after mount).
  // `fullOrder` tracks the user's preferred display order for *all* genomes
  // (visible and hidden) — drag-reorder mutates this.  `visibleIds` tracks
  // which genomes are currently checked.  The derived `order` is the visible
  // subset of `fullOrder`, used by all rendering code.
  let allGenomes = $state<Genome[] | null>(null)
  let universeSize = $state(0)
  let fullOrder = $state<string[]>([])
  const visibleIds = new SvelteSet<string>()
  let order = $derived(fullOrder.filter((id) => visibleIds.has(id)))
  // null = "follow top genome" (default); a genome ID locks coloring to that genome.
  let selectedReferenceId = $state<string | null>(null)

  // User-chosen chromosome colors for the reference genome. Empty = all grey.
  const seqColors = new SvelteMap<string, string>()
  const DEFAULT_SEQ_COLOR = '#888888'
  // Track which seq is being edited via the native color picker.
  let colorPickerSeq = $state<string | null>(null)
  let colorPickerEl: HTMLInputElement | undefined = $state()

  let globalViewport = $state<Viewport>(DEFAULT_VIEWPORT)
  type ScopeDelta = { zoomFactor: number; centerDelta: number }
  const viewportOverrides = new SvelteMap<string, ScopeDelta>()
  let error = $state<string | null>(null)
  let config = $state<ConfigResponse | null>(null)

  function effectiveViewport(genomeId: string): Viewport {
    const od = viewportOverrides.get(genomeId)
    if (!od) return globalViewport
    return {
      zoom: Math.max(1, globalViewport.zoom * od.zoomFactor),
      center: Math.min(1, Math.max(0, globalViewport.center + od.centerDelta)),
    }
  }
  const viewportFn = (gid: string): Viewport => effectiveViewport(gid)

  // ----------------------------- Layout ----------------------------------

  let containerEl = $state<HTMLDivElement | undefined>(undefined)
  let trackCanvas = $state<HTMLCanvasElement | undefined>(undefined)
  let ribbonCanvas = $state<HTMLCanvasElement | undefined>(undefined)
  let overlayCanvas = $state<HTMLCanvasElement | undefined>(undefined)
  // Connection layer (ribbons / SCM lines) is rendered via this handle, which
  // offloads to a worker + OffscreenCanvas when supported.
  let ribbonRenderer = $state<RibbonRenderer | null>(null)
  let canvasWidth = $state(800)
  let canvasHeight = $state(600)

  // Data caches: LRU-capped Maps to avoid per-item reactive overhead and
  // unbounded memory growth across reference/reorder changes. A single
  // reactive counter bumps once per batch of responses so deriveds/effects
  // recompute only once instead of N times.
  class LRUMap<K, V> extends Map<K, V> {
    _cap: number
    constructor(cap: number) { super(); this._cap = cap }
    override get(key: K): V | undefined {
      const v = super.get(key)
      if (v !== undefined) { super.delete(key); super.set(key, v) }
      return v
    }
    override set(key: K, value: V): this {
      if (super.has(key)) super.delete(key)
      super.set(key, value)
      while (super.size > this._cap) {
        const oldest = super.keys().next().value!
        super.delete(oldest)
      }
      return this
    }
  }
  const pairBlocks = new LRUMap<string, BlocksResponse>(50)
  const pairScms = new LRUMap<string, SCMsResponse>(30)
  const paintByPair = new LRUMap<string, PaintRegion[]>(40)
  let dataVersion = $state(0)
  // Plain counter — not reactive. Exposed to the template via dataVersion bumps.
  let _loadingCount = 0
  // Reactive loading flag set outside effects (from Promise callbacks only).
  let loadingData = $state(false)
  function pairKey(g1: string, g2: string, ref: string): string {
    return `${g1}|${g2}|${ref}`
  }
  function paintKey(genomeId: string, ref: string): string {
    return `${genomeId}|${ref}`
  }

  // ----------------------------- Drag state ------------------------------

  let dragState = $state<{
    startX: number
    startY: number
    startCenter: number
    target: string | null
  } | null>(null)

  let pendingPointer: { clientX: number } | null = null
  let pendingFrame: number | null = null

  // Track-handle reorder drag (HTML5 DnD on the DOM handle overlay).
  let reorderFromIdx = $state<number | null>(null)
  let reorderOverIdx = $state<number | null>(null)

  // Highlight region selection (Ctrl / Meta + click-drag).
  let highlightSelection = $state<HighlightSource | null>(null)
  let highlightResult = $state<HighlightResponse | null>(null)
  let highlightDragging = $state(false)
  // True while the export re-fetches the full (uncapped) SCM set for download.
  let downloadingScms = $state(false)

  // FISH marker sets — keyed by label.
  const fishSets = new SvelteMap<string, FishSetResponse>()
  const fishVisible = new SvelteSet<string>()
  let fishLoading = $state(false)
  // Label of the set currently being saved to file (null = none).
  let fishFileSaving = $state<string | null>(null)

  // FISH density preview: a frozen, whole-genome, multi-colour density render
  // of the visible marker sets (a synthetic FISH karyotype). While on, pan/zoom
  // is disabled and connections are hidden.
  let fishPreview = $state(false)
  let fishDensityResult = $state<FishDensityResponse | null>(null)
  let fishDensityLoading = $state(false)
  let fishDensityError = $state<string | null>(null)
  let fishExporting = $state(false)
  let savingHighlightSet = $state(false)
  // View saved on entering preview, restored on exit.
  let savedPreviewView: { vp: Viewport; overrides: Map<string, ScopeDelta> } | null = null

  // Small rotating palette for auto-assigning FISH set colors.
  const FISH_PALETTE = [
    '#e6194b', '#3cb44b', '#4363d8', '#f58231', '#911eb4',
    '#42d4f4', '#f032e6', '#bfef45', '#fabed4', '#469990',
  ] as const
  let fishColorIdx = 0
  function nextFishColor(): string {
    return FISH_PALETTE[fishColorIdx++ % FISH_PALETTE.length]
  }

  // Fade slider: dims painted bars, ribbons and SCM lines so the highlight
  // overlay stands out. 0 = normal, 0.9 = very faded. Does not affect the
  // highlight overlay, chromosome separators, or genome / sequence labels.
  let fadeLevel = $state(0)
  let fadeMultiplier = $derived(1 - fadeLevel)

  // Highlighted-SCM count per genome, derived from the /highlight response.
  // Source genome gets source.scm_count; every target gets its own scm_count
  // (backend returns an entry for every non-source genome, possibly 0).
  let highlightedByGenome = $derived.by<Map<string, number>>(() => {
    const m = new Map<string, number>()
    if (!highlightResult) return m
    m.set(highlightResult.source.genome_id, highlightResult.source.scm_count)
    for (const t of highlightResult.targets) {
      m.set(t.genome_id, t.scm_count)
    }
    return m
  })

  // ----------------------------- Lifecycle -------------------------------

  onMount(async () => {
    try {
      const [genomeResp, cfgResp] = await Promise.all([api.genomes(), api.config()])
      allGenomes = genomeResp.genomes
      fullOrder = genomeResp.genomes.map((g) => g.id)
      for (const g of genomeResp.genomes) visibleIds.add(g.id)
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
    if (!allGenomes) return []
    const byId = new Map(allGenomes.map((g) => [g.id, g]))
    return order
      .map((id) => byId.get(id))
      .filter((g): g is Genome => g !== undefined)
  })

  let referenceGenome = $derived.by<Genome | null>(() => {
    if (!allGenomes) return null
    if (selectedReferenceId) {
      const found = allGenomes.find((g) => g.id === selectedReferenceId)
      if (found) return found
    }
    return genomesInOrder[0] ?? null
  })
  let refColorMap = $derived.by<Map<string, string>>(() => {
    if (!referenceGenome) return new Map()
    const map = new Map<string, string>()
    for (const s of referenceGenome.sequences) {
      map.set(s.name, seqColors.get(s.name) ?? DEFAULT_SEQ_COLOR)
    }
    return map
  })

  // Clear user-chosen colors when the reference genome changes.
  let prevRefId: string | undefined
  $effect(() => {
    const id = referenceGenome?.id
    if (id !== prevRefId) {
      seqColors.clear()
      prevRefId = id
    }
  })

  let lodModeValue = $derived.by<'block' | 'scm'>(() => {
    if (genomesInOrder.length === 0 || canvasWidth < 2) return 'block'
    const top = genomesInOrder[0]
    const ppb = pixelsPerBp(effectiveViewport(top.id), top.total_length, canvasWidth)
    const threshold = config?.rendering_defaults.block_threshold_bp_per_px ?? 50_000
    return lodMode(ppb, threshold)
  })

  let adjacentPairs = $derived.by<AdjacentPair[]>(() => {
    void dataVersion // recompute when batch arrives
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

  /** Find the most recently cached SCM entry for a pair+ref, regardless of region. */
  function findScmsEntry(g1id: string, g2id: string, ref: string): SCMsResponse | undefined {
    const prefix = `${g1id}|${g2id}|${ref}|`
    for (const [k, v] of pairScms) {
      if (k.startsWith(prefix)) return v
    }
    return undefined
  }

  let adjacentPairsScms = $derived.by<AdjacentPairScms[]>(() => {
    void dataVersion // recompute when batch arrives
    const out: AdjacentPairScms[] = []
    const ref = referenceGenome?.id ?? ''
    for (let i = 0; i < genomesInOrder.length - 1; i++) {
      const g1 = genomesInOrder[i]
      const g2 = genomesInOrder[i + 1]
      const cached = findScmsEntry(g1.id, g2.id, ref)
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

  // AbortControllers — cancel in-flight requests when dependencies change.
  // Responses are collected with Promise.allSettled and flushed into the
  // plain-Map caches in one synchronous block, bumping `dataVersion` once
  // so reactive deriveds/effects recompute exactly once per batch.
  let blocksAbort: AbortController | undefined
  let scmsAbort: AbortController | undefined
  let paintAbort: AbortController | undefined

  $effect(() => {
    blocksAbort?.abort()
    blocksAbort = new AbortController()
    const { signal } = blocksAbort
    const ref = referenceGenome?.id
    if (!ref) return
    const pending: { key: string; promise: Promise<BlocksResponse> }[] = []
    for (let i = 0; i < genomesInOrder.length - 1; i++) {
      const g1 = genomesInOrder[i].id
      const g2 = genomesInOrder[i + 1].id
      const key = pairKey(g1, g2, ref)
      if (pairBlocks.has(key)) continue
      pending.push({ key, promise: api.blocks(g1, g2, { reference: ref }, signal) })
    }
    if (pending.length === 0) return
    _loadingCount += pending.length
    loadingData = true
    void Promise.allSettled(pending.map((p) => p.promise)).then((results) => {
      _loadingCount -= pending.length
      if (signal.aborted) { loadingData = _loadingCount > 0; return }
      for (let i = 0; i < results.length; i++) {
        const r = results[i]
        if (r.status === 'fulfilled') pairBlocks.set(pending[i].key, r.value)
      }
      dataVersion++
      loadingData = _loadingCount > 0
    })
  })

  // SCM fetching: viewport-filtered with debounce.
  // Clear cached SCMs when viewport changes so the next fetch uses fresh regions.
  let scmsDebounceTimer: ReturnType<typeof setTimeout> | undefined

  $effect(() => {
    scmsAbort?.abort()
    scmsAbort = new AbortController()
    clearTimeout(scmsDebounceTimer)
    if (lodModeValue !== 'scm') return
    const ref = referenceGenome?.id
    if (!ref) return
    // Capture reactive dependencies: viewport + canvas width for region computation.
    void globalViewport
    void viewportOverrides.size // track per-genome overrides
    const cw = canvasWidth
    const genomes = genomesInOrder
    const signal = scmsAbort.signal

    // Debounce: re-fetch 200ms after the last viewport/order change.
    scmsDebounceTimer = setTimeout(() => {
      if (signal.aborted) return
      const pending: { key: string; promise: Promise<SCMsResponse> }[] = []
      for (let i = 0; i < genomes.length - 1; i++) {
        const g1 = genomes[i]
        const g2 = genomes[i + 1]
        const region_g1 = visibleRegionString(g1, effectiveViewport(g1.id), cw)
        const region_g2 = visibleRegionString(g2, effectiveViewport(g2.id), cw)
        // Region-keyed: different viewport positions produce distinct cache entries.
        const key = `${g1.id}|${g2.id}|${ref}|${region_g1 ?? '*'}|${region_g2 ?? '*'}`
        if (pairScms.has(key)) continue
        pending.push({
          key,
          promise: api.scms(g1.id, g2.id, { reference: ref, region_g1, region_g2 }, signal),
        })
      }
      if (pending.length === 0) return
      _loadingCount += pending.length
      loadingData = true
      void Promise.allSettled(pending.map((p) => p.promise)).then((results) => {
        _loadingCount -= pending.length
        if (signal.aborted) { loadingData = _loadingCount > 0; return }
        for (let i = 0; i < results.length; i++) {
          const r = results[i]
          if (r.status === 'fulfilled') pairScms.set(pending[i].key, r.value)
        }
        dataVersion++
        loadingData = _loadingCount > 0
      })
    }, 200)

    return () => clearTimeout(scmsDebounceTimer)
  })

  $effect(() => {
    paintAbort?.abort()
    paintAbort = new AbortController()
    const { signal } = paintAbort
    const ref = referenceGenome?.id
    if (!ref) return
    const pending: { key: string; promise: Promise<PaintResponse> }[] = []
    for (const g of genomesInOrder) {
      const key = paintKey(g.id, ref)
      if (paintByPair.has(key)) continue
      pending.push({ key, promise: api.paint(g.id, ref, signal) })
    }
    if (pending.length === 0) return
    _loadingCount += pending.length
    loadingData = true
    void Promise.allSettled(pending.map((p) => p.promise)).then((results) => {
      _loadingCount -= pending.length
      if (signal.aborted) { loadingData = _loadingCount > 0; return }
      for (let i = 0; i < results.length; i++) {
        const r = results[i]
        if (r.status === 'fulfilled') paintByPair.set(pending[i].key, r.value.regions)
      }
      dataVersion++
      loadingData = _loadingCount > 0
    })
  })

  let paintByGenome = $derived.by<Map<string, PaintRegion[]>>(() => {
    void dataVersion // recompute when batch arrives
    const map = new Map<string, PaintRegion[]>()
    const ref = referenceGenome?.id
    if (!ref) return map
    for (const g of genomesInOrder) {
      const regions = paintByPair.get(paintKey(g.id, ref))
      if (regions) map.set(g.id, regions)
    }
    return map
  })

  $effect(() => {
    if (!trackCanvas || !allGenomes || canvasWidth < 2 || effectiveCanvasHeight < 2) return
    void viewportOverrides.size
    void globalViewport
    const ctx = sizeAndContext(trackCanvas, canvasWidth, effectiveCanvasHeight)
    if (!ctx) return
    if (fishPreview) {
      // Frozen, whole-genome multi-colour FISH density in place of the tracks.
      drawFishDensity(
        ctx,
        fishDensityResult?.sets ?? [],
        fishVisible,
        genomesInOrder,
        fishDensityResult?.bins ?? 0,
        canvasWidth,
        effectiveCanvasHeight,
      )
      return
    }
    drawTracks(
      ctx,
      genomesInOrder,
      viewportFn,
      canvasWidth,
      effectiveCanvasHeight,
      paintByGenome,
      refColorMap,
      referenceGenome?.id ?? null,
      fadeMultiplier,
    )
  })

  // OffscreenCanvas worker for the connection layer is opt-in pending browser
  // verification (enable with ?ribbonWorker=1). Default is main-thread render,
  // which is the proven path.
  const useRibbonWorker =
    typeof location !== 'undefined' &&
    new URLSearchParams(location.search).get('ribbonWorker') === '1'

  // Create the ribbon renderer once the canvas is mounted. Disposed on teardown.
  $effect(() => {
    if (!ribbonCanvas) return
    const r = new RibbonRenderer(ribbonCanvas, useRibbonWorker)
    ribbonRenderer = r
    return () => {
      r.dispose()
      ribbonRenderer = null
    }
  })

  // Data effect: forward synteny data to the renderer when it (re)fetches.
  // Only when rendering off-thread do we snapshot genome $state proxies to
  // plain clonable values; the main-thread path uses the data directly, exactly
  // as before (no snapshot, no structured clone).
  $effect(() => {
    const r = ribbonRenderer
    if (!r) return
    let pairs = adjacentPairs
    let pairsScms = adjacentPairsScms
    if (r.offscreen) {
      const plain = new Map(genomesInOrder.map((g) => [g.id, $state.snapshot(g) as Genome]))
      pairs = adjacentPairs.map((p) => ({
        ...p,
        g1: plain.get(p.g1.id) ?? p.g1,
        g2: plain.get(p.g2.id) ?? p.g2,
      }))
      pairsScms = adjacentPairsScms.map((p) => ({
        ...p,
        g1: plain.get(p.g1.id) ?? p.g1,
        g2: plain.get(p.g2.id) ?? p.g2,
      }))
    }
    const data: RibbonData = { pairs, pairsScms, colorMap: Array.from(refColorMap) }
    r.setData(data)
  })

  // Render effect: push a frame whenever the viewport, size, fade, or LOD
  // changes. Light payload — heavy data is cached in the renderer/worker.
  $effect(() => {
    const r = ribbonRenderer
    // Connections are hidden during FISH preview (and the layer is CSS-hidden).
    if (!r || fishPreview || canvasWidth < 2 || effectiveCanvasHeight < 2) return
    void viewportOverrides.size
    void globalViewport
    const viewports: Record<string, Viewport> = {}
    for (const g of genomesInOrder) viewports[g.id] = effectiveViewport(g.id)
    const view: RibbonView = {
      viewports,
      canvasWidth,
      canvasHeight: effectiveCanvasHeight,
      dpr: window.devicePixelRatio || 1,
      fade: fadeMultiplier,
      lodMode: lodModeValue,
    }
    r.render(view)
  })

  $effect(() => {
    if (!overlayCanvas || canvasWidth < 2 || effectiveCanvasHeight < 2) return
    void viewportOverrides.size
    void globalViewport
    const ctx = sizeAndContext(overlayCanvas, canvasWidth, effectiveCanvasHeight)
    if (!ctx) return
    ctx.clearRect(0, 0, canvasWidth, effectiveCanvasHeight)
    // FISH preview owns the whole view; no overlay ticks/highlight on top.
    if (fishPreview) return
    // FISH ticks first (underneath highlight).
    drawFishSets(ctx, fishSets, fishVisible, genomesInOrder, viewportFn, canvasWidth, effectiveCanvasHeight)
    // Transient highlight on top.
    const overlay: HighlightOverlay = {
      source: highlightSelection,
      isSelecting: highlightDragging,
      result: highlightResult,
    }
    drawHighlight(ctx, overlay, genomesInOrder, viewportFn, canvasWidth, effectiveCanvasHeight)
  })

  // ----------------------------- Visibility (sidebar) --------------------

  function isVisible(id: string): boolean {
    return visibleIds.has(id)
  }

  // Sidebar list: every genome in its fullOrder position, visible or hidden.
  // Unchecking a genome leaves its row exactly where it is (just dimmed) so the
  // user keeps the original position in view; re-checking it doesn't move it.
  let sidebarGenomes = $derived.by<Genome[]>(() => {
    if (!allGenomes) return []
    const byId = new Map(allGenomes.map((g) => [g.id, g]))
    return fullOrder
      .map((id) => byId.get(id))
      .filter((g): g is Genome => g !== undefined)
  })

  function toggleVisible(id: string) {
    if (visibleIds.has(id)) {
      visibleIds.delete(id)
    } else {
      visibleIds.add(id)
    }
  }

  function selectAll() {
    if (!allGenomes) return
    for (const g of allGenomes) visibleIds.add(g.id)
  }

  function selectNone() {
    visibleIds.clear()
  }

  // ----------------------------- Interaction -----------------------------

  function pointerGenomeId(clientY: number): string | null {
    if (!trackCanvas) return null
    const rect = trackCanvas.getBoundingClientRect()
    const y = clientY - rect.top
    const idx = genomeIndexAt(y, genomesInOrder.length)
    return idx === null ? null : genomesInOrder[idx].id
  }

  // rAF-throttled wheel zoom: accumulate zoom factor across coalesced wheel
  // events and apply once per animation frame (same pattern as pointer-move).
  let pendingWheel: {
    cursorFraction: number
    accumulatedFactor: number
    scoped: string | null
    clientY: number
  } | null = null
  let pendingWheelFrame: number | null = null

  function onWheel(e: WheelEvent) {
    if (!trackCanvas || fishPreview) return
    e.preventDefault()
    const rect = trackCanvas.getBoundingClientRect()
    const cursorFraction = (e.clientX - rect.left) / rect.width
    const factor = e.deltaY < 0 ? 1.25 : 1 / 1.25
    const scoped = e.shiftKey ? pointerGenomeId(e.clientY) : null
    if (pendingWheel && pendingWheel.scoped === scoped) {
      pendingWheel.cursorFraction = cursorFraction
      pendingWheel.accumulatedFactor *= factor
    } else {
      pendingWheel = { cursorFraction, accumulatedFactor: factor, scoped, clientY: e.clientY }
    }
    if (pendingWheelFrame !== null) return
    pendingWheelFrame = requestAnimationFrame(() => {
      pendingWheelFrame = null
      const pw = pendingWheel
      pendingWheel = null
      if (!pw) return
      if (pw.scoped) {
        const current = effectiveViewport(pw.scoped)
        const next = zoomAtFraction(current, pw.cursorFraction, pw.accumulatedFactor)
        viewportOverrides.set(pw.scoped, {
          zoomFactor: next.zoom / globalViewport.zoom,
          centerDelta: next.center - globalViewport.center,
        })
      } else {
        globalViewport = zoomAtFraction(globalViewport, pw.cursorFraction, pw.accumulatedFactor)
      }
    })
  }

  /** Resolve the clicked (genome, seq, local bp, xCanvas) or null if the
   *  cursor isn't over any track. */
  function resolveTrackClick(
    clientX: number,
    clientY: number,
  ): {
    genomeIdx: number
    genome: Genome
    seq: string
    bpLocal: number
    xCanvas: number
  } | null {
    if (!trackCanvas) return null
    const rect = trackCanvas.getBoundingClientRect()
    const x = clientX - rect.left
    const y = clientY - rect.top
    const idx = genomeIndexAt(y, genomesInOrder.length)
    if (idx === null) return null
    const g = genomesInOrder[idx]
    const vp = effectiveViewport(g.id)
    const bpGlobal = pxToBp(x, vp, g.total_length, canvasWidth)
    const clamped = Math.max(0, Math.min(g.total_length - 1, bpGlobal))
    let clickedSeq = g.sequences[g.sequences.length - 1]
    for (const s of g.sequences) {
      if (clamped >= s.offset && clamped < s.offset + s.length) {
        clickedSeq = s
        break
      }
    }
    return {
      genomeIdx: idx,
      genome: g,
      seq: clickedSeq.name,
      bpLocal: Math.max(0, Math.round(clamped - clickedSeq.offset)),
      xCanvas: x,
    }
  }

  function onPointerDown(e: PointerEvent) {
    if (e.button !== 0 || fishPreview) return
    // Ctrl / Meta + click-drag → start a highlight region selection.
    if (e.ctrlKey || e.metaKey) {
      const click = resolveTrackClick(e.clientX, e.clientY)
      if (!click) return
      e.preventDefault()
      ;(e.target as Element).setPointerCapture(e.pointerId)
      highlightSelection = {
        genomeId: click.genome.id,
        genome: click.genome,
        seq: click.seq,
        startBp: click.bpLocal,
        endBp: click.bpLocal,
      }
      highlightResult = null
      highlightDragging = true
      return
    }
    const scoped = e.shiftKey ? pointerGenomeId(e.clientY) : null
    const target = scoped
    const startCenter = target ? effectiveViewport(target).center : globalViewport.center
    dragState = { startX: e.clientX, startY: e.clientY, startCenter, target }
    ;(e.target as Element).setPointerCapture(e.pointerId)
  }

  function applyDragFromPointer(clientX: number): void {
    if (!dragState) return
    const dx = clientX - dragState.startX
    const fraction = dx / canvasWidth
    if (dragState.target) {
      const cur = effectiveViewport(dragState.target)
      const next = panByFraction({ zoom: cur.zoom, center: dragState.startCenter }, fraction)
      const prev = viewportOverrides.get(dragState.target)
      viewportOverrides.set(dragState.target, {
        zoomFactor: prev ? prev.zoomFactor : 1,
        centerDelta: next.center - globalViewport.center,
      })
    } else {
      globalViewport = panByFraction(
        { zoom: globalViewport.zoom, center: dragState.startCenter },
        fraction,
      )
    }
  }

  function applyHighlightDragFromPointer(clientX: number, clientY: number): void {
    if (!highlightSelection || !trackCanvas) return
    const rect = trackCanvas.getBoundingClientRect()
    const x = clientX - rect.left
    // Y is irrelevant for the highlight region: we stay on the genome that
    // was anchored at pointerdown, but we need its viewport to translate X
    // back to bp on the clicked sequence.
    void clientY
    const g = highlightSelection.genome
    const vp = effectiveViewport(g.id)
    const bpGlobal = pxToBp(x, vp, g.total_length, canvasWidth)
    const seqObj = g.sequences.find((s) => s.name === highlightSelection!.seq)
    if (!seqObj) return
    let bpLocal = bpGlobal - seqObj.offset
    if (bpLocal < 0) bpLocal = 0
    if (bpLocal > seqObj.length) bpLocal = seqObj.length
    highlightSelection = {
      ...highlightSelection,
      endBp: Math.round(bpLocal),
    }
  }

  function onPointerMove(e: PointerEvent) {
    if (highlightSelection && highlightDragging) {
      pendingPointer = { clientX: e.clientX }
      if (pendingFrame !== null) return
      const clientY = e.clientY
      pendingFrame = requestAnimationFrame(() => {
        pendingFrame = null
        const pending = pendingPointer
        pendingPointer = null
        if (pending) applyHighlightDragFromPointer(pending.clientX, clientY)
      })
      return
    }
    if (!dragState) return
    pendingPointer = { clientX: e.clientX }
    if (pendingFrame !== null) return
    pendingFrame = requestAnimationFrame(() => {
      pendingFrame = null
      const pending = pendingPointer
      pendingPointer = null
      if (pending) applyDragFromPointer(pending.clientX)
    })
  }

  async function finalizeHighlight(): Promise<void> {
    if (!highlightSelection) return
    highlightDragging = false
    const sel = highlightSelection
    const lo = Math.min(sel.startBp, sel.endBp)
    const hi = Math.max(sel.startBp, sel.endBp)
    if (hi <= lo) {
      // degenerate selection — treat as a single bp region
      highlightSelection = { ...sel, startBp: lo, endBp: Math.max(lo + 1, hi) }
    }
    const loFinal = Math.min(highlightSelection.startBp, highlightSelection.endBp)
    const hiFinal = Math.max(highlightSelection.startBp, highlightSelection.endBp)
    try {
      const resp = await api.highlight(
        sel.genome.id,
        `${sel.seq}:${loFinal}-${Math.max(loFinal + 1, hiFinal)}`,
      )
      highlightResult = resp
    } catch (err) {
      error = err instanceof Error ? err.message : String(err)
    }
  }

  function onPointerUp(e: PointerEvent) {
    if (pendingFrame !== null) {
      cancelAnimationFrame(pendingFrame)
      pendingFrame = null
    }
    if (highlightSelection && highlightDragging) {
      if (pendingPointer) {
        applyHighlightDragFromPointer(pendingPointer.clientX, 0)
        pendingPointer = null
      }
      void finalizeHighlight()
      return
    }
    // Detect clean click (no drag movement, no modifiers) on the reference
    // genome to open the chromosome color picker.
    const ds = dragState
    if (ds && !pendingPointer) {
      const dx = Math.abs(e.clientX - ds.startX)
      const dy = Math.abs(e.clientY - ds.startY)
      if (dx < 4 && dy < 4 && !e.ctrlKey && !e.metaKey && !e.shiftKey) {
        const click = resolveTrackClick(e.clientX, e.clientY)
        if (click && referenceGenome && click.genome.id === referenceGenome.id) {
          openColorPicker(click.seq)
          dragState = null
          return
        }
      }
    }
    if (pendingPointer) {
      applyDragFromPointer(pendingPointer.clientX)
      pendingPointer = null
    }
    dragState = null
  }

  function clearHighlight(): void {
    highlightSelection = null
    highlightResult = null
    highlightDragging = false
  }

  async function downloadHighlightScmIds(): Promise<void> {
    if (!highlightResult || !allGenomes || downloadingScms) return
    const region = highlightResult.source
    // The on-screen highlight is capped for rendering, but a FISH probe set
    // must be complete — re-fetch the region uncapped (limit=0) so the export
    // contains every SCM and an accurate cross-genome presence matrix.
    downloadingScms = true
    let full: HighlightResponse
    try {
      full = await api.highlight(
        region.genome_id,
        `${region.seq}:${region.start}-${region.end}`,
        { limit: 0 },
      )
    } catch (err) {
      error = err instanceof Error ? err.message : String(err)
      return
    } finally {
      downloadingScms = false
    }

    const src = full.source
    const ids = src.scm_ids
    if (ids.length === 0) return

    // Build per-SCM presence map across every loaded genome. Source is
    // present by definition; targets are present iff scm_id appears in
    // their positions list.
    const presence = new Map<string, Set<string>>()
    for (const id of ids) presence.set(id, new Set([src.genome_id]))
    for (const target of full.targets) {
      for (const pos of target.positions) {
        presence.get(pos.scm_id)?.add(target.genome_id)
      }
    }

    // allGenomes (server order) keeps the column layout stable across
    // reorder/visibility changes.
    const genomeIds = allGenomes.map((g) => g.id)
    const tsv = buildPresenceTsv(ids, presence, genomeIds)
    const safeSeq = safeFilenamePart(src.seq)
    downloadTextFile(tsv, `syntrack_${src.genome_id}_${safeSeq}_${src.start}-${src.end}_scm_ids.tsv`)
  }

  /** Save a stored marker set's COMPLETE SCM IDs to file (same presence-matrix
   *  TSV as the highlight export). Pulls full membership from the backend. */
  async function downloadFishSetScms(label: string): Promise<void> {
    if (!allGenomes || fishFileSaving) return
    fishFileSaving = label
    try {
      const resp = await api.fishScms(label)
      if (resp.scm_ids.length === 0) return
      const genomeIds = allGenomes.map((g) => g.id)
      const presence = presenceFromBitstrings(resp.scm_ids, resp.presence)
      const tsv = buildPresenceTsv(resp.scm_ids, presence, genomeIds)
      downloadTextFile(tsv, `syntrack_fishset_${safeFilenamePart(label)}_scm_ids.tsv`)
    } catch (err) {
      error = err instanceof Error ? err.message : String(err)
    } finally {
      fishFileSaving = null
    }
  }

  // ----------------------------- FISH marker sets --------------------------

  function parseFishFile(text: string): string[] {
    const ids: string[] = []
    for (const raw of text.split(/\r?\n/)) {
      const line = raw.trim()
      if (!line || line.startsWith('#')) continue
      // Take first column (tab or comma separated).
      const col = line.split(/[\t,]/)[0].trim()
      // Skip likely header rows.
      if (/^scm.?id$/i.test(col) || /^marker/i.test(col) || /^name$/i.test(col)) continue
      if (col) ids.push(col)
    }
    return ids
  }

  let fishFileInput: HTMLInputElement | undefined = $state()

  async function onFishFileSelected(): Promise<void> {
    if (!fishFileInput?.files?.length) return
    const file = fishFileInput.files[0]
    const text = await file.text()
    const ids = parseFishFile(text)
    if (ids.length === 0) {
      error = `No SCM IDs found in ${file.name}`
      fishFileInput.value = ''
      return
    }
    const label = file.name.replace(/\.[^.]+$/, '')
    // If a set with the same name exists, replace it silently.
    if (fishSets.has(label)) {
      await deleteFishSet(label)
    }
    const color = nextFishColor()
    fishLoading = true
    try {
      const resp = await api.fishCreate(ids, label, color)
      fishSets.set(label, resp)
      fishVisible.add(label)
      if (resp.scm_count === 0) {
        error = `"${label}": no matching SCMs found in loaded genomes`
      }
    } catch (err) {
      error = err instanceof Error ? err.message : String(err)
    } finally {
      fishLoading = false
      fishFileInput.value = ''
    }
  }

  async function deleteFishSet(label: string): Promise<void> {
    try {
      await api.fishDelete(label)
    } catch {
      // Best-effort server cleanup — remove locally regardless.
    }
    fishSets.delete(label)
    fishVisible.delete(label)
  }

  function toggleFishSet(label: string): void {
    if (fishVisible.has(label)) {
      fishVisible.delete(label)
    } else {
      fishVisible.add(label)
    }
  }

  // ----------------------------- FISH density preview ----------------------

  /** Fetch density for the currently-visible sets at ~canvas-width resolution. */
  async function fetchFishDensity(): Promise<void> {
    const labels = [...fishVisible]
    if (labels.length === 0) {
      fishDensityResult = null
      return
    }
    const bins = Math.max(1, Math.min(20_000, Math.round(canvasWidth)))
    fishDensityLoading = true
    fishDensityError = null
    try {
      fishDensityResult = await api.fishDensity(bins, labels)
    } catch (err) {
      fishDensityError = err instanceof Error ? err.message : String(err)
      fishDensityResult = null
    } finally {
      fishDensityLoading = false
    }
  }

  function toggleFishPreview(): void {
    if (fishPreview) {
      // Exit: restore the saved view.
      fishPreview = false
      fishDensityResult = null
      fishDensityError = null
      if (savedPreviewView) {
        globalViewport = savedPreviewView.vp
        viewportOverrides.clear()
        for (const [k, v] of savedPreviewView.overrides) viewportOverrides.set(k, v)
        savedPreviewView = null
      }
      return
    }
    // Enter: snapshot the view, reset to whole-genome, freeze. The effect below
    // fetches the density (it fires when fishPreview flips on).
    savedPreviewView = { vp: globalViewport, overrides: new Map(viewportOverrides) }
    globalViewport = DEFAULT_VIEWPORT
    viewportOverrides.clear()
    fishPreview = true
  }

  // While in preview, (re)fetch when entering or when the visible set changes.
  $effect(() => {
    const labels = [...fishVisible] // read membership so this tracks changes
    if (!fishPreview) return
    void labels
    void fetchFishDensity()
  })

  /** Export the FISH density as a high-resolution PNG (re-fetched at export
   *  resolution so the image is crisp, independent of the on-screen width). */
  async function exportFishPng(): Promise<void> {
    if (!fishPreview || fishExporting || fishVisible.size === 0) return
    fishExporting = true
    fishDensityError = null
    try {
      const density = await api.fishDensity(exportBins(), [...fishVisible])
      const canvas = renderFishDensityImage(density, genomesInOrder, fishVisible)
      const stamp = new Date().toISOString().slice(0, 10)
      downloadCanvasPng(canvas, `syntrack_fish_${stamp}.png`)
    } catch (err) {
      fishDensityError = err instanceof Error ? err.message : String(err)
    } finally {
      fishExporting = false
    }
  }

  /** Turn the current highlight selection into a coloured FISH marker set (the
   *  complete, uncapped SCM set — same source as the export). */
  async function saveHighlightAsFishSet(): Promise<void> {
    if (!highlightResult || savingHighlightSet) return
    const src = highlightResult.source
    let label = `${src.seq}:${src.start}-${src.end}`
    for (let n = 2; fishSets.has(label); n++) label = `${src.seq}:${src.start}-${src.end} (${n})`
    savingHighlightSet = true
    error = null
    try {
      const full = await api.highlight(
        src.genome_id,
        `${src.seq}:${src.start}-${src.end}`,
        { limit: 0 },
      )
      const ids = full.source.scm_ids
      if (ids.length === 0) return
      const resp = await api.fishCreate(ids, label, nextFishColor())
      fishSets.set(label, resp)
      fishVisible.add(label)
    } catch (err) {
      error = err instanceof Error ? err.message : String(err)
    } finally {
      savingHighlightSet = false
    }
  }

  // ----------------------------- Chromosome color picker -------------------

  function openColorPicker(seqName: string): void {
    if (!colorPickerEl) return
    colorPickerSeq = seqName
    colorPickerEl.value = seqColors.get(seqName) ?? DEFAULT_SEQ_COLOR
    colorPickerEl.click()
  }

  function onColorPicked(e: Event): void {
    const hex = (e.target as HTMLInputElement).value
    if (colorPickerSeq) {
      seqColors.set(colorPickerSeq, hex)
    }
  }

  function resetSeqColors(): void {
    seqColors.clear()
  }

  function onKeyDown(e: KeyboardEvent): void {
    if (e.key === 'Escape' && (highlightSelection || highlightResult)) {
      clearHighlight()
    }
  }

  function resetView() {
    globalViewport = DEFAULT_VIEWPORT
    viewportOverrides.clear()
    clearHighlight()
  }

  let lastAlignmentSummary = $state<string | null>(null)
  let aligning = $state(false)

  async function onDoubleClick(e: MouseEvent) {
    if (!trackCanvas || aligning || fishPreview) return
    const rect = trackCanvas.getBoundingClientRect()
    const cx = e.clientX - rect.left
    const cy = e.clientY - rect.top
    const idx = genomeIndexAt(cy, genomesInOrder.length)
    if (idx === null) return
    e.preventDefault()

    const anchor = genomesInOrder[idx]
    const anchorVp = effectiveViewport(anchor.id)
    const bpGlobal = pxToBp(cx, anchorVp, anchor.total_length, canvasWidth)
    const clamped = Math.max(0, Math.min(anchor.total_length - 1, bpGlobal))
    let clickedSeq = anchor.sequences[anchor.sequences.length - 1]
    for (const s of anchor.sequences) {
      if (clamped >= s.offset && clamped < s.offset + s.length) {
        clickedSeq = s
        break
      }
    }
    const posLocal = Math.max(0, Math.round(clamped - clickedSeq.offset))

    // Only align against visible genomes (skip the anchor itself).
    const targets = genomesInOrder.filter((g) => g.id !== anchor.id).map((g) => g.id)

    aligning = true
    lastAlignmentSummary = 'aligning…'
    let resp
    try {
      resp = await api.align(anchor.id, clickedSeq.name, posLocal, { targets })
    } catch (err) {
      error = err instanceof Error ? err.message : String(err)
      aligning = false
      lastAlignmentSummary = null
      return
    }
    aligning = false

    let aligned = 0
    let missed = 0
    for (const m of resp.mappings) {
      const target = genomesInOrder.find((g) => g.id === m.genome_id)
      if (!target || m.seq === null || m.pos === null) {
        missed += 1
        continue
      }
      const targetSeq = target.sequences.find((s) => s.name === m.seq)
      if (!targetSeq) {
        missed += 1
        continue
      }
      const bpTarget = targetSeq.offset + m.pos
      const delta = alignmentDelta({
        anchorVp,
        anchorTotalLen: anchor.total_length,
        targetTotalLen: target.total_length,
        canvasWidth,
        bpTarget,
        xClick: cx,
        globalVp: globalViewport,
      })
      viewportOverrides.set(m.genome_id, delta)
      aligned += 1
    }

    const total = aligned + missed
    lastAlignmentSummary =
      `aligned to ${anchor.label} ${clickedSeq.name}:${posLocal.toLocaleString()}` +
      (missed > 0 ? ` (${aligned}/${total} genomes)` : '')
  }

  // ----------------------------- Track-handle reorder --------------------

  function onHandleDragStart(e: DragEvent, i: number) {
    reorderFromIdx = i
    if (e.dataTransfer) {
      e.dataTransfer.effectAllowed = 'move'
      e.dataTransfer.setData('text/plain', String(i))
    }
  }

  function onHandleDragOver(e: DragEvent, i: number) {
    if (reorderFromIdx === null) return
    e.preventDefault()
    if (e.dataTransfer) e.dataTransfer.dropEffect = 'move'
    reorderOverIdx = i
  }

  function onHandleDragLeave(i: number) {
    if (reorderOverIdx === i) reorderOverIdx = null
  }

  function onHandleDrop(e: DragEvent, toIdx: number) {
    e.preventDefault()
    const fromIdx = reorderFromIdx
    reorderFromIdx = null
    reorderOverIdx = null
    if (fromIdx === null || fromIdx === toIdx) return
    // Map visible-list indices to fullOrder positions and splice there so
    // hidden genomes keep their relative slots.
    const movedId = order[fromIdx]
    const targetId = order[toIdx]
    const next = fullOrder.filter((id) => id !== movedId)
    const targetPos = next.indexOf(targetId)
    // Insert before or after the target depending on drag direction.
    next.splice(fromIdx < toIdx ? targetPos + 1 : targetPos, 0, movedId)
    fullOrder = next
  }

  function onHandleDragEnd() {
    reorderFromIdx = null
    reorderOverIdx = null
  }

  // ----------------------------- Status helpers --------------------------

  let statusLine = $derived.by(() => {
    if (!allGenomes || genomesInOrder.length === 0) return 'no genomes selected'
    const anchor = genomesInOrder[0]
    const vp = effectiveViewport(anchor.id)
    const { startBp, endBp } = visibleRange(vp, anchor.total_length, canvasWidth)
    const ppb = pixelsPerBp(vp, anchor.total_length, canvasWidth)
    const bpPerPx = ppb > 0 ? 1 / ppb : 0
    const scope = viewportOverrides.size
      ? `${viewportOverrides.size} override${viewportOverrides.size === 1 ? '' : 's'}`
      : 'global'
    const base =
      `${anchor.label}: ${fmtBp(startBp)} – ${fmtBp(endBp)}  ` +
      `(${(bpPerPx / 1000).toFixed(1)} kb/px, zoom ${vp.zoom.toFixed(1)}×, LOD: ${lodModeValue}, ${scope})`
    let line = base
    if (lastAlignmentSummary) line += `  ·  ${lastAlignmentSummary}`
    if (highlightResult) {
      const src = highlightResult.source
      const totalMatches = highlightResult.targets.reduce((s, t) => s + t.scm_count, 0)
      const anyTruncated = highlightResult.targets.some((t) => t.truncated)
      const truncNote = anyTruncated ? ' [ticks capped]' : ''
      line += `  ·  highlight ${src.seq}:${src.start.toLocaleString()}-${src.end.toLocaleString()} — ${src.scm_count} source SCMs, ${totalMatches} cross-genome${truncNote} (Esc to clear)`
    }
    return line
  })

  let canvasContentHeight = $derived(
    genomesInOrder.length
      ? totalTrackedHeight(genomesInOrder.length, DEFAULT_LAYOUT)
      : 0,
  )
  // Canvas layers must be sized to the full content height so that all
  // genomes render correctly even when the track stack is taller than the
  // scroll container.
  let effectiveCanvasHeight = $derived(Math.max(canvasHeight, canvasContentHeight))

  const HANDLE_HEIGHT = 18 // DOM overlay strip sitting above each bar
</script>

<svelte:window onkeydown={onKeyDown} />

<header>
  <h1>SynTrack</h1>
  {#if allGenomes}
    <span class="meta">
      {genomesInOrder.length}/{allGenomes.length} genomes · {universeSize.toLocaleString()} SCMs
    </span>
    <label class="ref-ctl" title="Choose which genome's chromosome palette colors all tracks and connections.">
      Color by:
      <select
        value={selectedReferenceId ?? ''}
        onchange={(e) => {
          const v = (e.target as HTMLSelectElement).value
          selectedReferenceId = v === '' ? null : v
        }}
      >
        <option value="">(top genome)</option>
        {#each allGenomes as g (g.id)}
          <option value={g.id}>{g.label}</option>
        {/each}
      </select>
    </label>
    <button
      onclick={resetSeqColors}
      disabled={seqColors.size === 0}
      title="Reset all chromosome colors to grey"
    >
      Reset colors
    </button>
  {/if}
  <input
    bind:this={colorPickerEl}
    type="color"
    style="position:absolute;opacity:0;pointer-events:none"
    oninput={onColorPicked}
  />
  <span
    class="hint"
    title="Drag the label above any track to reorder. Shift + wheel/drag over a bar: scope that genome. Double-click a bar: vertical alignment. Ctrl / Cmd + click-drag on a bar: highlight a region (Esc to clear). Click a chromosome on the reference genome to pick its color."
  >
    label = reorder · Shift = scope · dbl-click = align · Ctrl-drag = highlight · click ref = color
  </span>
  <label class="fade-ctl" title="Dim the reference-palette coloring so the highlight overlay stands out. 0 = normal, slide right to fade.">
    Fade
    <input type="range" min="0" max="0.9" step="0.05" bind:value={fadeLevel} />
  </label>
  <button
    onclick={downloadHighlightScmIds}
    disabled={!highlightResult || highlightResult.source.scm_count === 0 || downloadingScms}
    title="Download a TSV of ALL highlighted SCMs (complete set, not the on-screen cap): scm_id, present_in (genome count), and one 0/1 presence column per loaded genome."
  >
    {downloadingScms ? 'Fetching…' : '↓ SCM IDs'}
  </button>
  <button
    onclick={saveHighlightAsFishSet}
    disabled={!highlightResult || highlightResult.source.scm_count === 0 || savingHighlightSet}
    title="Save the highlighted region as a coloured FISH marker set (complete SCM set). View it in the FISH preview."
  >
    {savingHighlightSet ? 'Saving…' : '★ Save as set'}
  </button>
  <button onclick={resetView} disabled={!allGenomes}>Reset view</button>
</header>

<main>
  {#if error}
    <div class="error-banner" role="alert">
      <span>{error}</span>
      <button onclick={() => (error = null)} title="Dismiss">×</button>
    </div>
  {/if}
  {#if allGenomes === null}
    <p class="loading">Loading genomes…</p>
  {:else}
    <aside class="sidebar" aria-label="Genome visibility">
      <div class="sidebar-head">
        <span class="sidebar-title">Genomes</span>
        <div class="sidebar-actions">
          <button onclick={selectAll} disabled={visibleIds.size === allGenomes.length}>All</button>
          <button onclick={selectNone} disabled={visibleIds.size === 0}>None</button>
        </div>
      </div>
      {#each sidebarGenomes as g (g.id)}
        {@const hlCount = highlightedByGenome.get(g.id) ?? 0}
        <label class="genome-toggle" class:hidden={!isVisible(g.id)}>
          <input
            type="checkbox"
            checked={isVisible(g.id)}
            onchange={() => toggleVisible(g.id)}
          />
          <span class="toggle-label">{g.label}</span>
          <span class="toggle-meta">{g.scm_count.toLocaleString()}</span>
          {#if highlightResult}
            <span
              class="toggle-highlight"
              class:zero={hlCount === 0}
              title="{hlCount.toLocaleString()} SCM{hlCount === 1 ? '' : 's'} in the current highlight"
            >
              {hlCount.toLocaleString()}
            </span>
          {/if}
        </label>
      {/each}

      <div class="sidebar-head fish-head">
        <span class="sidebar-title">Marker Sets</span>
        <div class="sidebar-actions">
          <button
            class:active={fishPreview}
            onclick={toggleFishPreview}
            disabled={fishSets.size === 0}
            title="FISH preview: a frozen, whole-genome multi-colour density render of the visible marker sets (every SCM counted). Pan/zoom is disabled while on."
          >
            {fishPreview ? 'Exit preview' : 'FISH preview'}
          </button>
          {#if fishPreview}
            <button
              onclick={exportFishPng}
              disabled={fishExporting || fishDensityLoading || fishVisible.size === 0}
              title="Export the FISH density as a high-resolution PNG."
            >
              {fishExporting ? 'Exporting…' : 'Export PNG'}
            </button>
          {:else}
            <button onclick={() => fishFileInput?.click()} disabled={fishLoading}>
              {fishLoading ? 'Loading…' : 'Load'}
            </button>
          {/if}
        </div>
        <input
          bind:this={fishFileInput}
          type="file"
          accept=".txt,.tsv,.csv"
          style="display:none"
          onchange={onFishFileSelected}
        />
      </div>
      {#if fishPreview}
        <p class="fish-preview-note">
          {#if fishDensityLoading}Rendering density…
          {:else if fishDensityError}Error: {fishDensityError}
          {:else if fishVisible.size === 0}Enable a marker set to see its signal.
          {:else}Frozen whole-genome FISH density · pan/zoom disabled{/if}
        </p>
      {/if}
      {#each [...fishSets] as [label, fs] (label)}
        <label class="fish-toggle">
          <input
            type="checkbox"
            checked={fishVisible.has(label)}
            onchange={() => toggleFishSet(label)}
          />
          <span class="fish-swatch" style:background={fs.color}></span>
          <span class="toggle-label">{label}</span>
          <span class="toggle-meta">{fs.scm_count.toLocaleString()}</span>
          <button
            class="fish-save"
            title="Save this set's SCM IDs to file (complete set)"
            disabled={fishFileSaving !== null}
            onclick={(e: MouseEvent) => { e.preventDefault(); e.stopPropagation(); downloadFishSetScms(label) }}
          >{fishFileSaving === label ? '…' : '↓'}</button>
          <button
            class="fish-delete"
            title="Remove marker set"
            onclick={(e: MouseEvent) => { e.stopPropagation(); deleteFishSet(label) }}
          >×</button>
        </label>
      {/each}
    </aside>

    <div
      bind:this={containerEl}
      class="canvas-container"
      role="application"
      aria-label="Synteny canvas"
      style:cursor={aligning ? 'wait' : dragState ? 'grabbing' : 'grab'}
      onwheel={onWheel}
      onpointerdown={onPointerDown}
      onpointermove={onPointerMove}
      onpointerup={onPointerUp}
      onpointercancel={onPointerUp}
      ondblclick={onDoubleClick}
    >
      <div
        class="canvas-stack"
        style:height={`${Math.max(canvasHeight, canvasContentHeight)}px`}
      >
        <canvas bind:this={ribbonCanvas} class="layer ribbons" class:layer-hidden={fishPreview}></canvas>
        <canvas bind:this={trackCanvas} class="layer tracks"></canvas>
        <canvas bind:this={overlayCanvas} class="layer overlay" class:layer-hidden={fishPreview}></canvas>

        <!-- Track-handle overlay: one drag-handle strip per visible genome,
             sitting directly above its bar. Pointer-events isolated to the
             handle itself so panning/dblclick on the bar below are unaffected. -->
        <div class="handles-layer">
          {#each genomesInOrder as g, i (g.id)}
            <div
              class="track-handle"
              class:dragging={reorderFromIdx === i}
              class:drop-target={reorderOverIdx === i && reorderFromIdx !== i}
              style:top={`${trackY(i, DEFAULT_LAYOUT) - HANDLE_HEIGHT}px`}
              style:height={`${HANDLE_HEIGHT}px`}
              draggable="true"
              role="button"
              tabindex="0"
              aria-label={`reorder ${g.label}`}
              ondragstart={(e) => onHandleDragStart(e, i)}
              ondragover={(e) => onHandleDragOver(e, i)}
              ondragleave={() => onHandleDragLeave(i)}
              ondrop={(e) => onHandleDrop(e, i)}
              ondragend={onHandleDragEnd}
            >
              <span class="grip" aria-hidden="true">≡</span>
              <span class="handle-label">{g.label}</span>
            </div>
          {/each}
        </div>
      </div>
      {#if loadingData}
        <div class="badge">loading…</div>
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

  .hint {
    color: #666;
    font-size: 0.8em;
    margin-left: auto;
    cursor: help;
  }

  .ref-ctl {
    display: flex;
    align-items: center;
    gap: 0.4em;
    color: #aaa;
    font-size: 0.85em;
    user-select: none;
  }

  .ref-ctl select {
    background: #333;
    color: #ddd;
    border: 1px solid #555;
    border-radius: 3px;
    padding: 0.15em 0.3em;
    font-size: 0.95em;
  }

  .fade-ctl {
    display: flex;
    align-items: center;
    gap: 0.4em;
    color: #aaa;
    font-size: 0.85em;
    user-select: none;
  }

  .fade-ctl input[type='range'] {
    width: 100px;
    accent-color: #4ab2e0;
  }

  main {
    flex: 1;
    overflow: hidden;
    display: flex;
    min-height: 0;
  }

  .sidebar {
    flex: 0 0 240px;
    border-right: 1px solid #333;
    background: #1f1f1f;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
  }

  .sidebar-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.5em 0.8em;
    border-bottom: 1px solid #2a2a2a;
    position: sticky;
    top: 0;
    background: #1f1f1f;
    z-index: 1;
  }

  .sidebar-title {
    color: #ccc;
    font-weight: 500;
    font-size: 0.9em;
  }

  .sidebar-actions {
    display: flex;
    gap: 0.3em;
  }

  .sidebar-actions button {
    font-size: 0.75em;
    padding: 0.2em 0.6em;
  }

  .genome-toggle {
    display: flex;
    align-items: center;
    gap: 0.5em;
    padding: 0.4em 0.8em;
    border-bottom: 1px solid #2a2a2a;
    cursor: pointer;
    user-select: none;
  }

  .genome-toggle:hover {
    background: #2a2a2a;
  }

  .genome-toggle.hidden .toggle-label,
  .genome-toggle.hidden .toggle-meta {
    color: #555;
    text-decoration: line-through;
  }

  .genome-toggle input[type='checkbox'] {
    margin: 0;
    accent-color: #4ab2e0;
  }

  .toggle-label {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .toggle-meta {
    color: #888;
    font-size: 0.8em;
    font-variant-numeric: tabular-nums;
  }

  .toggle-highlight {
    background: rgba(255, 220, 50, 0.18);
    border: 1px solid rgba(255, 220, 50, 0.55);
    color: #ffdc32;
    font-size: 0.75em;
    font-variant-numeric: tabular-nums;
    padding: 0.05em 0.45em;
    border-radius: 10px;
    min-width: 1.5em;
    text-align: center;
  }

  .toggle-highlight.zero {
    background: transparent;
    border-color: #444;
    color: #555;
  }

  .fish-head {
    margin-top: 0.2em;
    border-top: 1px solid #333;
  }

  .sidebar-actions button.active {
    background: #ffdc32;
    color: #1a1a1a;
    border-color: #ffdc32;
  }

  .fish-preview-note {
    margin: 0;
    padding: 0.35em 0.8em;
    font-size: 0.75em;
    color: #bbb;
    background: #1d1d1d;
    border-bottom: 1px solid #2a2a2a;
  }

  .fish-toggle {
    display: flex;
    align-items: center;
    gap: 0.5em;
    padding: 0.4em 0.8em;
    border-bottom: 1px solid #2a2a2a;
    cursor: pointer;
    user-select: none;
  }

  .fish-toggle:hover {
    background: #2a2a2a;
  }

  .fish-toggle input[type='checkbox'] {
    margin: 0;
    accent-color: #4ab2e0;
  }

  .fish-swatch {
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 2px;
    flex-shrink: 0;
  }

  .fish-save {
    margin-left: auto;
    background: none;
    border: none;
    color: #777;
    font-size: 0.95em;
    cursor: pointer;
    padding: 0 0.3em;
    line-height: 1;
  }

  .fish-save:hover:not(:disabled) {
    color: #6cf;
  }

  .fish-save:disabled {
    cursor: default;
    opacity: 0.5;
  }

  .fish-delete {
    background: none;
    border: none;
    color: #777;
    font-size: 1em;
    cursor: pointer;
    padding: 0 0.3em;
    line-height: 1;
  }

  .fish-delete:hover {
    color: #e44;
  }

  .loading {
    margin: 1em;
  }

  .error-banner {
    display: flex;
    align-items: center;
    gap: 0.6em;
    padding: 0.5em 1em;
    background: #3a1c1c;
    border-bottom: 1px solid #6b2a2a;
    color: #f8a0a0;
    font-size: 0.9em;
  }

  .error-banner span {
    flex: 1;
  }

  .error-banner button {
    background: none;
    border: none;
    color: #f8a0a0;
    font-size: 1.1em;
    cursor: pointer;
    padding: 0 0.3em;
    line-height: 1;
  }

  .error-banner button:hover {
    color: #fff;
  }

  .canvas-container {
    width: 100%;
    height: 100%;
    overflow-y: auto;
    overflow-x: hidden;
    user-select: none;
    touch-action: none;
    position: relative;
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

  .layer-hidden {
    display: none;
  }

  .ribbons {
    z-index: 1;
  }

  .tracks {
    z-index: 2;
    pointer-events: none;
  }

  .overlay {
    z-index: 3;
    pointer-events: none;
  }

  .handles-layer {
    position: absolute;
    inset: 0;
    pointer-events: none;
    z-index: 4;
  }

  .track-handle {
    position: absolute;
    left: 8px;
    min-width: 160px;
    max-width: 320px;
    padding: 1px 8px;
    display: flex;
    align-items: center;
    gap: 0.4em;
    background: rgba(32, 32, 32, 0.82);
    border: 1px solid #3a3a3a;
    border-radius: 3px;
    color: #ddd;
    font-size: 11px;
    cursor: grab;
    pointer-events: auto;
    user-select: none;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .track-handle:hover {
    background: rgba(45, 45, 45, 0.95);
    border-color: #555;
  }

  .track-handle.dragging {
    opacity: 0.5;
    cursor: grabbing;
  }

  .track-handle.drop-target {
    background: rgba(31, 58, 74, 0.95);
    border-color: #4ab2e0;
    box-shadow: 0 0 0 2px rgba(74, 178, 224, 0.4);
  }

  .grip {
    color: #888;
    font-size: 12px;
  }

  .handle-label {
    overflow: hidden;
    text-overflow: ellipsis;
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
