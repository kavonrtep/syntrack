import { describe, expect, it } from 'vitest'

import { alignmentDelta } from './alignment'
import { bpToPx, type Viewport } from './coords'

const GLOBAL: Viewport = { zoom: 1, center: 0.5 }

describe('alignmentDelta', () => {
  it('produces identity when anchor == target and click is at the mapped bp', () => {
    // Anchor at (zoom=1, center=0.5) on 1000 bp shows [0, 1000]. bp=500 lands at x=400 (canvas 800).
    const d = alignmentDelta({
      anchorVp: { zoom: 1, center: 0.5 },
      anchorTotalLen: 1000,
      targetTotalLen: 1000,
      canvasWidth: 800,
      bpTarget: 500,
      xClick: 400,
      globalVp: GLOBAL,
    })
    expect(d.zoomFactor).toBeCloseTo(1)
    expect(d.centerDelta).toBeCloseTo(0)
  })

  it('places bpTarget at xClick after applying the delta', () => {
    // Non-trivial case: different genome lengths, off-center click.
    const anchorVp: Viewport = { zoom: 3, center: 0.4 }
    const d = alignmentDelta({
      anchorVp,
      anchorTotalLen: 1_000_000,
      targetTotalLen: 5_000_000,
      canvasWidth: 1200,
      bpTarget: 2_345_678,
      xClick: 300,
      globalVp: { zoom: 2, center: 0.3 },
    })
    // Reconstruct the target's effective viewport from the delta.
    const targetVp: Viewport = {
      zoom: 2 * d.zoomFactor,
      center: 0.3 + d.centerDelta,
    }
    const x = bpToPx(2_345_678, targetVp, 5_000_000, 1200)
    expect(x).toBeCloseTo(300, 3)
  })

  it('matches bp-per-pixel between anchor and target', () => {
    const anchorVp: Viewport = { zoom: 4, center: 0.5 }
    const anchorTotalLen = 2_000_000
    const targetTotalLen = 10_000_000
    const W = 1000
    const d = alignmentDelta({
      anchorVp,
      anchorTotalLen,
      targetTotalLen,
      canvasWidth: W,
      bpTarget: 5_000_000,
      xClick: 500,
      globalVp: GLOBAL,
    })
    const ppbAnchor = (W / anchorTotalLen) * anchorVp.zoom
    const targetZoom = GLOBAL.zoom * d.zoomFactor
    const ppbTarget = (W / targetTotalLen) * targetZoom
    expect(ppbTarget).toBeCloseTo(ppbAnchor, 9)
  })

  it('survives non-center global viewport (delta is relative)', () => {
    const globalVp: Viewport = { zoom: 1.7, center: 0.123 }
    const d = alignmentDelta({
      anchorVp: { zoom: 2, center: 0.5 },
      anchorTotalLen: 800_000,
      targetTotalLen: 1_600_000,
      canvasWidth: 640,
      bpTarget: 900_000,
      xClick: 100,
      globalVp,
    })
    // Reconstructing: the target's center = globalVp.center + centerDelta.
    const targetVp: Viewport = {
      zoom: globalVp.zoom * d.zoomFactor,
      center: globalVp.center + d.centerDelta,
    }
    const x = bpToPx(900_000, targetVp, 1_600_000, 640)
    expect(x).toBeCloseTo(100, 3)
  })
})
