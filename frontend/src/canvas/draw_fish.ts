// FISH marker-set overlay renderer (Phase 3 — F4).
//
// Draws colored vertical ticks on every genome track for each visible FISH set.
// Uses distinct per-set colors (user-chosen), independent of the reference palette.
// Rendered on the overlay canvas, underneath the transient highlight.

import type { FishSetResponse, Genome } from '../api/types'
import { bpToPx } from './coords'
import {
  DEFAULT_LAYOUT,
  type TrackLayout,
  type ViewportFn,
  trackY,
} from './draw_tracks'

export function drawFishSets(
  ctx: CanvasRenderingContext2D,
  fishSets: Map<string, FishSetResponse>,
  visibleLabels: Set<string>,
  genomesInOrder: Genome[],
  viewportFn: ViewportFn,
  canvasWidth: number,
  _canvasHeight: number,
  layout: TrackLayout = DEFAULT_LAYOUT,
): void {
  if (visibleLabels.size === 0) return

  // Pre-build genome index lookup.
  const genomeIdxById = new Map<string, number>()
  for (let i = 0; i < genomesInOrder.length; i++) {
    genomeIdxById.set(genomesInOrder[i].id, i)
  }

  // Sequence-offset lookup per genome (built lazily, cached across sets).
  const seqOffsetCache = new Map<string, Map<string, number>>()
  function seqOffsets(genome: Genome): Map<string, number> {
    let cached = seqOffsetCache.get(genome.id)
    if (!cached) {
      cached = new Map(genome.sequences.map((s) => [s.name, s.offset]))
      seqOffsetCache.set(genome.id, cached)
    }
    return cached
  }

  // Draw each visible set as a batch of ticks in its color.
  for (const [label, fishSet] of fishSets) {
    if (!visibleLabels.has(label)) continue

    const path = new Path2D()
    for (const gc of fishSet.genomes) {
      const idx = genomeIdxById.get(gc.genome_id)
      if (idx === undefined) continue
      const genome = genomesInOrder[idx]
      const vp = viewportFn(genome.id)
      const y = trackY(idx, layout)
      const offsets = seqOffsets(genome)

      for (const pos of gc.positions) {
        const seqOff = offsets.get(pos.seq)
        if (seqOff === undefined) continue
        const mid = (pos.start + pos.end) / 2
        const x = bpToPx(seqOff + mid, vp, genome.total_length, canvasWidth)
        if (x < -1 || x > canvasWidth + 1) continue
        const px = Math.round(x) + 0.5
        path.moveTo(px, y)
        path.lineTo(px, y + layout.trackHeight)
      }
    }

    ctx.strokeStyle = fishSet.color
    ctx.lineWidth = 2
    ctx.globalAlpha = 0.85
    ctx.stroke(path)
  }
  ctx.globalAlpha = 1
}
