// Block-ribbon renderer. For every adjacent pair, draws one quadrilateral per
// block connecting the g1 sequence segment (on the top track) to the g2
// segment (on the bottom track). Color comes from the block's reference_seq
// looked up in the reference genome's palette (v0.1.1 color propagation).

import type { Genome, SyntenyBlock } from '../api/types'
import { colorFor } from './colors'
import {
  bpToPx,
  visibleRange,
  type Viewport,
} from './coords'
import { DEFAULT_LAYOUT, type TrackLayout, trackY } from './draw_tracks'

export type AdjacentPair = {
  topIndex: number
  bottomIndex: number
  g1: Genome
  g2: Genome
  blocks: SyntenyBlock[] | null // null = still loading
}

function clipBp(bp: number, lo: number, hi: number): number {
  if (bp < lo) return lo
  if (bp > hi) return hi
  return bp
}

function densityToOpacity(scmCount: number, spanBp: number, baseOpacity: number): number {
  if (spanBp <= 0) return baseOpacity
  // Heuristic: 1 SCM per kb saturates; smaller density fades.
  const density = scmCount / (spanBp / 1000)
  const factor = Math.min(1, 0.3 + density)
  return Math.min(1, baseOpacity * factor)
}

export function drawRibbons(
  ctx: CanvasRenderingContext2D,
  pairs: AdjacentPair[],
  viewport: Viewport,
  canvasWidth: number,
  canvasHeight: number,
  referenceColorMap: Map<string, string>,
  baseOpacity = 0.45,
  layout: TrackLayout = DEFAULT_LAYOUT,
): void {
  ctx.clearRect(0, 0, canvasWidth, canvasHeight)
  ctx.lineWidth = 0

  for (const pair of pairs) {
    if (!pair.blocks || pair.blocks.length === 0) continue

    const yTopBottom = trackY(pair.topIndex, layout) + layout.trackHeight
    const yBottomTop = trackY(pair.bottomIndex, layout)

    const g1SeqOffset = new Map(pair.g1.sequences.map((s) => [s.name, s.offset]))
    const g2SeqOffset = new Map(pair.g2.sequences.map((s) => [s.name, s.offset]))

    const { startBp: g1Start, endBp: g1End } = visibleRange(
      viewport,
      pair.g1.total_length,
      canvasWidth,
    )
    const { startBp: g2Start, endBp: g2End } = visibleRange(
      viewport,
      pair.g2.total_length,
      canvasWidth,
    )

    for (const block of pair.blocks) {
      const off1 = g1SeqOffset.get(block.g1_seq)
      const off2 = g2SeqOffset.get(block.g2_seq)
      if (off1 === undefined || off2 === undefined) continue

      const g1A = off1 + block.g1_start
      const g1B = off1 + block.g1_end
      const g2A = off2 + block.g2_start
      const g2B = off2 + block.g2_end

      // Skip if entirely outside the visible window of either genome.
      if (g1B < g1Start || g1A > g1End) continue
      if (g2B < g2Start || g2A > g2End) continue

      const x1a = bpToPx(
        clipBp(g1A, g1Start, g1End),
        viewport,
        pair.g1.total_length,
        canvasWidth,
      )
      const x1b = bpToPx(
        clipBp(g1B, g1Start, g1End),
        viewport,
        pair.g1.total_length,
        canvasWidth,
      )
      const x2a = bpToPx(
        clipBp(g2A, g2Start, g2End),
        viewport,
        pair.g2.total_length,
        canvasWidth,
      )
      const x2b = bpToPx(
        clipBp(g2B, g2Start, g2End),
        viewport,
        pair.g2.total_length,
        canvasWidth,
      )

      const color = colorFor(block.reference_seq, referenceColorMap)
      const span = (g1B - g1A + g2B - g2A) / 2
      const opacity = densityToOpacity(block.scm_count, span, baseOpacity)

      ctx.fillStyle = color
      ctx.globalAlpha = opacity

      ctx.beginPath()
      ctx.moveTo(x1a, yTopBottom)
      ctx.lineTo(x1b, yTopBottom)
      if (block.strand === '+') {
        // Parallel ribbon
        ctx.lineTo(x2b, yBottomTop)
        ctx.lineTo(x2a, yBottomTop)
      } else {
        // Crossed ribbon
        ctx.lineTo(x2a, yBottomTop)
        ctx.lineTo(x2b, yBottomTop)
      }
      ctx.closePath()
      ctx.fill()
    }
  }
  ctx.globalAlpha = 1
}
