import { describe, expect, it } from 'vitest'

import {
  bpToPx,
  clampCenter,
  clampZoom,
  panByFraction,
  pixelsPerBp,
  pxToBp,
  visibleRange,
  zoomAtFraction,
  type Viewport,
} from './coords'

const ZOOM_OUT: Viewport = { zoom: 1, center: 0.5 }

describe('pixelsPerBp', () => {
  it('zoom=1 means whole genome fits canvas', () => {
    expect(pixelsPerBp(ZOOM_OUT, 1000, 100)).toBeCloseTo(0.1)
  })

  it('zoom=2 means twice as many pixels per bp', () => {
    expect(pixelsPerBp({ zoom: 2, center: 0.5 }, 1000, 100)).toBeCloseTo(0.2)
  })

  it('returns 0 for degenerate inputs', () => {
    expect(pixelsPerBp(ZOOM_OUT, 0, 100)).toBe(0)
    expect(pixelsPerBp(ZOOM_OUT, 1000, 0)).toBe(0)
  })
})

describe('visibleRange', () => {
  it('zoom=1 covers full genome', () => {
    expect(visibleRange(ZOOM_OUT, 1000, 100)).toEqual({ startBp: 0, endBp: 1000 })
  })

  it('zoom=2 centered shows middle half', () => {
    expect(visibleRange({ zoom: 2, center: 0.5 }, 1000, 100)).toEqual({
      startBp: 250,
      endBp: 750,
    })
  })

  it('clamps to [0, totalLength] at boundaries', () => {
    // center=0 with zoom=2 wants startBp = -250; clamp to 0
    expect(visibleRange({ zoom: 2, center: 0 }, 1000, 100)).toEqual({
      startBp: 0,
      endBp: 500,
    })
    // center=1 wants endBp > total; clamp to total
    expect(visibleRange({ zoom: 2, center: 1 }, 1000, 100)).toEqual({
      startBp: 500,
      endBp: 1000,
    })
  })
})

describe('bpToPx / pxToBp round trip', () => {
  it('inverse of each other', () => {
    const vp: Viewport = { zoom: 4, center: 0.3 }
    for (const bp of [100, 250, 500, 750, 950]) {
      const px = bpToPx(bp, vp, 1000, 800)
      const back = pxToBp(px, vp, 1000, 800)
      expect(back).toBeCloseTo(bp, 5)
    }
  })

  it('left edge bp = visible startBp', () => {
    const vp: Viewport = { zoom: 4, center: 0.5 }
    const { startBp } = visibleRange(vp, 1000, 800)
    expect(pxToBp(0, vp, 1000, 800)).toBeCloseTo(startBp)
  })
})

describe('zoomAtFraction', () => {
  it('zooming with cursor at center keeps center fixed', () => {
    const v = zoomAtFraction({ zoom: 1, center: 0.5 }, 0.5, 2)
    expect(v.zoom).toBe(2)
    expect(v.center).toBeCloseTo(0.5)
  })

  it('zooming at left edge pulls center toward the left', () => {
    const v = zoomAtFraction({ zoom: 1, center: 0.5 }, 0, 2)
    // The bp at the left edge before (fraction 0.0) should remain at left after.
    // Before: cursorFraction=0, fBefore = 0.5 + (0 - 0.5)/1 = 0.0
    // After:  newCenter = 0.0 - (0 - 0.5)/2 = 0.25
    expect(v.center).toBeCloseTo(0.25)
  })

  it('cursor pinpoint is preserved by composition', () => {
    const before: Viewport = { zoom: 1.5, center: 0.4 }
    const cursor = 0.7
    const total = 1000
    const width = 800
    const bpUnderCursorBefore = pxToBp(cursor * width, before, total, width)
    const after = zoomAtFraction(before, cursor, 3)
    const bpUnderCursorAfter = pxToBp(cursor * width, after, total, width)
    expect(bpUnderCursorAfter).toBeCloseTo(bpUnderCursorBefore, 3)
  })

  it('clamps zoom to [1, max]', () => {
    expect(zoomAtFraction({ zoom: 1, center: 0.5 }, 0.5, 0.1).zoom).toBe(1)
  })
})

describe('panByFraction', () => {
  it('positive delta moves view right (center decreases? — convention)', () => {
    // panBy +0.1 means: the canvas image shifts +0.1 (content moves right under viewer).
    // Viewer sees content from earlier in the genome → center decreases.
    const v = panByFraction({ zoom: 1, center: 0.5 }, 0.1)
    expect(v.center).toBeCloseTo(0.4)
  })

  it('clamps to [0,1]', () => {
    expect(panByFraction({ zoom: 1, center: 0.5 }, 1.0).center).toBe(0)
    expect(panByFraction({ zoom: 1, center: 0.5 }, -1.0).center).toBe(1)
  })

  it('zoomed-in pan moves less in genome-space', () => {
    const v = panByFraction({ zoom: 4, center: 0.5 }, 0.1)
    // pan by 10% of canvas = 10%/4 = 2.5% of genome
    expect(v.center).toBeCloseTo(0.475)
  })
})

describe('clamp helpers', () => {
  it('clampCenter', () => {
    expect(clampCenter(-0.1)).toBe(0)
    expect(clampCenter(1.1)).toBe(1)
    expect(clampCenter(0.5)).toBe(0.5)
  })

  it('clampZoom', () => {
    expect(clampZoom(0.5)).toBe(1)
    expect(clampZoom(1e9)).toBe(1e6)
    expect(clampZoom(100)).toBe(100)
  })
})
