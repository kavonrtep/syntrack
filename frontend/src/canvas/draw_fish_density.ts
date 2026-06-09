// Multi-colour FISH density renderer.
//
// Each visible marker set is composited *additively* onto a dark chromosome
// bar: pixel colour = Σ (setColour × intensity), clamped — so overlapping sets
// blend like fluorescence channels (red + green → yellow). Density comes from
// the backend histogram, which counts every SCM (no subsampling), so this is
// the un-subsampled ground truth the capped live view can be checked against.
//
// View is whole-genome (zoom = 1) while in preview, so every genome's bar fills
// the full width and bin b maps to x = b/bins · width for all genomes alike.

import type { FishDensitySet, Genome } from '../api/types'
import { type Ctx2D, DEFAULT_LAYOUT, type TrackLayout, trackY } from './draw_tracks'

const BAR_BG = '#0a0a0a'
const SEP = 'rgba(255, 255, 255, 0.18)'

export type ActiveSet = {
  rgb: [number, number, number]
  inv: number
  genomes: Record<string, number[]>
}

function hexToRgb(hex: string): [number, number, number] {
  const m = /^#([0-9a-f]{6})$/i.exec(hex)
  if (!m) return [255, 255, 255]
  const n = Number.parseInt(m[1], 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

/** Precompute per-set RGB + inverse normalizer for the visible sets. Per-set
 *  normalization means each set spans its own full brightness range, so faint
 *  sets stay visible next to dense ones. */
export function buildActiveSets(sets: FishDensitySet[], visibleLabels: Set<string>): ActiveSet[] {
  return sets
    .filter((s) => visibleLabels.has(s.label) && s.max_count > 0)
    .map((s) => ({ rgb: hexToRgb(s.color), inv: 1 / s.max_count, genomes: s.genomes }))
}

/** Render one genome's density bar (dark background + additive multi-colour
 *  composite + chromosome separators) into the rectangle (x0, y, barWidth,
 *  barHeight). Shared by the on-screen render and the PNG export. */
export function drawGenomeBar(
  ctx: Ctx2D,
  active: ActiveSet[],
  genome: Genome,
  bins: number,
  x0: number,
  y: number,
  barWidth: number,
  barHeight: number,
): void {
  ctx.fillStyle = BAR_BG
  ctx.fillRect(x0, y, barWidth, barHeight)
  if (bins <= 0) return

  const binW = barWidth / bins
  const cols = active
    .map((a) => ({ rgb: a.rgb, inv: a.inv, counts: a.genomes[genome.id] }))
    .filter((a): a is { rgb: [number, number, number]; inv: number; counts: number[] } =>
      a.counts !== undefined,
    )
  for (let b = 0; b < bins && cols.length > 0; b++) {
    let r = 0
    let gg = 0
    let bl = 0
    for (const c of cols) {
      const v = c.counts[b]
      if (!v) continue
      // sqrt display gain lifts faint bands while preserving relative order.
      const intensity = Math.sqrt(v * c.inv)
      r += c.rgb[0] * intensity
      gg += c.rgb[1] * intensity
      bl += c.rgb[2] * intensity
    }
    if (r === 0 && gg === 0 && bl === 0) continue
    ctx.fillStyle = `rgb(${Math.min(255, r) | 0}, ${Math.min(255, gg) | 0}, ${Math.min(255, bl) | 0})`
    ctx.fillRect(x0 + b * binW, y, Math.max(1, binW), barHeight)
  }

  // Chromosome separators (whole-genome: x = offset / total_length · barWidth).
  if (genome.total_length > 0) {
    ctx.fillStyle = SEP
    for (const s of genome.sequences) {
      const x = x0 + Math.round((s.offset / genome.total_length) * barWidth)
      ctx.fillRect(x, y - 2, 1, barHeight + 4)
    }
  }
}

export function drawFishDensity(
  ctx: Ctx2D,
  sets: FishDensitySet[],
  visibleLabels: Set<string>,
  genomesInOrder: Genome[],
  bins: number,
  canvasWidth: number,
  canvasHeight: number,
  layout: TrackLayout = DEFAULT_LAYOUT,
): void {
  ctx.clearRect(0, 0, canvasWidth, canvasHeight)
  if (bins <= 0) return
  const active = buildActiveSets(sets, visibleLabels)
  for (let i = 0; i < genomesInOrder.length; i++) {
    drawGenomeBar(
      ctx,
      active,
      genomesInOrder[i],
      bins,
      0,
      trackY(i, layout),
      canvasWidth,
      layout.trackHeight,
    )
  }
}
