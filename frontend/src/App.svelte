<script lang="ts">
  import { onMount } from 'svelte'
  import { SvelteMap, SvelteSet } from 'svelte/reactivity'

  import { api } from './api/client'
  import type {
    BlocksResponse,
    ConfigResponse,
    Genome,
    HighlightResponse,
    PaintRegion,
    SCMsResponse,
  } from './api/types'
  import { alignmentDelta } from './canvas/alignment'
  import { referenceColorMap } from './canvas/colors'
  import {
    DEFAULT_VIEWPORT,
    panByFraction,
    pixelsPerBp,
    pxToBp,
    visibleRange,
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
  import { drawRibbons, type AdjacentPair } from './canvas/draw_ribbons'
  import { drawScmLines, type AdjacentPairScms } from './canvas/draw_scms'
  import { fmtBp } from './canvas/format'
  import { genomeIndexAt } from './canvas/hit_test'
  import { lodMode } from './canvas/lod'

  // ----------------------------- State -----------------------------------

  // `allGenomes` is the stable server-load order — used for the visibility
  // sidebar. `order` is the *display* order of genomes that are currently
  // checked on. Unchecking removes a genome from `order`; checking appends it
  // at the end.
  let allGenomes = $state<Genome[] | null>(null)
  let universeSize = $state(0)
  let order = $state<string[]>([])

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
  let canvasWidth = $state(800)
  let canvasHeight = $state(600)

  const pairBlocks = new SvelteMap<string, BlocksResponse>()
  const loadingBlocks = new SvelteSet<string>()
  const pairScms = new SvelteMap<string, SCMsResponse>()
  const loadingScms = new SvelteSet<string>()
  const paintByPair = new SvelteMap<string, PaintRegion[]>()
  const loadingPaint = new SvelteSet<string>()
  function pairKey(g1: string, g2: string, ref: string): string {
    return `${g1}|${g2}|${ref}`
  }
  function paintKey(genomeId: string, ref: string): string {
    return `${genomeId}|${ref}`
  }

  // ----------------------------- Drag state ------------------------------

  let dragState = $state<{
    startX: number
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
      order = genomeResp.genomes.map((g) => g.id) // all visible initially
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

  let referenceGenome = $derived<Genome | null>(genomesInOrder[0] ?? null)
  let refColorMap = $derived<Map<string, string>>(
    referenceGenome ? referenceColorMap(referenceGenome) : new Map(),
  )

  let lodModeValue = $derived.by<'block' | 'scm'>(() => {
    if (genomesInOrder.length === 0 || canvasWidth < 2) return 'block'
    const top = genomesInOrder[0]
    const ppb = pixelsPerBp(effectiveViewport(top.id), top.total_length, canvasWidth)
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

  $effect(() => {
    if (!trackCanvas || !allGenomes || canvasWidth < 2 || canvasHeight < 2) return
    void viewportOverrides.size
    void globalViewport
    const ctx = sizeAndContext(trackCanvas, canvasWidth, canvasHeight)
    if (!ctx) return
    drawTracks(
      ctx,
      genomesInOrder,
      viewportFn,
      canvasWidth,
      canvasHeight,
      paintByGenome,
      refColorMap,
      fadeMultiplier,
    )
  })

  $effect(() => {
    if (!ribbonCanvas || canvasWidth < 2 || canvasHeight < 2) return
    void viewportOverrides.size
    void globalViewport
    const ctx = sizeAndContext(ribbonCanvas, canvasWidth, canvasHeight)
    if (!ctx) return
    if (lodModeValue === 'scm') {
      drawScmLines(
        ctx,
        adjacentPairsScms,
        viewportFn,
        canvasWidth,
        canvasHeight,
        refColorMap,
        fadeMultiplier,
      )
    } else {
      drawRibbons(
        ctx,
        adjacentPairs,
        viewportFn,
        canvasWidth,
        canvasHeight,
        refColorMap,
        fadeMultiplier,
      )
    }
  })

  $effect(() => {
    if (!overlayCanvas || canvasWidth < 2 || canvasHeight < 2) return
    void viewportOverrides.size
    void globalViewport
    const ctx = sizeAndContext(overlayCanvas, canvasWidth, canvasHeight)
    if (!ctx) return
    const overlay: HighlightOverlay = {
      source: highlightSelection,
      isSelecting: highlightDragging,
      result: highlightResult,
    }
    drawHighlight(ctx, overlay, genomesInOrder, viewportFn, canvasWidth, canvasHeight)
  })

  // ----------------------------- Visibility (sidebar) --------------------

  function isVisible(id: string): boolean {
    return order.includes(id)
  }

  function toggleVisible(id: string) {
    if (order.includes(id)) {
      order = order.filter((x) => x !== id)
    } else {
      order = [...order, id]
    }
  }

  function selectAll() {
    if (!allGenomes) return
    order = allGenomes.map((g) => g.id)
  }

  function selectNone() {
    order = []
  }

  // ----------------------------- Interaction -----------------------------

  function pointerGenomeId(clientY: number): string | null {
    if (!trackCanvas) return null
    const rect = trackCanvas.getBoundingClientRect()
    const y = clientY - rect.top
    const idx = genomeIndexAt(y, genomesInOrder.length)
    return idx === null ? null : genomesInOrder[idx].id
  }

  function onWheel(e: WheelEvent) {
    if (!trackCanvas) return
    e.preventDefault()
    const rect = trackCanvas.getBoundingClientRect()
    const cursorFraction = (e.clientX - rect.left) / rect.width
    const factor = e.deltaY < 0 ? 1.25 : 1 / 1.25
    const scoped = e.shiftKey ? pointerGenomeId(e.clientY) : null
    if (scoped) {
      const current = effectiveViewport(scoped)
      const next = zoomAtFraction(current, cursorFraction, factor)
      viewportOverrides.set(scoped, {
        zoomFactor: next.zoom / globalViewport.zoom,
        centerDelta: next.center - globalViewport.center,
      })
    } else {
      globalViewport = zoomAtFraction(globalViewport, cursorFraction, factor)
    }
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
    if (e.button !== 0) return
    // Ctrl / Meta + click-drag → start a highlight region selection.
    if (e.ctrlKey || e.metaKey) {
      const click = resolveTrackClick(e.clientX, e.clientY)
      if (!click) return
      e.preventDefault()
      ;(e.target as Element).setPointerCapture(e.pointerId)
      highlightSelection = {
        genomeIdx: click.genomeIdx,
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
    dragState = { startX: e.clientX, startCenter, target }
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

  function onPointerUp(_e: PointerEvent) {
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

  function downloadHighlightScmIds(): void {
    if (!highlightResult || !allGenomes) return
    const src = highlightResult.source
    const ids = src.scm_ids
    if (ids.length === 0) return

    // Build per-SCM presence map across every loaded genome. Source is
    // present by definition; targets are present iff scm_id appears in
    // their positions list.
    const presence = new Map<string, Set<string>>()
    for (const id of ids) presence.set(id, new Set([src.genome_id]))
    for (const target of highlightResult.targets) {
      for (const pos of target.positions) {
        presence.get(pos.scm_id)?.add(target.genome_id)
      }
    }

    // Columns: scm_id, present_in, <one per loaded genome in server order>.
    // Using allGenomes (server order) keeps the column layout stable across
    // reorder/visibility changes.
    const genomeIds = allGenomes.map((g) => g.id)
    const header = ['scm_id', 'present_in', ...genomeIds].join('\t')
    const lines = [header]
    for (const scmId of ids) {
      const set = presence.get(scmId) ?? new Set<string>()
      const cells: string[] = [
        scmId,
        String(set.size),
        ...genomeIds.map((gid) => (set.has(gid) ? '1' : '0')),
      ]
      lines.push(cells.join('\t'))
    }
    const text = lines.join('\n') + '\n'
    const blob = new Blob([text], { type: 'text/tab-separated-values;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    const safeSeq = src.seq.replace(/[^A-Za-z0-9._-]/g, '_')
    a.download = `syntrack_${src.genome_id}_${safeSeq}_${src.start}-${src.end}_scm_ids.tsv`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
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

  async function onDoubleClick(e: MouseEvent) {
    if (!trackCanvas) return
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

    let resp
    try {
      resp = await api.align(anchor.id, clickedSeq.name, posLocal)
    } catch (err) {
      error = err instanceof Error ? err.message : String(err)
      return
    }

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
    const next = [...order]
    const [moved] = next.splice(fromIdx, 1)
    next.splice(toIdx, 0, moved)
    order = next
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
      line += `  ·  highlight ${src.seq}:${src.start.toLocaleString()}-${src.end.toLocaleString()} — ${src.scm_count} source SCMs, ${totalMatches} cross-genome (Esc to clear)`
    }
    return line
  })

  let canvasContentHeight = $derived(
    genomesInOrder.length
      ? totalTrackedHeight(genomesInOrder.length, DEFAULT_LAYOUT)
      : 0,
  )

  const HANDLE_HEIGHT = 18 // DOM overlay strip sitting above each bar
</script>

<svelte:window onkeydown={onKeyDown} />

<header>
  <h1>SynTrack</h1>
  {#if allGenomes}
    <span class="meta">
      {genomesInOrder.length}/{allGenomes.length} genomes · {universeSize.toLocaleString()} SCMs
    </span>
  {/if}
  <span
    class="hint"
    title="Drag the label above any track to reorder. Shift + wheel/drag over a bar: scope that genome. Double-click a bar: vertical alignment. Ctrl / Cmd + click-drag on a bar: highlight a region (Esc to clear)."
  >
    label = reorder · Shift = scope · dbl-click = align · Ctrl-drag = highlight
  </span>
  <label class="fade-ctl" title="Dim the reference-palette coloring so the highlight overlay stands out. 0 = normal, slide right to fade.">
    Fade
    <input type="range" min="0" max="0.9" step="0.05" bind:value={fadeLevel} />
  </label>
  <button
    onclick={downloadHighlightScmIds}
    disabled={!highlightResult || highlightResult.source.scm_count === 0}
    title="Download a TSV of the highlighted SCMs: scm_id, present_in (genome count), and one 0/1 presence column per loaded genome."
  >
    ↓ SCM IDs
  </button>
  <button onclick={resetView} disabled={!allGenomes}>Reset view</button>
</header>

<main>
  {#if error}
    <div class="error">{error}</div>
  {:else if allGenomes === null}
    <p class="loading">Loading genomes…</p>
  {:else}
    <aside class="sidebar" aria-label="Genome visibility">
      <div class="sidebar-head">
        <span class="sidebar-title">Genomes</span>
        <div class="sidebar-actions">
          <button onclick={selectAll} disabled={order.length === allGenomes.length}>All</button>
          <button onclick={selectNone} disabled={order.length === 0}>None</button>
        </div>
      </div>
      {#each allGenomes as g (g.id)}
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
      ondblclick={onDoubleClick}
    >
      <div
        class="canvas-stack"
        style:height={`${Math.max(canvasHeight, canvasContentHeight)}px`}
      >
        <canvas bind:this={ribbonCanvas} class="layer ribbons"></canvas>
        <canvas bind:this={trackCanvas} class="layer tracks"></canvas>
        <canvas bind:this={overlayCanvas} class="layer overlay"></canvas>

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

  .hint {
    color: #666;
    font-size: 0.8em;
    margin-left: auto;
    cursor: help;
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
