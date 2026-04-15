// Viewport math for double-click alignment (v0.1.2).
//
// Given a clicked pixel X on an anchor genome and the syntenic bp on a target
// genome, compute the ScopeDelta (zoomFactor + centerDelta) that makes the
// target show `bpTarget` at exactly the same pixel X, at the same bp-per-pixel
// as the anchor. Deltas ride on top of the global viewport — subsequent
// global zoom/pan still applies uniformly.

import type { Viewport } from './coords'

export type ScopeDelta = { zoomFactor: number; centerDelta: number }

export type AlignmentInputs = {
  /** Effective viewport of the anchor genome right now. */
  anchorVp: Viewport
  anchorTotalLen: number
  targetTotalLen: number
  canvasWidth: number
  /** Syntenic basepair on the target genome (global, i.e. seq.offset + local). */
  bpTarget: number
  /** Cursor X in canvas-local pixels at click time. */
  xClick: number
  /** Current global viewport (the one the delta is relative to). */
  globalVp: Viewport
}

export function alignmentDelta(inp: AlignmentInputs): ScopeDelta {
  const {
    anchorVp,
    anchorTotalLen,
    targetTotalLen,
    canvasWidth,
    bpTarget,
    xClick,
    globalVp,
  } = inp

  // Match basewise resolution.
  const ppbAnchor = (canvasWidth / anchorTotalLen) * anchorVp.zoom
  const zoomTarget = (ppbAnchor * targetTotalLen) / canvasWidth

  // Target center placing bpTarget at xClick:
  //   bpToPx(bpTarget, targetVp) = (bpTarget − startBp) · ppb = xClick
  //   startBp = center·L − W/(2·ppb)  ⇒  center = bp/L + (W/2 − xClick)/(W·zoom)
  // and W·zoom = ppb·L, so:
  const centerTarget =
    bpTarget / targetTotalLen + (canvasWidth / 2 - xClick) / (ppbAnchor * targetTotalLen)

  return {
    zoomFactor: zoomTarget / globalVp.zoom,
    centerDelta: centerTarget - globalVp.center,
  }
}
