// Canvas hit-testing helpers. Used for scoped zoom/pan (v0.1.1): given a
// pointer Y in canvas-local coordinates, figure out which genome row the
// cursor is over.

import { DEFAULT_LAYOUT, type TrackLayout, trackY } from './draw_tracks'

/** Return the index of the genome whose track bar contains ``y``, or ``null``
 *  if ``y`` falls in a gap / outside any track. */
export function genomeIndexAt(
  y: number,
  trackCount: number,
  layout: TrackLayout = DEFAULT_LAYOUT,
): number | null {
  for (let i = 0; i < trackCount; i++) {
    const top = trackY(i, layout)
    if (y >= top && y < top + layout.trackHeight) return i
  }
  return null
}
