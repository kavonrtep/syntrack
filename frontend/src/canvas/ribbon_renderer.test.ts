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
  it('renders on the main thread when the worker is not requested', () => {
    const canvas = document.createElement('canvas')
    canvas.getContext = (() => null) as unknown as HTMLCanvasElement['getContext']
    const r = new RibbonRenderer(canvas, false)
    expect(r.offscreen).toBe(false)
    // Null context must be a safe no-op, never a throw into the caller.
    expect(() => r.setData(EMPTY_DATA)).not.toThrow()
    expect(() => r.render(VIEW)).not.toThrow()
    expect(() => r.dispose()).not.toThrow()
  })

  it('does not attempt a worker even if opted-in when OffscreenCanvas is unavailable', () => {
    // happy-dom has no transferControlToOffscreen, so opt-in still falls back.
    const canvas = document.createElement('canvas')
    canvas.getContext = (() => null) as unknown as HTMLCanvasElement['getContext']
    const r = new RibbonRenderer(canvas, true)
    expect(r.offscreen).toBe(false)
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
    const r = new RibbonRenderer(canvas, false)

    // Only a view, no data yet → nothing drawn.
    r.render(VIEW)
    expect(clearRect).not.toHaveBeenCalled()

    // Data arrives → renderer repaints with the cached view.
    r.setData(EMPTY_DATA)
    expect(clearRect).toHaveBeenCalled()
  })

  it('never throws into the caller when drawing fails', () => {
    // A context whose methods throw must be swallowed, not propagated.
    const canvas = document.createElement('canvas')
    canvas.getContext = (() =>
      ({
        clearRect: () => {
          throw new Error('boom')
        },
        setTransform: () => {},
      }) as unknown) as HTMLCanvasElement['getContext']
    const r = new RibbonRenderer(canvas, false)
    r.setData(EMPTY_DATA)
    expect(() => r.render(VIEW)).not.toThrow()
  })
})
