// Track-canvas renderer: one horizontal bar per genome. When reference-paint
// data is provided, bars are filled by painted regions (reference-color per
// run of SCMs, design §5.7). Without paint data, bars fall back to the
// genome's own per-sequence palette.
//
// Performance: all rectangle fills are batched into one Path2D per color,
// then flushed with a single fill() per color. Paint regions narrower than
// one pixel are dropped (pixel-aware LOD) — they'd be indistinguishable
// anyway.

import type { Genome, PaintRegion } from '../api/types'
import { UNKNOWN_COLOR, colorFor } from './colors'
import { bpToPx, pixelsPerBp, visibleRange, type Viewport } from './coords'

export type TrackLayout = {
  trackHeight: number
  trackGap: number
  topPad: number
  labelHeight: number
}

export const DEFAULT_LAYOUT: TrackLayout = {
  trackHeight: 22,
  trackGap: 80,
  topPad: 28,
  labelHeight: 14,
}

/** Y-coordinate (top edge) of the genome bar at `index` in the visual order. */
export function trackY(index: number, layout: TrackLayout): number {
  return layout.topPad + index * (layout.trackHeight + layout.trackGap)
}

export function totalTrackedHeight(nGenomes: number, layout: TrackLayout): number {
  if (nGenomes === 0) return 0
  return trackY(nGenomes - 1, layout) + layout.trackHeight + layout.topPad
}

export type GenomePaintMap = Map<string, PaintRegion[]>
export type ViewportFn = (genomeId: string) => Viewport

// Visible extent of one sequence within one track — carried through from the
// fill pass to the separator + label passes so we don't recompute.
type SeqExtent = {
  name: string
  x0: number
  x1: number
  y: number
}

const SEP_TICK = 4
const SEP_DARK = 'rgba(0, 0, 0, 0.85)'
const SEP_LIGHT = 'rgba(255, 255, 255, 0.75)'
const LABEL_FILL = 'rgba(255, 255, 255, 0.95)'
const LABEL_STROKE = 'rgba(0, 0, 0, 0.6)'

export function drawTracks(
  ctx: CanvasRenderingContext2D,
  genomesInOrder: Genome[],
  viewportFn: ViewportFn,
  canvasWidth: number,
  canvasHeight: number,
  paintByGenome: GenomePaintMap,
  referenceColorMap: Map<string, string>,
  layout: TrackLayout = DEFAULT_LAYOUT,
): void {
  ctx.clearRect(0, 0, canvasWidth, canvasHeight)
  ctx.font = '11px system-ui, sans-serif'
  ctx.textBaseline = 'alphabetic'

  // Accumulate all rectangles to fill, keyed by color. Across every genome
  // and every paint region, we'll end up issuing exactly one fill() per
  // distinct color.
  const colorPaths = new Map<string, Path2D>()
  const addRect = (color: string, x: number, y: number, w: number, h: number): void => {
    let path = colorPaths.get(color)
    if (!path) {
      path = new Path2D()
      colorPaths.set(color, path)
    }
    path.rect(x, y, w, h)
  }

  const seqExtentsByTrack: SeqExtent[][] = []

  for (let i = 0; i < genomesInOrder.length; i++) {
    const g = genomesInOrder[i]
    const vp = viewportFn(g.id)
    const y = trackY(i, layout)
    const { startBp, endBp } = visibleRange(vp, g.total_length, canvasWidth)

    // Genome label (drawn immediately — small, not worth batching).
    ctx.fillStyle = '#ddd'
    ctx.fillText(g.label, 8, y - 6)

    const painting = paintByGenome.get(g.id)
    const extents: SeqExtent[] = []

    // Base pass: for each visible sequence, fill its full on-screen extent.
    for (const seq of g.sequences) {
      const seqStart = seq.offset
      const seqEnd = seq.offset + seq.length
      if (seqEnd <= startBp || seqStart >= endBp) continue
      const x0 = Math.max(0, bpToPx(seqStart, vp, g.total_length, canvasWidth))
      const x1 = Math.min(canvasWidth, bpToPx(seqEnd, vp, g.total_length, canvasWidth))
      const w = Math.max(1, x1 - x0)
      const baseColor = painting ? UNKNOWN_COLOR : seq.color
      addRect(baseColor, x0, y, w, layout.trackHeight)
      extents.push({ name: seq.name, x0, x1, y })
    }

    // Overlay pass: painted regions, with sub-pixel LOD.
    if (painting) {
      const seqOffsets = new Map(g.sequences.map((s) => [s.name, s.offset]))
      for (const r of painting) {
        const off = seqOffsets.get(r.seq)
        if (off === undefined) continue
        const rStart = off + r.start
        const rEnd = off + r.end
        if (rEnd <= startBp || rStart >= endBp) continue
        const x0 = Math.max(0, bpToPx(rStart, vp, g.total_length, canvasWidth))
        const x1 = Math.min(canvasWidth, bpToPx(rEnd, vp, g.total_length, canvasWidth))
        const w = x1 - x0
        if (w < 1) continue // sub-pixel: would alias into a single column anyway
        addRect(colorFor(r.reference_seq, referenceColorMap), x0, y, w, layout.trackHeight)
      }
    }

    seqExtentsByTrack.push(extents)
  }

  // 1) One fill call per color across every track + region. This is where
  //    batching pays off: with ~12 palette colors + UNKNOWN_COLOR we issue
  //    ~13 Canvas ops regardless of region count.
  for (const [color, path] of colorPaths) {
    ctx.fillStyle = color
    ctx.fill(path)
  }

  // 2) Color-independent chromosome separators. 1 px dark + 1 px light
  //    side-by-side so the boundary reads on any background. Small ticks
  //    above and below extend beyond the bar to signal the split even when
  //    neighbouring regions share a colour.
  for (const extents of seqExtentsByTrack) {
    for (const { x0, x1, y } of extents) {
      drawSeparator(ctx, x0, y, layout.trackHeight)
      drawSeparator(ctx, x1, y, layout.trackHeight)
    }
  }

  // 3) Sequence-name labels (drawn last so they overlay fills + separators).
  ctx.font = '11px system-ui, sans-serif'
  ctx.fillStyle = LABEL_FILL
  ctx.strokeStyle = LABEL_STROKE
  ctx.lineWidth = 3
  ctx.textAlign = 'center'
  for (const extents of seqExtentsByTrack) {
    for (const { name, x0, x1, y } of extents) {
      const w = x1 - x0
      if (w <= 30) continue
      const cx = x0 + w / 2
      const cy = y + layout.trackHeight / 2 + 4
      ctx.strokeText(name, cx, cy)
      ctx.fillText(name, cx, cy)
    }
  }
  ctx.textAlign = 'start'
  ctx.lineWidth = 1
}

function drawSeparator(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  trackHeight: number,
): void {
  const top = y - SEP_TICK
  const bottom = y + trackHeight + SEP_TICK
  // Dark line at (x + 0.5) and light line at (x - 0.5) — 2 px wide combined.
  ctx.lineWidth = 1
  ctx.strokeStyle = SEP_DARK
  ctx.beginPath()
  ctx.moveTo(x + 0.5, top)
  ctx.lineTo(x + 0.5, bottom)
  ctx.stroke()
  ctx.strokeStyle = SEP_LIGHT
  ctx.beginPath()
  ctx.moveTo(x - 0.5, top)
  ctx.lineTo(x - 0.5, bottom)
  ctx.stroke()
}

// Re-export for callers (pixelsPerBp is used in LOD computation in App).
export { pixelsPerBp }
