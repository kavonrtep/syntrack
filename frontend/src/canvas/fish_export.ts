// High-resolution PNG export of the multi-colour FISH density karyotype.
// Composes a standalone figure: title-less black canvas with a colour legend,
// one labelled density bar per genome, reusing the on-screen compositing so the
// image matches the live preview exactly (just at higher resolution).

import type { FishDensityResponse, Genome } from '../api/types'
import { buildActiveSets, drawGenomeBar } from './draw_fish_density'

export type FishExportLayout = {
  width: number
  gutter: number // left margin for genome labels
  rightPad: number
  barHeight: number
  gap: number
  topPad: number // legend area
  bottomPad: number
}

export const DEFAULT_EXPORT_LAYOUT: FishExportLayout = {
  width: 4000,
  gutter: 420,
  rightPad: 40,
  barHeight: 64,
  gap: 30,
  topPad: 150,
  bottomPad: 50,
}

/** The density bin count that matches a layout's bar width (for a crisp image). */
export function exportBins(layout: FishExportLayout = DEFAULT_EXPORT_LAYOUT): number {
  return Math.round(layout.width - layout.gutter - layout.rightPad)
}

export function renderFishDensityImage(
  density: FishDensityResponse,
  genomesInOrder: Genome[],
  visibleLabels: Set<string>,
  layout: FishExportLayout = DEFAULT_EXPORT_LAYOUT,
): HTMLCanvasElement {
  const { width, gutter, rightPad, barHeight, gap, topPad, bottomPad } = layout
  const barWidth = width - gutter - rightPad
  const height = topPad + genomesInOrder.length * (barHeight + gap) + bottomPad

  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d')
  if (!ctx) return canvas

  ctx.fillStyle = '#000000'
  ctx.fillRect(0, 0, width, height)

  // Legend: a swatch + label per visible set, left to right across the top.
  const legendSets = density.sets.filter((s) => visibleLabels.has(s.label))
  ctx.textBaseline = 'middle'
  ctx.font = '26px system-ui, sans-serif'
  let lx = gutter
  const ly = topPad / 2
  for (const s of legendSets) {
    ctx.fillStyle = s.color
    ctx.fillRect(lx, ly - 14, 28, 28)
    ctx.fillStyle = '#e8e8e8'
    const text = `${s.label} (${s.scm_count.toLocaleString()})`
    ctx.fillText(text, lx + 38, ly)
    lx += 38 + ctx.measureText(text).width + 48
  }

  // Density bars + genome labels.
  const active = buildActiveSets(density.sets, visibleLabels)
  for (let i = 0; i < genomesInOrder.length; i++) {
    const g = genomesInOrder[i]
    const y = topPad + i * (barHeight + gap)
    drawGenomeBar(ctx, active, g, density.bins, gutter, y, barWidth, barHeight)
    ctx.fillStyle = '#dddddd'
    ctx.font = '28px system-ui, sans-serif'
    ctx.textAlign = 'left'
    ctx.fillText(g.label, 24, y + barHeight / 2, gutter - 40)
  }

  return canvas
}

export function downloadCanvasPng(canvas: HTMLCanvasElement, filename: string): void {
  canvas.toBlob((blob) => {
    if (!blob) return
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }, 'image/png')
}
