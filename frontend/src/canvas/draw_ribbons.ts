// Block-ribbon renderer. For every adjacent pair, draws one quadrilateral per
// block connecting the g1 sequence segment (on the top track) to the g2
// segment (on the bottom track). Color comes from the block's reference_seq
// looked up in the reference genome's palette (v0.1.1 color propagation).
//
// Performance: quadrilaterals are batched into one Path2D per colour and
// flushed with a single fill() per colour. Blocks narrower than a pixel on
// both sides are skipped.

import type { Genome, SyntenyBlock } from '../api/types'
import { colorFor } from './colors'
import { bpToPx, visibleRange } from './coords'
import {
  DEFAULT_LAYOUT,
  type TrackLayout,
  type ViewportFn,
  trackY,
} from './draw_tracks'

export type AdjacentPair = {
  topIndex: number
  bottomIndex: number
  g1: Genome
  g2: Genome
  blocks: SyntenyBlock[] | null
}

function clipBp(bp: number, lo: number, hi: number): number {
  if (bp < lo) return lo
  if (bp > hi) return hi
  return bp
}

// Quantize per-block opacity into 4 buckets so we still issue only
// O(colors * 4) fills. Values chosen to read on a dark background
// across a wide density range.
const OPACITY_BY_BUCKET = [0.25, 0.45, 0.65, 0.85]

function opacityBucketIndex(scmCount: number, spanBp: number): number {
  if (spanBp <= 0) return OPACITY_BY_BUCKET.length - 1
  const density = scmCount / (spanBp / 1000) // SCMs per kb
  // density < 0.2 → bucket 0; 0.2-0.5 → 1; 0.5-1.0 → 2; >=1.0 → 3
  if (density < 0.2) return 0
  if (density < 0.5) return 1
  if (density < 1.0) return 2
  return 3
}

export function drawRibbons(
  ctx: CanvasRenderingContext2D,
  pairs: AdjacentPair[],
  viewportFn: ViewportFn,
  canvasWidth: number,
  canvasHeight: number,
  referenceColorMap: Map<string, string>,
  _baseOpacity = 0.45, // kept for API compatibility; opacity now driven by density buckets
  layout: TrackLayout = DEFAULT_LAYOUT,
): void {
  ctx.clearRect(0, 0, canvasWidth, canvasHeight)

  // Path2Ds keyed by "color|bucket" — one fill call per (color, opacity bucket).
  const buckets = new Map<string, Path2D>()
  const getPath = (color: string, bucket: number): Path2D => {
    const key = `${color}|${bucket}`
    let p = buckets.get(key)
    if (!p) {
      p = new Path2D()
      buckets.set(key, p)
    }
    return p
  }

  for (const pair of pairs) {
    if (!pair.blocks || pair.blocks.length === 0) continue

    const yTopBottom = trackY(pair.topIndex, layout) + layout.trackHeight
    const yBottomTop = trackY(pair.bottomIndex, layout)

    const vp1 = viewportFn(pair.g1.id)
    const vp2 = viewportFn(pair.g2.id)

    const g1SeqOffset = new Map(pair.g1.sequences.map((s) => [s.name, s.offset]))
    const g2SeqOffset = new Map(pair.g2.sequences.map((s) => [s.name, s.offset]))

    const { startBp: g1Start, endBp: g1End } = visibleRange(vp1, pair.g1.total_length, canvasWidth)
    const { startBp: g2Start, endBp: g2End } = visibleRange(vp2, pair.g2.total_length, canvasWidth)

    for (const block of pair.blocks) {
      const off1 = g1SeqOffset.get(block.g1_seq)
      const off2 = g2SeqOffset.get(block.g2_seq)
      if (off1 === undefined || off2 === undefined) continue

      const g1A = off1 + block.g1_start
      const g1B = off1 + block.g1_end
      const g2A = off2 + block.g2_start
      const g2B = off2 + block.g2_end

      if (g1B < g1Start || g1A > g1End) continue
      if (g2B < g2Start || g2A > g2End) continue

      const x1a = bpToPx(clipBp(g1A, g1Start, g1End), vp1, pair.g1.total_length, canvasWidth)
      const x1b = bpToPx(clipBp(g1B, g1Start, g1End), vp1, pair.g1.total_length, canvasWidth)
      const x2a = bpToPx(clipBp(g2A, g2Start, g2End), vp2, pair.g2.total_length, canvasWidth)
      const x2b = bpToPx(clipBp(g2B, g2Start, g2End), vp2, pair.g2.total_length, canvasWidth)

      // Sub-pixel on both sides → invisible. Skip.
      if (x1b - x1a < 1 && Math.abs(x2b - x2a) < 1) continue

      const color = colorFor(block.reference_seq, referenceColorMap)
      const span = ((g1B - g1A) + (g2B - g2A)) / 2
      const bucket = opacityBucketIndex(block.scm_count, span)
      const path = getPath(color, bucket)
      path.moveTo(x1a, yTopBottom)
      path.lineTo(x1b, yTopBottom)
      if (block.strand === '+') {
        path.lineTo(x2b, yBottomTop)
        path.lineTo(x2a, yBottomTop)
      } else {
        path.lineTo(x2a, yBottomTop)
        path.lineTo(x2b, yBottomTop)
      }
      path.closePath()
    }
  }

  for (const [key, path] of buckets) {
    const sep = key.lastIndexOf('|')
    const color = key.slice(0, sep)
    const bucketIdx = Number(key.slice(sep + 1))
    ctx.fillStyle = color
    ctx.globalAlpha = OPACITY_BY_BUCKET[bucketIdx]
    ctx.fill(path)
  }
  ctx.globalAlpha = 1
}
