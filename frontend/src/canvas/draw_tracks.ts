// Track-canvas renderer: one horizontal bar per genome, segmented by sequence.

import type { Genome } from '../api/types'
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

export function drawTracks(
  ctx: CanvasRenderingContext2D,
  genomesInOrder: Genome[],
  viewport: Viewport,
  canvasWidth: number,
  canvasHeight: number,
  layout: TrackLayout = DEFAULT_LAYOUT,
): void {
  ctx.clearRect(0, 0, canvasWidth, canvasHeight)
  ctx.font = '11px system-ui, sans-serif'
  ctx.textBaseline = 'alphabetic'

  for (let i = 0; i < genomesInOrder.length; i++) {
    const g = genomesInOrder[i]
    const y = trackY(i, layout)
    const ppb = pixelsPerBp(viewport, g.total_length, canvasWidth)
    const { startBp, endBp } = visibleRange(viewport, g.total_length, canvasWidth)

    // Label
    ctx.fillStyle = '#ddd'
    ctx.fillText(g.label, 8, y - 6)

    // Sequence bars
    for (const seq of g.sequences) {
      const seqStart = seq.offset
      const seqEnd = seq.offset + seq.length
      if (seqEnd <= startBp || seqStart >= endBp) continue

      const x0 = Math.max(0, bpToPx(seqStart, viewport, g.total_length, canvasWidth))
      const x1 = Math.min(
        canvasWidth,
        bpToPx(seqEnd, viewport, g.total_length, canvasWidth),
      )
      const w = Math.max(1, x1 - x0)

      ctx.fillStyle = seq.color
      ctx.fillRect(x0, y, w, layout.trackHeight)

      // Subtle border so adjacent same-color sequences are distinguishable
      ctx.strokeStyle = 'rgba(0, 0, 0, 0.45)'
      ctx.lineWidth = 1
      ctx.strokeRect(x0 + 0.5, y + 0.5, w - 1, layout.trackHeight - 1)

      // Sequence name centered if there's room
      if (ppb > 0 && w > 30) {
        ctx.fillStyle = 'rgba(0, 0, 0, 0.85)'
        ctx.textAlign = 'center'
        ctx.fillText(seq.name, x0 + w / 2, y + layout.trackHeight / 2 + 4)
        ctx.textAlign = 'start'
      }
    }
  }
}
