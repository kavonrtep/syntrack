// Main-thread handle for the connection (ribbon/SCM) layer.
//
// By default it draws on the main thread (the proven path). When explicitly
// enabled (and supported) it transfers the canvas to a worker and forwards
// data/view messages instead. Either way callers push data via setData() and
// frames via render(); the handle keeps the last of each and repaints when
// either changes.
//
// Robustness: every public call is wrapped so a worker/clone/context failure
// can never throw into a Svelte effect (which would crash the component and
// freeze the UI). The worker is created BEFORE the one-shot
// transferControlToOffscreen so a synchronous Worker-construction failure
// leaves the canvas intact for the main-thread fallback.

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
  /** Set if a worker error makes the (already-transferred) canvas unusable. */
  private dead = false

  constructor(canvas: HTMLCanvasElement, useWorker: boolean) {
    this.canvas = canvas
    let ok = false
    if (useWorker && supportsOffscreen()) {
      try {
        // Construct the worker first; only commit the one-shot canvas transfer
        // once it exists, so a synchronous failure here keeps the canvas usable.
        const worker = new Worker(new URL('./ribbon_worker.ts', import.meta.url), {
          type: 'module',
        })
        worker.onerror = () => {
          // The module failed to load/run after we already transferred the
          // canvas — we can't get a 2D context back, so just stop drawing.
          this.dead = true
        }
        const offscreen = canvas.transferControlToOffscreen()
        worker.postMessage({ type: 'init', canvas: offscreen }, [offscreen])
        this.worker = worker
        ok = true
      } catch {
        this.worker?.terminate()
        this.worker = null
        ok = false
      }
    }
    this.offscreen = ok
  }

  setData(data: RibbonData): void {
    this.data = data
    this.flush('data')
  }

  render(view: RibbonView): void {
    this.view = view
    this.flush('render')
  }

  dispose(): void {
    try {
      this.worker?.terminate()
    } catch {
      /* ignore */
    }
    this.worker = null
  }

  private flush(kind: 'data' | 'render'): void {
    if (this.dead) return
    try {
      if (this.worker) {
        if (kind === 'data' && this.data) this.worker.postMessage({ type: 'data', data: this.data })
        else if (kind === 'render' && this.view)
          this.worker.postMessage({ type: 'render', view: this.view })
      } else {
        this.drawMain()
      }
    } catch {
      // A postMessage clone error or a draw failure must never propagate into
      // the effect that called us; degrade to "no ribbon" instead of a crash.
      this.dead = !!this.worker
    }
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
