// SCM-line renderer for the high-zoom (LOD=scm) regime. One line per shared SCM.
// Color comes from each SCM's reference_seq, looked up in the reference genome's
// palette (v0.1.1 color propagation).

import type { Genome, PairwiseSCM } from '../api/types'
import { colorFor } from './colors'
import { bpToPx, visibleRange } from './coords'
import {
  DEFAULT_LAYOUT,
  type TrackLayout,
  type ViewportFn,
  trackY,
} from './draw_tracks'

export type AdjacentPairScms = {
  topIndex: number
  bottomIndex: number
  g1: Genome
  g2: Genome
  scms: PairwiseSCM[] | null
}

export function drawScmLines(
  ctx: CanvasRenderingContext2D,
  pairs: AdjacentPairScms[],
  viewportFn: ViewportFn,
  canvasWidth: number,
  canvasHeight: number,
  referenceColorMap: Map<string, string>,
  fadeMultiplier = 1,
  baseOpacity = 0.55,
  layout: TrackLayout = DEFAULT_LAYOUT,
): void {
  ctx.clearRect(0, 0, canvasWidth, canvasHeight)
  ctx.lineWidth = 1
  ctx.globalAlpha = baseOpacity * fadeMultiplier

  for (const pair of pairs) {
    if (!pair.scms || pair.scms.length === 0) continue
    const yTopBottom = trackY(pair.topIndex, layout) + layout.trackHeight
    const yBottomTop = trackY(pair.bottomIndex, layout)
    const vp1 = viewportFn(pair.g1.id)
    const vp2 = viewportFn(pair.g2.id)
    const g1SeqOffset = new Map(pair.g1.sequences.map((s) => [s.name, s.offset]))
    const g2SeqOffset = new Map(pair.g2.sequences.map((s) => [s.name, s.offset]))

    const { startBp: g1Start, endBp: g1End } = visibleRange(
      vp1,
      pair.g1.total_length,
      canvasWidth,
    )
    const { startBp: g2Start, endBp: g2End } = visibleRange(
      vp2,
      pair.g2.total_length,
      canvasWidth,
    )

    // Group by color so we batch strokes (one stroke call per color bucket).
    const buckets = new Map<string, Path2D>()

    for (const scm of pair.scms) {
      const off1 = g1SeqOffset.get(scm.g1_seq)
      const off2 = g2SeqOffset.get(scm.g2_seq)
      if (off1 === undefined || off2 === undefined) continue

      const g1Mid = off1 + (scm.g1_start + scm.g1_end) / 2
      const g2Mid = off2 + (scm.g2_start + scm.g2_end) / 2
      if (g1Mid < g1Start || g1Mid > g1End) continue
      if (g2Mid < g2Start || g2Mid > g2End) continue

      const x1 = bpToPx(g1Mid, vp1, pair.g1.total_length, canvasWidth)
      const x2 = bpToPx(g2Mid, vp2, pair.g2.total_length, canvasWidth)
      const color = colorFor(scm.reference_seq, referenceColorMap)
      let path = buckets.get(color)
      if (!path) {
        path = new Path2D()
        buckets.set(color, path)
      }
      path.moveTo(x1, yTopBottom)
      path.lineTo(x2, yBottomTop)
    }

    for (const [color, path] of buckets) {
      ctx.strokeStyle = color
      ctx.stroke(path)
    }
  }
  ctx.globalAlpha = 1
}
