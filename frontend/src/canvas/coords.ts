// Per-genome coordinate transforms.
//
// Each genome has its own world (its total length in bp). The shared Viewport
// applies the same fractional zoom + pan to every genome — so when zoomed out
// every genome fills the canvas; when zoomed in we see the same fractional
// region on each.

export type Viewport = {
  zoom: number   // 1 = entire genome fits canvas; >1 = zoomed in
  center: number // fractional position [0..1] of the visible window's center
}

export const DEFAULT_VIEWPORT: Viewport = { zoom: 1, center: 0.5 }

export function clampCenter(center: number): number {
  if (center < 0) return 0
  if (center > 1) return 1
  return center
}

export function clampZoom(zoom: number, min = 1, max = 1e6): number {
  if (zoom < min) return min
  if (zoom > max) return max
  return zoom
}

export function pixelsPerBp(viewport: Viewport, totalLength: number, canvasWidth: number): number {
  if (totalLength <= 0 || canvasWidth <= 0) return 0
  return (canvasWidth / totalLength) * viewport.zoom
}

export type VisibleRange = { startBp: number; endBp: number }

export function visibleRange(
  viewport: Viewport,
  totalLength: number,
  canvasWidth: number,
): VisibleRange {
  const ppb = pixelsPerBp(viewport, totalLength, canvasWidth)
  if (ppb === 0) return { startBp: 0, endBp: totalLength }
  const visibleBp = canvasWidth / ppb
  let startBp = viewport.center * totalLength - visibleBp / 2
  // Clamp so we never show beyond [0, totalLength]
  if (startBp < 0) startBp = 0
  let endBp = startBp + visibleBp
  if (endBp > totalLength) {
    endBp = totalLength
    startBp = Math.max(0, endBp - visibleBp)
  }
  return { startBp, endBp }
}

export function bpToPx(
  bp: number,
  viewport: Viewport,
  totalLength: number,
  canvasWidth: number,
): number {
  const { startBp } = visibleRange(viewport, totalLength, canvasWidth)
  const ppb = pixelsPerBp(viewport, totalLength, canvasWidth)
  return (bp - startBp) * ppb
}

export function pxToBp(
  px: number,
  viewport: Viewport,
  totalLength: number,
  canvasWidth: number,
): number {
  const { startBp } = visibleRange(viewport, totalLength, canvasWidth)
  const ppb = pixelsPerBp(viewport, totalLength, canvasWidth)
  return ppb === 0 ? 0 : startBp + px / ppb
}

/** Zoom the viewport, keeping the bp under the cursor pinned to that pixel. */
export function zoomAtFraction(
  viewport: Viewport,
  cursorFraction: number, // [0..1] across canvas
  factor: number,
): Viewport {
  const newZoom = clampZoom(viewport.zoom * factor)
  // The bp at cursor before zoom (as fraction of total): some f_before
  // We want: f_before stays at cursorFraction in the new viewport.
  //
  // Visible window width in fraction: 1 / zoom. Center at viewport.center.
  // → fraction at canvas position p = center + (p - 0.5) / zoom
  const fBefore = viewport.center + (cursorFraction - 0.5) / viewport.zoom
  const newCenter = fBefore - (cursorFraction - 0.5) / newZoom
  return {
    zoom: newZoom,
    center: clampCenter(newCenter),
  }
}

/**
 * Find the sequence covering the viewport center and return a "seq:start-end"
 * region string suitable for the /synteny/scms region_g1 / region_g2 params.
 * Returns undefined if the genome has no sequences or the viewport spans
 * beyond any single sequence boundary.
 */
export function visibleRegionString(
  genome: { total_length: number; sequences: { name: string; length: number; offset: number }[] },
  viewport: Viewport,
  canvasWidth: number,
): string | undefined {
  const { startBp, endBp } = visibleRange(viewport, genome.total_length, canvasWidth)
  if (genome.sequences.length === 0) return undefined
  // Find the sequence containing the center of the visible range.
  const center = (startBp + endBp) / 2
  let seq: { name: string; length: number; offset: number } | undefined
  for (const s of genome.sequences) {
    if (center >= s.offset && center < s.offset + s.length) {
      seq = s
      break
    }
  }
  if (!seq) return undefined
  // Clamp the visible range to this sequence's bounds and convert to local coords.
  const localStart = Math.max(0, Math.floor(startBp - seq.offset))
  const localEnd = Math.min(seq.length, Math.ceil(endBp - seq.offset))
  if (localEnd <= localStart) return undefined
  return `${seq.name}:${localStart}-${localEnd}`
}

/** Pan by a fraction of the visible window (e.g., dragging by 30 px on a 600px canvas → -0.05). */
export function panByFraction(viewport: Viewport, deltaFraction: number): Viewport {
  // delta is in canvas-fraction; convert to total-fraction = delta / zoom
  return {
    zoom: viewport.zoom,
    center: clampCenter(viewport.center - deltaFraction / viewport.zoom),
  }
}
