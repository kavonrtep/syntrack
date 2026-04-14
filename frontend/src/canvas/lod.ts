// Level-of-detail decision: at low zoom (few px per bp) we render block ribbons;
// at high zoom we render individual SCM lines. Threshold from server config.

export type LODMode = 'block' | 'scm'

/** thresholdBpPerPx is the design's `block_threshold_bp_per_px`. Default 50_000.
 *  When a single pixel covers MORE than `thresholdBpPerPx` basepairs, we draw blocks. */
export function lodMode(pixelsPerBp: number, thresholdBpPerPx: number): LODMode {
  if (pixelsPerBp <= 0) return 'block'
  // Equivalent to (1/ppb) >= threshold, but multiplication avoids a fp round-trip
  // that breaks the equality at the knife-edge.
  return pixelsPerBp * thresholdBpPerPx <= 1 ? 'block' : 'scm'
}
