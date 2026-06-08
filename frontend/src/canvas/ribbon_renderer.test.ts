import { describe, expect, it, vi } from 'vitest'

import type { RibbonData, RibbonView } from './ribbon_protocol'
import { RibbonRenderer } from './ribbon_renderer'

const EMPTY_DATA: RibbonData = { pairs: [], pairsScms: [], colorMap: [] }
const VIEW: RibbonView = {
  viewports: {},
  canvasWidth: 800,
  canvasHeight: 600,
  dpr: 1,
  fade: 1,
  lodMode: 'block',
}

describe('RibbonRenderer (main-thread fallback)', () => {
  it('falls back to main thread when OffscreenCanvas transfer is unavailable', () => {
    // happy-dom has no transferControlToOffscreen, so this path is exercised.
    const canvas = document.createElement('canvas')
    canvas.getContext = (() => null) as unknown as HTMLCanvasElement['getContext']
    const r = new RibbonRenderer(canvas)
    expect(r.offscreen).toBe(false)
    // No worker: data/render with a null context must be safe no-ops.
    expect(() => r.setData(EMPTY_DATA)).not.toThrow()
    expect(() => r.render(VIEW)).not.toThrow()
    expect(() => r.dispose()).not.toThrow()
  })

  it('draws to the 2D context once both data and a view have arrived', () => {
    const clearRect = vi.fn()
    const ctxMock = {
      clearRect,
      setTransform: vi.fn(),
      fill: vi.fn(),
      stroke: vi.fn(),
      moveTo: vi.fn(),
      lineTo: vi.fn(),
      beginPath: vi.fn(),
    }
    const canvas = document.createElement('canvas')
    canvas.getContext = (() => ctxMock) as unknown as HTMLCanvasElement['getContext']
    const r = new RibbonRenderer(canvas)

    // Only a view, no data yet → nothing drawn.
    r.render(VIEW)
    expect(clearRect).not.toHaveBeenCalled()

    // Data arrives → renderer repaints with the cached view.
    r.setData(EMPTY_DATA)
    expect(clearRect).toHaveBeenCalled()
  })
})
