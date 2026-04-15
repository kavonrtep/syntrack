// Track-canvas renderer: one horizontal bar per genome. When reference-paint
// data is provided, bars are filled by painted regions (reference-color per
// run of SCMs, design §5.7). Without paint data, bars fall back to the
// genome's own per-sequence palette — useful while paint data is loading.

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
  trackGap: 80, // vertical room between tracks (where ribbons land)
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

  for (let i = 0; i < genomesInOrder.length; i++) {
    const g = genomesInOrder[i]
    const vp = viewportFn(g.id)
    const y = trackY(i, layout)
    const ppb = pixelsPerBp(vp, g.total_length, canvasWidth)
    const { startBp, endBp } = visibleRange(vp, g.total_length, canvasWidth)

    ctx.fillStyle = '#ddd'
    ctx.fillText(g.label, 8, y - 6)

    const painting = paintByGenome.get(g.id)
    const drawnSeqs = painting
      ? drawPaintedBars(ctx, g, painting, referenceColorMap, vp, canvasWidth, y, layout, startBp, endBp)
      : drawSeqPaletteBars(ctx, g, vp, canvasWidth, y, layout, startBp, endBp)

    // Sequence name labels (on top of whatever colour bars we drew)
    if (ppb > 0) {
      ctx.fillStyle = 'rgba(255, 255, 255, 0.95)'
      ctx.strokeStyle = 'rgba(0, 0, 0, 0.6)'
      ctx.lineWidth = 3
      ctx.textAlign = 'center'
      for (const { name, x0, x1 } of drawnSeqs) {
        const w = x1 - x0
        if (w > 30) {
          const cx = x0 + w / 2
          const cy = y + layout.trackHeight / 2 + 4
          ctx.strokeText(name, cx, cy)
          ctx.fillText(name, cx, cy)
        }
      }
      ctx.textAlign = 'start'
      ctx.lineWidth = 1
    }
  }
}

type DrawnSeq = { name: string; x0: number; x1: number }

function drawSeqPaletteBars(
  ctx: CanvasRenderingContext2D,
  g: Genome,
  viewport: Viewport,
  canvasWidth: number,
  y: number,
  layout: TrackLayout,
  startBp: number,
  endBp: number,
): DrawnSeq[] {
  const out: DrawnSeq[] = []
  for (const seq of g.sequences) {
    const seqStart = seq.offset
    const seqEnd = seq.offset + seq.length
    if (seqEnd <= startBp || seqStart >= endBp) continue
    const x0 = Math.max(0, bpToPx(seqStart, viewport, g.total_length, canvasWidth))
    const x1 = Math.min(canvasWidth, bpToPx(seqEnd, viewport, g.total_length, canvasWidth))
    const w = Math.max(1, x1 - x0)
    ctx.fillStyle = seq.color
    ctx.fillRect(x0, y, w, layout.trackHeight)
    ctx.strokeStyle = 'rgba(0, 0, 0, 0.45)'
    ctx.strokeRect(x0 + 0.5, y + 0.5, w - 1, layout.trackHeight - 1)
    out.push({ name: seq.name, x0, x1 })
  }
  return out
}

function drawPaintedBars(
  ctx: CanvasRenderingContext2D,
  g: Genome,
  regions: PaintRegion[],
  referenceColorMap: Map<string, string>,
  viewport: Viewport,
  canvasWidth: number,
  y: number,
  layout: TrackLayout,
  startBp: number,
  endBp: number,
): DrawnSeq[] {
  // Build per-sequence offset table once.
  const seqOffsets = new Map(g.sequences.map((s) => [s.name, s]))

  // First pass: paint each sequence's full span in UNKNOWN_COLOR, so uncovered
  // stretches still register visually.
  const drawnSeqs: DrawnSeq[] = []
  for (const seq of g.sequences) {
    const seqStart = seq.offset
    const seqEnd = seq.offset + seq.length
    if (seqEnd <= startBp || seqStart >= endBp) continue
    const x0 = Math.max(0, bpToPx(seqStart, viewport, g.total_length, canvasWidth))
    const x1 = Math.min(canvasWidth, bpToPx(seqEnd, viewport, g.total_length, canvasWidth))
    ctx.fillStyle = UNKNOWN_COLOR
    ctx.fillRect(x0, y, Math.max(1, x1 - x0), layout.trackHeight)
    drawnSeqs.push({ name: seq.name, x0, x1 })
  }

  // Second pass: paint each region over its base.
  for (const r of regions) {
    const seq = seqOffsets.get(r.seq)
    if (!seq) continue
    const rStart = seq.offset + r.start
    const rEnd = seq.offset + r.end
    if (rEnd <= startBp || rStart >= endBp) continue
    const x0 = Math.max(0, bpToPx(rStart, viewport, g.total_length, canvasWidth))
    const x1 = Math.min(canvasWidth, bpToPx(rEnd, viewport, g.total_length, canvasWidth))
    const w = Math.max(1, x1 - x0)
    ctx.fillStyle = colorFor(r.reference_seq, referenceColorMap)
    ctx.fillRect(x0, y, w, layout.trackHeight)
  }

  // Border around each sequence to separate bars visually.
  ctx.strokeStyle = 'rgba(0, 0, 0, 0.45)'
  for (const { x0, x1 } of drawnSeqs) {
    const w = Math.max(1, x1 - x0)
    ctx.strokeRect(x0 + 0.5, y + 0.5, w - 1, layout.trackHeight - 1)
  }

  return drawnSeqs
}
