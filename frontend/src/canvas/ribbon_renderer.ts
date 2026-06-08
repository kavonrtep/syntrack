// Main-thread handle for the connection (ribbon/SCM) layer.
//
// When OffscreenCanvas + Worker are available it transfers the canvas to a
// worker and forwards data/view messages; otherwise it draws on the main
// thread with the exact same code path (drawRibbons / drawScmLines). Callers
// don't care which: they push data via setData() and frames via render(); the
// renderer keeps the last of each and repaints when either changes.

import { DEFAULT_VIEWPORT } from './coords'
import { drawRibbons } from './draw_ribbons'
import { drawScmLines } from './draw_scms'
import type { RibbonData, RibbonView } from './ribbon_protocol'

function supportsOffscreen(): boolean {
  return (
    typeof OffscreenCanvas !== 'undefined' &&
    typeof Worker !== 'undefined' &&
    typeof HTMLCanvasElement !== 'undefined' &&
    'transferControlToOffscreen' in HTMLCanvasElement.prototype
  )
}

export class RibbonRenderer {
  /** True when drawing happens in a worker; false when on the main thread. */
  readonly offscreen: boolean
  private worker: Worker | null = null
  private readonly canvas: HTMLCanvasElement
  private data: RibbonData | null = null
  private view: RibbonView | null = null

  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas
    let ok = false
    if (supportsOffscreen()) {
      try {
        const offscreen = canvas.transferControlToOffscreen()
        this.worker = new Worker(new URL('./ribbon_worker.ts', import.meta.url), {
          type: 'module',
        })
        this.worker.postMessage({ type: 'init', canvas: offscreen }, [offscreen])
        ok = true
      } catch {
        // transferControlToOffscreen can throw (already transferred, or the
        // browser lacks worker module support); fall back to main-thread draw.
        this.worker?.terminate()
        this.worker = null
        ok = false
      }
    }
    this.offscreen = ok
  }

  setData(data: RibbonData): void {
    this.data = data
    if (this.worker) this.worker.postMessage({ type: 'data', data })
    else this.drawMain()
  }

  render(view: RibbonView): void {
    this.view = view
    if (this.worker) this.worker.postMessage({ type: 'render', view })
    else this.drawMain()
  }

  dispose(): void {
    this.worker?.terminate()
    this.worker = null
  }

  // ---- main-thread fallback (no worker) ----

  private drawMain(): void {
    if (!this.data || !this.view) return
    const view = this.view
    const ctx = this.sizeContext(view.canvasWidth, view.canvasHeight, view.dpr)
    if (!ctx) return
    const colorMap = new Map(this.data.colorMap)
    const fn = (id: string) => view.viewports[id] ?? DEFAULT_VIEWPORT
    if (view.lodMode === 'scm') {
      drawScmLines(ctx, this.data.pairsScms, fn, view.canvasWidth, view.canvasHeight, colorMap, view.fade)
    } else {
      drawRibbons(ctx, this.data.pairs, fn, view.canvasWidth, view.canvasHeight, colorMap, view.fade)
    }
  }

  private sizeContext(w: number, h: number, dpr: number): CanvasRenderingContext2D | null {
    const wi = Math.floor(w * dpr)
    const hi = Math.floor(h * dpr)
    if (this.canvas.width !== wi) this.canvas.width = wi
    if (this.canvas.height !== hi) this.canvas.height = hi
    this.canvas.style.width = `${w}px`
    this.canvas.style.height = `${h}px`
    const ctx = this.canvas.getContext('2d')
    if (!ctx) return null
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    return ctx
  }
}
