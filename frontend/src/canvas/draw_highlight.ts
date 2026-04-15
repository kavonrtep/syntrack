// Highlight overlay renderer (Phase 3.1):
//   - source rectangle on the clicked genome's bar
//   - thin vertical ticks on every target genome's bar at each matching SCM
//
// All drawing is colour-independent of the reference palette (a distinct
// accent hue) so the highlight visually separates from the painted bars.

import type { Genome, HighlightResponse } from '../api/types'
import { bpToPx } from './coords'
import {
  DEFAULT_LAYOUT,
  type TrackLayout,
  type ViewportFn,
  trackY,
} from './draw_tracks'

export const HIGHLIGHT_ACCENT = '#ffdc32'
export const HIGHLIGHT_FILL_PENDING = 'rgba(255, 220, 50, 0.16)'
export const HIGHLIGHT_FILL_CONFIRMED = 'rgba(255, 220, 50, 0.28)'

export type HighlightSource = {
  genomeIdx: number
  genome: Genome
  seq: string
  /** Local bp (0-based) in ``seq``. Half-open [startBp, endBp) after sort. */
  startBp: number
  endBp: number
}

export type HighlightOverlay = {
  /** The currently-selected region on the anchor genome. Present during an
   *  in-progress drag (pending) and after confirmation. Null when nothing
   *  is selected. */
  source: HighlightSource | null
  /** True while the user is still dragging; switches to false after fetch
   *  completes. Affects the rectangle's fill opacity / border weight. */
  isSelecting: boolean
  /** The /api/highlight response (ticks on every target). Null until the
   *  fetch resolves. */
  result: HighlightResponse | null
}

export function drawHighlight(
  ctx: CanvasRenderingContext2D,
  overlay: HighlightOverlay,
  genomesInOrder: Genome[],
  viewportFn: ViewportFn,
  canvasWidth: number,
  canvasHeight: number,
  layout: TrackLayout = DEFAULT_LAYOUT,
): void {
  ctx.clearRect(0, 0, canvasWidth, canvasHeight)
  if (!overlay.source && !overlay.result) return

  // Source rectangle (drawn first so ticks layer on top if they fall inside).
  if (overlay.source) {
    const { genomeIdx, genome, seq, startBp, endBp } = overlay.source
    const vp = viewportFn(genome.id)
    const seqObj = genome.sequences.find((s) => s.name === seq)
    if (seqObj) {
      const lo = Math.min(startBp, endBp)
      const hi = Math.max(startBp, endBp)
      const rawX0 = bpToPx(seqObj.offset + lo, vp, genome.total_length, canvasWidth)
      const rawX1 = bpToPx(seqObj.offset + hi, vp, genome.total_length, canvasWidth)
      const x0 = Math.max(0, Math.min(canvasWidth, rawX0))
      const x1 = Math.max(0, Math.min(canvasWidth, rawX1))
      const w = Math.max(1, x1 - x0)
      const y = trackY(genomeIdx, layout)
      ctx.fillStyle = overlay.isSelecting ? HIGHLIGHT_FILL_PENDING : HIGHLIGHT_FILL_CONFIRMED
      ctx.fillRect(x0, y, w, layout.trackHeight)
      ctx.strokeStyle = HIGHLIGHT_ACCENT
      ctx.lineWidth = overlay.isSelecting ? 1 : 2
      ctx.strokeRect(x0 + 0.5, y + 0.5, w - 1, layout.trackHeight - 1)
    }
  }

  if (!overlay.result) return

  // Target ticks: one 1.5 px vertical line per matching SCM, stroked in a
  // single Path2D across every target genome.
  const path = new Path2D()
  const genomeIdxById = new Map<string, number>()
  for (let i = 0; i < genomesInOrder.length; i++) {
    genomeIdxById.set(genomesInOrder[i].id, i)
  }
  for (const target of overlay.result.targets) {
    const idx = genomeIdxById.get(target.genome_id)
    if (idx === undefined) continue
    const genome = genomesInOrder[idx]
    const vp = viewportFn(genome.id)
    const y = trackY(idx, layout)
    for (const pos of target.positions) {
      const seqObj = genome.sequences.find((s) => s.name === pos.seq)
      if (!seqObj) continue
      const mid = (pos.start + pos.end) / 2
      const x = bpToPx(seqObj.offset + mid, vp, genome.total_length, canvasWidth)
      if (x < -1 || x > canvasWidth + 1) continue
      const px = Math.round(x) + 0.5
      path.moveTo(px, y)
      path.lineTo(px, y + layout.trackHeight)
    }
  }
  ctx.strokeStyle = HIGHLIGHT_ACCENT
  ctx.lineWidth = 1.5
  ctx.globalAlpha = 0.9
  ctx.stroke(path)
  ctx.globalAlpha = 1
}
